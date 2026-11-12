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
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict


ROOT = Path(__file__).resolve().parents[2]
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
