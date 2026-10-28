"""Full engine -> Supabase Python client -> local PostgREST/RPC -> independent read E2E.

This test is only intended for a disposable local Supabase stack created by CI.
It refuses non-local API/database targets and never prints credentials.
"""
import json
import os
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_URL = os.environ["SUPABASE_URL"].rstrip("/")
SERVICE_KEY = os.environ["SUPABASE_KEY"]
DATABASE_URL = os.environ["TEST_DATABASE_URL"]
HYPOTHESIS = "H990_PRD_TEST_INIT"
LAB_ID = HYPOTHESIS


def _assert_local_only():
    assert urlparse(API_URL).hostname in {"127.0.0.1", "localhost"}, "E2E guard: API target is not local"
    assert urlparse(DATABASE_URL).hostname in {"127.0.0.1", "localhost"}, "E2E guard: database target is not local"


def _rest_rows():
    request = Request(
        f"{API_URL}/rest/v1/lab_results?lab_id=eq.{LAB_ID}&gen=eq.990&select=id,params,metrics,status,evidence_count",
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_engine():
    completed = subprocess.run(
        [sys.executable, "labs/lab_engine.py", "--hypothesis", HYPOTHESIS],
        text=True,
        capture_output=True,
        timeout=60,
        env=os.environ.copy(),
        check=False,
    )
    assert completed.returncode == 0, (
        f"engine failed with exit={completed.returncode}; "
        f"stdout={completed.stdout[-2000:]!r}; stderr={completed.stderr[-1000:]!r}"
    )
    try:
        return json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise AssertionError("engine did not emit a final JSON result") from exc


def test_real_engine_persists_atomically_and_retry_is_idempotent():
    _assert_local_only()
    assert os.environ.get("PRD_ORIGINAL_MANIFEST_STATUS") == "fixture"
    first = _run_engine()
    assert first["insert_ok"] is True
    assert first["lab_id"] == LAB_ID
    assert first["persistence"]["idempotent_replay"] is False
    assert first["persistence"]["baseline_created"] is True

    first_rows = _rest_rows()
    baselines = [row for row in first_rows if (row.get("params") or {}).get("record_type") == "baseline"]
    evidence = [row for row in first_rows if (row.get("params") or {}).get("record_type") == "evidence"]
    assert len(baselines) == 1
    assert len(evidence) == 1
    first_evidence_id = evidence[0]["id"]
    first_run_id = evidence[0]["params"]["run_id"]

    second = _run_engine()
    assert second["insert_ok"] is True
    assert second["run_id"] == first_run_id
    assert second["persistence"]["id"] == first_evidence_id
    assert second["persistence"]["idempotent_replay"] is True

    second_rows = _rest_rows()
    baselines_after = [row for row in second_rows if (row.get("params") or {}).get("record_type") == "baseline"]
    evidence_after = [row for row in second_rows if (row.get("params") or {}).get("record_type") == "evidence"]
    assert len(baselines_after) == 1
    assert len(evidence_after) == 1
    assert evidence_after[0]["id"] == first_evidence_id
