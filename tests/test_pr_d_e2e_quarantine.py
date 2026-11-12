"""Fail-closed guard for legacy tests that mutate shared public database objects.

These modules remain quarantined until replaced by a disposable-stack
implementation with isolated schema/table ownership and guaranteed cleanup.
"""
import ast
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
LEGACY_UNSAFE_TESTS = (
    ROOT / "tests" / "e2e" / "test_pr_d_supabase_http_rpc.py",
    ROOT / "tests" / "e2e" / "test_pr_d_engine_http_e2e.py",
    ROOT / "tests" / "integration" / "test_pr_d_atomic_rpc.py",
)
FORBIDDEN_CI_TEST_PATHS = (
    "tests/e2e/test_pr_d_supabase_http_rpc.py",
    "tests/e2e/test_pr_d_engine_http_e2e.py",
    "tests/integration/test_pr_d_atomic_rpc.py",
)


def test_legacy_shared_public_schema_tests_are_explicitly_skipped():
    for path in LEGACY_UNSAFE_TESTS:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        module_skip = False
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets):
                continue
            value = node.value
            if isinstance(value, ast.Call) and ast.unparse(value.func) == "pytest.mark.skip":
                module_skip = True
                break
        assert module_skip, f"{path.name} must remain module-skipped until safely rewritten"
        assert "public.lab_results" in source, f"{path.name} quarantine rationale must identify the shared public target"


def test_quarantined_modules_never_appear_in_any_candidate_ci_test_command():
    workflow_path = ROOT / ".github" / "workflows" / "pr-d-sandbox-eligibility-schema.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    run_commands = [
        step.get("run", "")
        for job in jobs.values()
        for step in job.get("steps", [])
        if isinstance(step, dict) and isinstance(step.get("run", ""), str)
    ]
    pytest_commands = [command for command in run_commands if "pytest" in command]
    assert pytest_commands, "candidate CI must expose at least one pytest command"
    for forbidden_path in FORBIDDEN_CI_TEST_PATHS:
        assert all(forbidden_path not in command for command in pytest_commands), (
            f"{forbidden_path} must not be executed by any candidate CI pytest command"
        )


def test_candidate_ci_keeps_database_image_and_actions_immutable():
    workflow_path = ROOT / ".github" / "workflows" / "pr-d-sandbox-eligibility-schema.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    postgres = workflow["jobs"]["disposable-postgres-schema"]["services"]["postgres"]["image"]
    image, separator, digest = postgres.partition("@sha256:")
    assert separator and image.startswith("postgres:17."), "PostgreSQL service must use a versioned tag plus digest"
    assert len(digest) == 64 and all(char in "0123456789abcdef" for char in digest), (
        "PostgreSQL service must be pinned to a complete immutable sha256 digest"
    )

    windows_job = workflow["jobs"].get("windows-iana-timezone")
    assert windows_job is not None, "Windows IANA timezone coverage must remain enabled"
    assert windows_job.get("runs-on") == "windows-2025", "Windows runner generation must not follow windows-latest"
    windows_runs = [
        step.get("run", "")
        for step in windows_job.get("steps", [])
        if isinstance(step, dict)
    ]
    assert any("tests/test_pr_d_sync_cohort_estimator_e2e.py" in command for command in windows_runs), (
        "Windows job must execute the temporal/IANA integration test file"
    )

    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if uses and (uses.startswith("actions/checkout@") or uses.startswith("actions/setup-python@")):
                ref = uses.rsplit("@", 1)[1]
                assert len(ref) == 40 and all(char in "0123456789abcdef" for char in ref), (
                    f"GitHub action must be pinned to a full commit SHA: {uses}"
                )


def test_new_postgrest_http_e2e_is_separate_and_fail_closed():
    workflow_path = ROOT / ".github" / "workflows" / "pr-d-sandbox-eligibility-schema.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"].get("postgrest-http-disposable")
    assert job is not None, "isolated PostgREST HTTP job must remain explicit"
    assert "postgres" in job.get("services", {}), "HTTP job must own its disposable PostgreSQL service"
    postgres_image = job["services"]["postgres"]["image"]
    assert "@sha256:" in postgres_image, "HTTP PostgreSQL service must use immutable digest"
    steps = job.get("steps", [])
    commands = [step.get("run", "") for step in steps if isinstance(step, dict)]
    bootstrap_index = next((i for i, cmd in enumerate(commands) if "bootstrap_pr_d_postgrest.py" in cmd), None)
    start_index = next((i for i, cmd in enumerate(commands) if "docker run" in cmd and "postgrest/postgrest" in cmd), None)
    test_index = next((i for i, cmd in enumerate(commands) if "test_pr_d_postgrest_isolated_http.py" in cmd), None)
    cleanup = next((step for step in steps if isinstance(step, dict) and "docker rm -f prd-postgrest" in step.get("run", "")), None)
    assert bootstrap_index is not None and start_index is not None and test_index is not None
    assert bootstrap_index < start_index < test_index, "database identity and schema must be bootstrapped before PostgREST starts"
    assert cleanup is not None and cleanup.get("if") == "always()", "PostgREST container cleanup must run even after failures"

    safe_test = (ROOT / "tests/e2e/test_pr_d_postgrest_isolated_http.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "tests/e2e/bootstrap_pr_d_postgrest.py").read_text(encoding="utf-8")
    assert 'DISPOSABLE_MARKER == "1"' in safe_test
    assert 'params.get("dbname") == "prd_test" and params.get("user") == "prd_test"' in safe_test
    assert 'params.get("dbname") != "prd_test" or params.get("user") != "prd_test"' in bootstrap
    assert "postgrest_api_must_be_loopback" in bootstrap
    assert 'Request("GET", "/")' in safe_test, "readiness probe must not mutate database state"
    assert "readiness-probe" not in safe_test
