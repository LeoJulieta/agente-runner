from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import uuid

import psycopg

POSTGREST_URL = os.environ["POSTGREST_URL"].rstrip("/")
JWT_SECRET = os.environ["PGRST_JWT_SECRET"].encode("utf-8")
DATABASE_URL = os.environ["TEST_DATABASE_URL"]
RUN_A = uuid.UUID("11111111-2222-4333-8444-555555555555")
RUN_B = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
PUBLISHED = "2026-10-30T02:30:00Z"
CAPTURED = "2026-10-30T05:30:00.123456Z"
PUBLIC_KEY = "MCowBQYDK2VwAyEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
HMAC_SECRET = bytes([7]) * 32
KEY_ID = "e12-test-key"
RESPONSE_SHA = "a" * 64
REQUESTED_IDS_SHA = "b" * 64
COLLECTOR_BUILD = "e12-collector/0.1.0"
SIGNATURE = "A" * 86 + "=="


def b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def jwt_for(role: str) -> str:
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64url(json.dumps(
        {"role": role, "exp": int(time.time()) + 300},
        separators=(",", ":"),
    ).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = hmac.new(JWT_SECRET, signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{b64url(signature)}"


def rpc(name: str, body: dict, role: str = "service_role"):
    request = urllib.request.Request(
        f"{POSTGREST_URL}/rpc/{name}",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {jwt_for(role)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def batch_item(run_id, token, row_id: int, video_id: str, views: str = "123"):
    canonical = json.dumps([
        "e12-observation-attestation/v1",
        KEY_ID,
        str(run_id),
        str(token),
        str(row_id),
        video_id,
        PUBLISHED,
        views,
        CAPTURED,
        RESPONSE_SHA,
        REQUESTED_IDS_SHA,
        COLLECTOR_BUILD,
    ], separators=(",", ":"), ensure_ascii=False)
    canonical_bytes = canonical.encode("utf-8")
    return {
        "p_row_id": str(row_id),
        "p_youtube_video_id": video_id,
        "p_views": views,
        "p_published_at": PUBLISHED,
        "p_sync_captured_at": CAPTURED,
        "p_run_id": str(run_id),
        "p_fencing_token": str(token),
        "p_attestation_version": "e12-observation-attestation/v1",
        "p_attestation_algorithm": "Ed25519",
        "p_collector_key_id": KEY_ID,
        "p_collector_public_key_spki_base64": PUBLIC_KEY,
        "p_collector_payload_canonical": canonical,
        "p_collector_payload_sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "p_collector_signature": SIGNATURE,
        "p_collector_hmac_signature": hmac.new(
            HMAC_SECRET, canonical_bytes, hashlib.sha256
        ).hexdigest(),
        "p_collector_response_sha256": RESPONSE_SHA,
        "p_collector_requested_ids_sha256": REQUESTED_IDS_SHA,
        "p_collector_build": COLLECTOR_BUILD,
    }


def test_postgrest_batch_rpc_roundtrip_and_role_boundary():
    # PostgREST is a real HTTP server backed by the disposable PostgreSQL 17
    # service. The worker's sb_secret->JWT gateway translation is not emulated
    # here; this test validates PostgREST RPC binding and SQL authorization.
    # Use dedicated IDs that cannot overlap with the Deno worker E2E fixtures.
    # That test runs first against the same disposable database.
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO public.youtube_shorts_log(id, youtube_video_id, status, created_at)
            VALUES
                (101, 'e12-python-rpc-video-101', 'published', clock_timestamp()),
                (102, 'e12-python-rpc-video-102', 'published', clock_timestamp())
            """
        )

    claim = rpc("pr_d_claim_e12_worker_lease", {
        "p_run_id": str(RUN_A),
        "p_ttl_seconds": 90,
    })
    assert isinstance(claim, list) and len(claim) == 1
    assert claim[0]["acquired"] is True
    token_a = str(claim[0]["fencing_token"])

    first = rpc("pr_d_capture_views_batch", {
        "p_items": [batch_item(RUN_A, token_a, 101, "e12-python-rpc-video-101", "123")],
    })
    assert first == [{"row_id": "101", "captured": True}]

    duplicate = rpc("pr_d_capture_views_batch", {
        "p_items": [batch_item(RUN_A, token_a, 101, "e12-python-rpc-video-101", "999")],
    })
    assert duplicate == [{"row_id": "101", "captured": False}]

    assert rpc("pr_d_release_e12_worker_lease", {
        "p_run_id": str(RUN_A),
        "p_fencing_token": token_a,
    }) is True

    claim_b = rpc("pr_d_claim_e12_worker_lease", {
        "p_run_id": str(RUN_B),
        "p_ttl_seconds": 90,
    })
    token_b = str(claim_b[0]["fencing_token"])
    assert int(token_b) == int(token_a) + 1

    stale = rpc("pr_d_capture_views_batch", {
        "p_items": [batch_item(RUN_A, token_a, 102, "e12-python-rpc-video-102", "456")],
    })
    assert stale == [{"row_id": "102", "captured": False}]

    current = rpc("pr_d_capture_views_batch", {
        "p_items": [batch_item(RUN_B, token_b, 102, "e12-python-rpc-video-102", "456")],
    })
    assert current == [{"row_id": "102", "captured": True}]

    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT id, views_primeras_3h, e12_fencing_token "
            "FROM public.youtube_shorts_log WHERE id IN (101,102) ORDER BY id"
        ).fetchall()
        assert rows == [(101, 123, int(token_a)), (102, 456, int(token_b))]

    # The public wrapper is intentionally not executable by anon.
    try:
        rpc("pr_d_capture_views_batch", {"p_items": []}, role="anon")
    except urllib.error.HTTPError as error:
        assert error.code in (401, 403, 404)
    else:
        raise AssertionError("anon unexpectedly executed the batch RPC")
