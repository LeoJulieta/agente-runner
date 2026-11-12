"""Real HTTP/PostgREST E2E against an ephemeral PostgreSQL service only.

Unlike the quarantined legacy tests, this module proves the target identity
before connecting and is run only in a dedicated GitHub Actions service stack.
No Supabase project, production URL, or user credential is accepted.
"""
import base64
import hashlib
import hmac
import json
import os
import time
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


def _request(method, path, role="service_role", payload=None):
    token = _jwt(role)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
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

    # The database is ephemeral; remove all objects created by this module as
    # defense in depth. The service container is destroyed after the job too.
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS public.lab_results CASCADE")
        conn.execute("DROP FUNCTION IF EXISTS public.pr_d_capture_views_once(bigint, text, numeric, timestamptz, timestamptz)")
        conn.execute("DROP TABLE IF EXISTS public.youtube_shorts_log CASCADE")


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


def test_e12_capture_rpc_over_http_is_cas_and_preserves_uint64():
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
        stored = conn.execute(
            "SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored == 18446744073709551615


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
            "SELECT views_primeras_3h FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()[0]
    assert stored == 2147483648


def test_e12_direct_http_insert_and_patch_cannot_bypass_cas():
    video_id = "e12-http-direct-write-denied"
    row_id = _insert_e12_video(video_id)

    patch_status, _ = _request(
        "PATCH",
        f"/youtube_shorts_log?id=eq.{row_id}",
        payload={
            "views_primeras_3h": 888,
            "published_at": "2026-10-30T02:30:00Z",
            "sync_captured_at": "2026-10-30T05:30:00Z",
        },
    )
    assert patch_status >= 400, f"direct_patch_must_be_rejected_http_{patch_status}"

    insert_status, _ = _request(
        "POST",
        "/youtube_shorts_log",
        payload={
            "youtube_video_id": "e12-http-direct-insert-denied",
            "views_primeras_3h": 888,
        },
    )
    assert insert_status >= 400, f"direct_insert_must_be_rejected_http_{insert_status}"

    with psycopg.connect(DATABASE_URL) as conn:
        stored = conn.execute(
            "SELECT views_primeras_3h, published_at, sync_captured_at "
            "FROM public.youtube_shorts_log WHERE id = %s",
            (row_id,),
        ).fetchone()
        direct_insert_count = conn.execute(
            "SELECT count(*) FROM public.youtube_shorts_log "
            "WHERE youtube_video_id = 'e12-http-direct-insert-denied'"
        ).fetchone()[0]
    assert stored == (None, None, None)
    assert direct_insert_count == 0


def test_lab_results_direct_insert_is_denied_to_service_role():
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("SET ROLE service_role")
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege,
            match="prd_lab_results_insert_requires_atomic_rpc",
        ):
            conn.execute(
                """
                INSERT INTO public.lab_results
                    (lab_id, gen, params, metrics, status, evidence_count, reproducible, last_test)
                VALUES
                    ('DIRECT_INSERT_BYPASS_ATTEMPT', 1, '{}'::jsonb, '{}'::jsonb,
                     'VERIFICADO', 1, false, now())
                """
            )

    status, _ = _request(
        "POST",
        "/lab_results",
        payload={
            "lab_id": "DIRECT_HTTP_INSERT_BYPASS_ATTEMPT",
            "gen": 1,
            "params": {},
            "metrics": {},
            "status": "VERIFICADO",
            "evidence_count": 1,
            "reproducible": False,
        },
    )
    assert status >= 400, f"direct_lab_results_post_must_be_rejected_http_{status}"


def test_atomic_lab_results_rpc_is_the_only_service_role_insert_capability():
    with psycopg.connect(DATABASE_URL) as conn:
        wrapper_signature = (
            "public.rpc_insert_baseline_and_evidence("
            "text,integer,jsonb,text,jsonb,jsonb,text,boolean,text)"
        )
        implementation_signature = (
            "public.pr_d_rpc_insert_baseline_and_evidence_impl("
            "text,integer,jsonb,text,jsonb,jsonb,text,boolean,text)"
        )
        wrapper_execute, implementation_execute = conn.execute(
            """
            SELECT
                has_function_privilege('service_role', %s, 'EXECUTE'),
                has_function_privilege('service_role', %s, 'EXECUTE')
            """,
            (wrapper_signature, implementation_signature),
        ).fetchone()
        wrapper_owner = conn.execute(
            """
            SELECT pg_get_userbyid(proowner)
            FROM pg_proc
            WHERE oid = %s::regprocedure
            """,
            (wrapper_signature,),
        ).fetchone()[0]
        writer_memberships = conn.execute(
            """
            SELECT count(*) FROM pg_auth_members
            WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname='pr_d_lab_results_writer')
               OR member = (SELECT oid FROM pg_roles WHERE rolname='pr_d_lab_results_writer')
            """
        ).fetchone()[0]
    assert wrapper_execute is True
    assert implementation_execute is False
    assert wrapper_owner == "pr_d_lab_results_writer"
    assert writer_memberships == 0


def test_service_role_cannot_truncate_protected_lab_tables():
    with psycopg.connect(DATABASE_URL) as conn:
        lab_truncate = conn.execute(
            "SELECT has_table_privilege('service_role', 'public.lab_results', 'TRUNCATE')"
        ).fetchone()[0]
        capture_truncate = conn.execute(
            "SELECT has_table_privilege('service_role', 'public.youtube_shorts_log', 'TRUNCATE')"
        ).fetchone()[0]
        assert lab_truncate is False
        assert capture_truncate is False

        conn.execute("SET ROLE service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE TABLE public.lab_results")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("TRUNCATE TABLE public.youtube_shorts_log")
