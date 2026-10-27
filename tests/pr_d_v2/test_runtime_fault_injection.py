"""Runtime fault-injection characterization against a fake Supabase client.

These tests execute the engine's main() control flow but never contact Supabase.
They demonstrate behavior of the current code against deterministic fake storage;
they do not prove production database transaction semantics.
"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "labs" / "lab_engine.py"


class FakeQuery:
    def __init__(self, client, table_name):
        self.client = client
        self.table_name = table_name
        self.payload = None

    def select(self, *args, **kwargs): return self
    def eq(self, *args, **kwargs): return self
    def order(self, *args, **kwargs): return self
    def limit(self, *args, **kwargs): return self
    @property
    def not_(self): return self
    def is_(self, *args, **kwargs): return self
    def lt(self, *args, **kwargs): return self
    def gte(self, *args, **kwargs): return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        if self.payload is not None:
            record_type = (self.payload.get("params") or {}).get("record_type")
            if record_type == "evidence" and self.client.fail_evidence_insert:
                raise RuntimeError("injected evidence insert failure")
            self.client.rows.append(self.payload)
            return types.SimpleNamespace(data=[self.payload])
        return types.SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self, fail_evidence_insert=False):
        self.rows = []
        self.fail_evidence_insert = fail_evidence_insert

    def table(self, table_name):
        return FakeQuery(self, table_name)


def load_engine_with_dependency_stubs():
    # Stub imports only; no real client or external service is initialized.
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda stream: {}
    supabase_stub = types.ModuleType("supabase")
    supabase_stub.create_client = lambda *args, **kwargs: None
    with mock.patch.dict(sys.modules, {"yaml": yaml_stub, "supabase": supabase_stub}):
        spec = importlib.util.spec_from_file_location("pr_d_runtime_engine", ENGINE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


engine = load_engine_with_dependency_stubs()


class RuntimeFaultInjectionTests(unittest.TestCase):
    def setUp(self):
        self.contract = {
            "id": "TEST-FAULT",
            "gen": 0,
            "class": "A",
            "dataset": ["fake_dataset"],
            "vars": {"independent": ["x"], "dependent": ["y"]},
            "sample_min": 1,
            "comparison": {"type": "greater_than"},
            "metric": {"primary": "correlation"},
        }

    def run_main(self, client, *, schema_ok=True, measure_side_effect=None):
        out = io.StringIO()
        patches = [
            mock.patch.object(engine, "create_client", return_value=client),
            mock.patch.object(engine, "load_hypothesis", return_value=self.contract),
            mock.patch.object(engine, "_load_catalog", return_value={}),
            mock.patch.object(engine, "_validate_schema_gate", return_value=(schema_ok, "injected")),
            mock.patch.object(engine, "_validate_derive_gate", return_value=(True, "")),
            mock.patch.object(engine, "_validate_contract_gate", return_value=(True, "")),
            mock.patch.object(engine, "check_class_permissions"),
            mock.patch.object(engine, "get_existing_baseline", return_value=(None, False)),
            mock.patch.object(engine, "_compute_baseline_value", return_value=(0.0, "fixed")),
            mock.patch.object(engine, "compare", return_value={"passed": True, "measured_value": 1.0}),
            mock.patch.object(engine, "_method_fingerprint", return_value="fingerprint-test"),
            mock.patch.object(sys, "argv", ["lab_engine.py", "--hypothesis", "TEST-FAULT"]),
            mock.patch.dict(os.environ, {"SUPABASE_URL": "https://fake.invalid", "SUPABASE_KEY": "not-a-secret"}),
        ]
        if measure_side_effect is not None:
            patches.append(mock.patch.object(engine, "measure", side_effect=measure_side_effect))
        else:
            patches.append(mock.patch.object(engine, "measure", return_value={
                "sample_ok": True, "correlation": 1.0, "sample_size": 10
            }))
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as raised:
                    engine.main()
        return raised.exception.code, out.getvalue()

    def test_evidence_insert_failure_leaves_baseline_in_fake_store(self):
        client = FakeSupabase(fail_evidence_insert=True)
        code, output = self.run_main(client)
        self.assertEqual(code, 1, output)
        record_types = [(r.get("params") or {}).get("record_type") for r in client.rows]
        self.assertIn("baseline", record_types)
        self.assertNotIn("evidence", record_types)
        self.assertIn("injected evidence insert failure", output)

    def test_invalid_schema_gate_exits_zero_without_persisting(self):
        client = FakeSupabase()
        code, output = self.run_main(client, schema_ok=False)
        self.assertEqual(code, 0, output)
        self.assertEqual(client.rows, [])
        self.assertIn('"status": "INVALID"', output)

    def test_measurement_runtime_error_currently_exits_one_even_when_unclassified(self):
        # Characterization only: RuntimeError is injected without an explicit
        # operational classification. Contract default for unknown errors is 2.
        client = FakeSupabase()
        code, output = self.run_main(
            client, measure_side_effect=RuntimeError("injected unclassified measurement failure")
        )
        self.assertEqual(code, 1, output)
        self.assertIn("injected unclassified measurement failure", output)

    def test_invalid_schema_output_contains_explicit_reason(self):
        client = FakeSupabase()
        code, output = self.run_main(client, schema_ok=False)
        self.assertEqual(code, 0, output)
        self.assertIn('"failure_reason": "invalid_hypothesis"', output)
        self.assertIn('"reason": "injected"', output)

    def test_malformed_window_currently_exits_one_not_structural_two(self):
        # Window parsing currently maps malformed windows to exit 1; contract requires 2.
        out = io.StringIO()
        with mock.patch.object(sys, "argv", [
            "lab_engine.py", "--hypothesis", "TEST-FAULT", "--window", "bad-window"
        ]), mock.patch.dict(os.environ, {
            "SUPABASE_URL": "https://fake.invalid", "SUPABASE_KEY": "not-a-secret"
        }), contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as raised:
                engine.main()
        self.assertEqual(raised.exception.code, 1, out.getvalue())
        self.assertIn("window_invalido", out.getvalue())

    def test_missing_hypothesis_currently_exits_one_without_manifest_semantics(self):
        # The current engine has no frozen-manifest gate. This captures existing
        # FileNotFoundError behavior, not the required manifest contract.
        client = FakeSupabase()
        out = io.StringIO()
        patches = [
            mock.patch.object(engine, "create_client", return_value=client),
            mock.patch.object(engine, "load_hypothesis", side_effect=FileNotFoundError("missing YAML")),
            mock.patch.object(sys, "argv", ["lab_engine.py", "--hypothesis", "MISSING"]),
            mock.patch.dict(os.environ, {
                "SUPABASE_URL": "https://fake.invalid", "SUPABASE_KEY": "not-a-secret"
            }),
        ]
        with contextlib.ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            with contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as raised:
                    engine.main()
        self.assertEqual(raised.exception.code, 1, out.getvalue())
        self.assertIn("missing YAML", out.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
