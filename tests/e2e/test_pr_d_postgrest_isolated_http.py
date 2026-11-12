"""Real HTTP/PostgREST E2E against an ephemeral PostgreSQL service only.

This module proves that service_role cannot forge, replace, or delete an E12
capture through direct table DML, while the public CAS wrapper succeeds and
the restricted helper remains outside PostgREST's exposed schema.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict


API_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
JWT_SECRET = os.getenv("PR_D_TEST_JWT_SECRET", "")
DISPOSABLE_MARKER = os.getenv("PR_D_DISPOSABLE_DATABASE")
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _assert_disposable_target():
    assert DISPOSABLE_MARKER == "1", "disposable_database_opt_in_required"
    assert API_URL, "local_postgrest_url_required"
    assert JWT_SECRET and len(JWT_SECRET.encode("utf-8")) >= 32, "test_only_jwt_secret_required"
    api_host = urlparse(API_URL).hostname
    assert api_host in ALLOWED_HOSTS, "postgrest_api_must_be_loopback"
    params = conninfo_to_dict(DATABASE_URL)
    hosts = params.get("host", "").split(",")
    assert hosts and all(host.strip().strip("[]").lower() in ALLOWED_HOSTS for host in hosts), (
        "database_must_be_loopback"
    )
    assert params.get("dbname") == "prd_test" and params.get("user") == "prd_test", (
        "database_identity_mismatch"
    )


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(role):
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps({"role": role, "exp": int(time.time()) + 300}, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64url(hmac.new(JWT_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def _request(method, path, role="service_role", payload=None, extra_headers=None):
    token = _jwt(role)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(f"{API_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"message": "non_json_error_body"}
        return exc.code, parsed


def _payload(lab_id, run_id):
    return {
        "p_lab_id": lab_id,
        "p_gen": 990,
        "p_baseline_value": 3.5,
        "p_baseline_type": "isolated-postgrest-e2e",
        "p_evidence_params": {"fixture": True},
        "p_evidence_metrics": {"sample_size": 10, "passed": True},
        "p_status": "VERIFICADO",
        "p_reproducible": False,
        "p_run_id": run_id,
    }


@pytest.fixture(scope="module", autouse=True)
def disposable_postgrest_database():
    _assert_disposable_target()
    # Wait for the API to finish startup and load the RPC schema cache.
    last_error = None
    for _ in range(40):
        try:
            status, _ = _request("GET", "/")
            if status in {200, 400, 401, 403}:
                break
        except (URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(1)
    else:
        pytest.fail(f"postgrest_not_ready: {type(last_error).__name__ if last_error else 'schema_cache_timeout'}")

    yield

    # The DB is ephemeral; clean the E12 objects before the service container
    # is destroyed. This teardown is never pointed at a hosted Supabase project.
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS public.lab_results CASCADE")
        conn.execute(
            "DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(bigint, text, numeric, timestamptz, timestamptz)"
        )
        conn.execute("DROP FUNCTION IF EXISTS public.pr_d_guard_capture_fields()")
        conn.execute("DROP TABLE IF EXISTS public.youtube_shorts_log CASCADE")
        conn.execute("DROP SCHEMA IF EXISTS pr_d_internal CASCADE")
        conn.execute("REVOKE ALL ON SCHEMA public FROM pr_d_capture_owner")
        conn.execute("DROP ROLE IF EXISTS pr_d_capture_owner")


def _rows(lab_id):
    query = urlencode({
        "lab_id": f"eq.{lab_id}",
        "select": "id,params,metrics,status,evidence_count",
    })
    status, rows = _request("GET", f"/lab_results?{query}")
    assert status == 200, f"independent_rest_read_failed_http_{status}"
    return rows


def test_http_rpc_persists_once_and_retry_is_idempotent():
    lab_id = "E2E_POSTGREST_IDEMPOTENT"
    first_status, first = _request(
        "POST", "/rpc/rpc_insert_baseline_and_evidence",
        payload=_payload(lab_id, "same-logical-run"),
    )
    second_status, second = _request(
        "POST", "/rpc/rpc_insert_baseline_and_evidence",
        payload=_payload(lab_id, "same-logical-run"),
    )
    assert first_status == second_status == 200
    assert first["id"] == second["id"]
    assert second["idempotent_replay"] is True

    rows = _rows(lab_id)
    baselines = [row for row in rows if row["params"].get("record_type") == "baseline"]
    evidence = [row for row in rows if row["params"].get("record_type") == "evidence"]
    assert len(baselines) == len(evidence) == 1
    assert evidence[0]["params"]["run_id"] == "same-logical-run"


def test_http_rpc_rolls_back_when_evidence_insert_fails():
    lab_id = "E2E_POSTGREST_ROLLBACK"
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("""
            CREATE OR REPLACE FUNCTION public.test_prd_http_fail_evidence()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.params ->> 'record_type' = 'evidence' THEN
                RAISE EXCEPTION 'prd_http_injected_evidence_failure';
              END IF;
              RETURN NEW;
            END;
            $$;
            DROP TRIGGER IF EXISTS test_prd_http_fail_evidence ON public.lab_results;
            CREATE TRIGGER test_prd_http_fail_evidence
            BEFORE INSERT ON public.lab_results
            FOR EACH ROW EXECUTE FUNCTION public.test_prd_http_fail_evidence();
        """)

    try:
        status, _ = _request(
            "POST", "/rpc/rpc_insert_baseline_and_evidence",
            payload=_payload(lab_id, "rollback-run"),
        )
        assert status >= 400
        assert _rows(lab_id) == []
    finally:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_prd_http_fail_evidence ON public.lab_results")
            conn.execute("DROP FUNCTION IF EXISTS public.test_prd_http_fail_evidence()")


def test_anon_role_cannot_execute_privileged_rpc():
    status, _ = _request(
        "POST", "/rpc/rpc_insert_baseline_and_evidence",
        role="anon",
        payload=_payload("E2E_POSTGREST_ANON_DENIED", "anon-run"),
    )
    assert status in {401, 403}, f"anon_rpc_must_be_denied_http_{status}"
    assert _rows("E2E_POSTGREST_ANON_DENIED") == []


def _insert_e12_video(video_id):
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(
            "INSERT INTO public.youtube_shorts_log (youtube_video_id) VALUES (%s) RETURNING id",
            (video_id,),
        ).fetchone()[0]


def test_e12_direct_http_dml_cannot_forge_or_replace_capture():
    row_id = _insert_e12_video("e12-http-direct-bypass")
    query = urlencode({"id": f"eq.{row_id}"})
    forged = {
        "views_primeras_3h": "77",
        "published_at": "2026-10-30T02:30:00Z",
        "sync_captured_at": "2026-10-30T05:30:00Z",
        "elapsed_seconds_e12": 10800,
        "hs_al_publicar_al_sync": 3,
    }
    status, _ = _request("PATCH", f"/youtube_shorts_log?{query}", payload=forged)
    assert status >= 400, f"direct_capture_patch_must_be_denied_http_{status}"

    status, _ = _request("POST", "/youtube_shorts_log", payload={
        "youtube_video_id": "e12-http-forged-insert",
        **forged,
    })
    assert status >= 400, f"direct_capture_insert_must_be_denied_http_{status}"

    # Unrelated metadata updates are intentionally unaffected by the guard.
    status, _ = _request(
        "PATCH", f"/youtube_shorts_log?{query}",
        payload={"status": "published"},
    )
    assert status in {200, 204}, f"unrelated_metadata_update_should_work_http_{status}"

    with psycopg.connect(DATABASE_URL) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at,
                   elapsed_seconds_e12, hs_al_publicar_al_sync, status
            FROM public.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored == (None, None, None, None, None, "published")


def test_e12_capture_rpc_over_http_is_cas_and_preserves_uint64_and_elapsed():
    video_id = "e12-http-uint64"
    row_id = _insert_e12_video(video_id)
    payload = {
        "p_row_id": row_id,
        "p_youtube_video_id": video_id,
        "p_views": "18446744073709551615",
        "p_published_at": "2026-10-30T02:30:00Z",
        "p_sync_captured_at": "2026-10-30T05:30:00Z",
    }
    first_status, first = _request("POST", "/rpc/pr_d_capture_views_once", payload=payload)
    second_status, second = _request("POST", "/rpc/pr_d_capture_views_once", payload=payload)
    assert first_status == second_status == 200
    assert first is True
    assert second is False

    with psycopg.connect(DATABASE_URL) as conn:
        stored = conn.execute("""
            SELECT views_primeras_3h, published_at, sync_captured_at,
                   elapsed_seconds_e12, hs_al_publicar_al_sync
            FROM public.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored[0] == 18446744073709551615
    assert stored[1].isoformat() == "2026-10-30T02:30:00+00:00"
    assert stored[2].isoformat() == "2026-10-30T05:30:00+00:00"
    assert stored[3] == Decimal("10800")
    assert stored[4] is None


