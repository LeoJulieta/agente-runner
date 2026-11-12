"""Fail-closed guard for HTTP E2E tests that mutate public.lab_results.

These legacy tests remain quarantined until replaced by a disposable-stack
implementation with isolated schema/table ownership and guaranteed cleanup.
"""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_UNSAFE_TESTS = (
    ROOT / "tests" / "e2e" / "test_pr_d_supabase_http_rpc.py",
    ROOT / "tests" / "e2e" / "test_pr_d_engine_http_e2e.py",
    ROOT / "tests" / "integration" / "test_pr_d_atomic_rpc.py",
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


def test_quarantined_http_e2e_files_are_not_in_candidate_ci_pytest_command():
    workflow = (ROOT / ".github" / "workflows" / "pr-d-sandbox-eligibility-schema.yml").read_text(
        encoding="utf-8"
    )
    assert "tests/e2e/test_pr_d_supabase_http_rpc.py" not in workflow
    assert "tests/e2e/test_pr_d_engine_http_e2e.py" not in workflow
    assert "tests/integration/test_pr_d_atomic_rpc.py" not in workflow
