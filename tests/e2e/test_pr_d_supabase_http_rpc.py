import json
import os
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psycopg


SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
DATABASE_URL = os.environ["TEST_DATABASE_URL"]


def _assert_disposable_local_target():
    api_host = urlparse(SUPABASE_URL).hostname
    db_host = urlparse(DATABASE_URL).hostname
    assert api_host in {"127.0.0.1", "localhost"}, "E2E guard: API target is not local"
    assert db_host in {"127.0.0.1", "localhost"}, "E2E guard: database target is not local"


def _request(method, path, key, payload=None):
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = Request(f"{SUPABASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"message": "non_json_error_body"}
        return exc.code, parsed


def _rpc_payload(lab_id, run_id, baseline=3.5):
    return {
        "p_lab_id": lab_id,
        "p_gen": 990,
        "p_baseline_value": baseline,
        "p_baseline_type": "e2e-fixture",
        "p_evidence_params": {"fixture": True},
        "p_evidence_metrics": {"sample_size": 10, "passed": True},
        "p_status": "VERIFICADO",
        "p_reproducible": False,
        "p_run_id": run_id,
    }


def _rows_for(lab_id):
    status, data = _request(
        "GET",
        f"/rest/v1/lab_results?lab_id=eq.{lab_id}&select=id,params,metrics,status,evidence_count",
        SUPABASE_KEY,
    )
    assert status == 200, f"Independent REST read failed with HTTP {status}"
    return data


def test_http_rpc_persists_baseline_and_evidence_and_retry_is_idempotent():
    _assert_disposable_local_target()
    lab_id = "E2E_PRD_HTTP_IDEMPOTENT"
    first_status, first = _request(
        "POST",
        "/rest/v1/rpc/rpc_insert_baseline_and_evidence",
        SUPABASE_KEY,
        _rpc_payload(lab_id, "e2e-same-logical-run"),
    )
    second_status, second = _request(
        "POST",
        "/rest/v1/rpc/rpc_insert_baseline_and_evidence",
        SUPABASE_KEY,
        _rpc_payload(lab_id, "e2e-same-logical-run"),
    )

    assert first_status == 200, f"First RPC call failed with HTTP {first_status}"
    assert second_status == 200, f"Retry RPC call failed with HTTP {second_status}"
    assert first["id"] == second["id"]
    assert second["idempotent_replay"] is True

    rows = _rows_for(lab_id)
    baselines = [row for row in rows if row["params"].get("record_type") == "baseline"]
    evidence = [row for row in rows if row["params"].get("record_type") == "evidence"]
    assert len(baselines) == 1
    assert len(evidence) == 1
    assert evidence[0]["params"]["run_id"] == "e2e-same-logical-run"


def test_http_rpc_failure_after_baseline_insert_rolls_back_everything():
    _assert_disposable_local_target()
    lab_id = "E2E_PRD_HTTP_ROLLBACK"

    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("""
            CREATE OR REPLACE FUNCTION public.test_fail_e2e_evidence_insert()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.params ->> 'record_type' = 'evidence' THEN
                RAISE EXCEPTION 'e2e_injected_evidence_failure';
              END IF;
              RETURN NEW;
            END;
            $$;
            DROP TRIGGER IF EXISTS test_fail_e2e_evidence ON public.lab_results;
            CREATE TRIGGER test_fail_e2e_evidence
            BEFORE INSERT ON public.lab_results
            FOR EACH ROW EXECUTE FUNCTION public.test_fail_e2e_evidence_insert();
        """)

    try:
        status, _ = _request(
            "POST",
            "/rest/v1/rpc/rpc_insert_baseline_and_evidence",
            SUPABASE_KEY,
            _rpc_payload(lab_id, "e2e-rollback-run"),
        )
        assert status >= 400, "Injected failure unexpectedly returned success"
        assert _rows_for(lab_id) == [], "Failed RPC left baseline or evidence rows behind"
    finally:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("DROP TRIGGER IF EXISTS test_fail_e2e_evidence ON public.lab_results")
            conn.execute("DROP FUNCTION IF EXISTS public.test_fail_e2e_evidence_insert()")


def test_http_rpc_is_not_executable_with_anon_key():
    _assert_disposable_local_target()
    status, _ = _request(
        "POST",
        "/rest/v1/rpc/rpc_insert_baseline_and_evidence",
        SUPABASE_ANON_KEY,
        _rpc_payload("E2E_PRD_HTTP_UNAUTHORIZED", "e2e-anon-must-fail"),
    )
    assert status in {401, 403}, f"Expected denied anon RPC, received HTTP {status}"