def test_e12_captured_video_cannot_be_reassigned_or_deleted_over_http():
    video_id = "e12-http-immutable-identity"
    row_id = _insert_e12_video(video_id)
    payload = {
        "p_row_id": row_id,
        "p_youtube_video_id": video_id,
        "p_views": "123",
        "p_published_at": "2026-10-30T02:30:00Z",
        "p_sync_captured_at": "2026-10-30T05:30:00Z",
    }
    status, result = _request("POST", "/rpc/pr_d_capture_views_once", payload=payload)
    assert status == 200 and result is True

    query = urlencode({"id": f"eq.{row_id}"})
    status, _ = _request(
        "PATCH", f"/youtube_shorts_log?{query}",
        payload={"youtube_video_id": "e12-http-reassigned"},
    )
    assert status >= 400, f"captured_video_identity_change_must_be_denied_http_{status}"

    status, _ = _request("DELETE", f"/youtube_shorts_log?{query}")
    assert status >= 400, f"captured_outcome_delete_must_be_denied_http_{status}"

    with psycopg.connect(DATABASE_URL) as conn:
        stored = conn.execute("""
            SELECT youtube_video_id, views_primeras_3h
            FROM public.youtube_shorts_log WHERE id = %s
        """, (row_id,)).fetchone()
    assert stored == (video_id, 123)


