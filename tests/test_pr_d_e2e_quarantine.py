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