def test_e12_private_helper_schema_is_not_exposed_to_postgrest():
    payload = {
        "p_row_id": 1,
        "p_youtube_video_id": "not-reachable",
        "p_views": "1",
        "p_published_at": "2026-10-30T02:30:00Z",
        "p_sync_captured_at": "2026-10-30T05:30:00Z",
    }
    status, _ = _request(
        "POST",
        "/rpc/pr_d_capture_views_once",
        payload=payload,
        extra_headers={"Content-Profile": "pr_d_internal"},
    )
    assert status == 406, f"private_schema_must_not_be_exposed_http_{status}"


def test_e12_capture_rpc_rejects_wrong_id_outside_window_and_anon():
    row_id = _insert_e12_video("e12-http-correct")
    base = {
        "p_row_id": row_id,
        "p_youtube_video_id": "wrong-id",
        "p_views": "99",
        "p_published_at": "2026-10-30T02:30:00Z",
        "p_sync_captured_at": "2026-10-30T05:30:00Z",
    }
    status, result = _request("POST", "/rpc/pr_d_capture_views_once", payload=base)
    assert status == 200 and result is False

    outside = dict(base, p_youtube_video_id="e12-http-correct", p_sync_captured_at="2026-10-30T05:35:00.000001Z")
    status, result = _request("POST", "/rpc/pr_d_capture_views_once", payload=outside)
    assert status == 200 and result is False

    for invalid_views in ("-1", "1.5", "18446744073709551616"):
        invalid = dict(base, p_youtube_video_id="e12-http-correct", p_views=invalid_views)
        status, result = _request("POST", "/rpc/pr_d_capture_views_once", payload=invalid)
        assert status == 200 and result is False

    status, _ = _request(
        "POST", "/rpc/pr_d_capture_views_once", role="anon",
        payload=dict(base, p_youtube_video_id="e12-http-correct"),
    )
    assert status in {401, 403}
    with psycopg.connect(DATABASE_URL) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored is None


def test_e12_capture_rpc_concurrent_http_claim_has_one_winner():
    from concurrent.futures import ThreadPoolExecutor

    video_id = "e12-http-concurrent"
    row_id = _insert_e12_video(video_id)
    payload = {
        "p_row_id": row_id,
        "p_youtube_video_id": video_id,
        "p_views": "2147483648",
        "p_published_at": "2026-10-30T02:30:00Z",
        "p_sync_captured_at": "2026-10-30T05:30:00Z",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: _request("POST", "/rpc/pr_d_capture_views_once", payload=payload),
            range(2),
        ))
    assert all(status == 200 for status, _ in results)
    assert sorted(value for _, value in results) == [False, True]
    with psycopg.connect(DATABASE_URL) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h, elapsed_seconds_e12, hs_al_publicar_al_sync FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()
    assert stored == (2147483648, Decimal("10800"), None)
