import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest


ENGINE_PATH = Path("labs/lab_engine.py")


def load_engine(monkeypatch, rpc_raises=False):
    # The engine's external integrations are stubbed here; the RPC's PostgreSQL
    # transaction behavior is covered separately by test_pr_d_atomic_rpc.py.
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda _stream: {}
    supabase_stub = types.ModuleType("supabase")

    class Response:
        def __init__(self, data):
            self.data = data

    class Query:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def execute(self):
            return Response([])

    class FakeClient:
        def __init__(self):
            self.rpc_args = None

        def table(self, *_args, **_kwargs):
            return Query()

        def rpc(self, name, args):
            self.rpc_args = (name, args)
            if rpc_raises:
                raise RuntimeError("RPC unavailable")
            return types.SimpleNamespace(
                execute=lambda: Response({
                    "id": 123,
                    "evidence_count": 1,
                    "baseline_created": True,
                    "idempotent_replay": False,
                })
            )

    client = FakeClient()
    supabase_stub.create_client = lambda *_args, **_kwargs: client
    monkeypatch.setitem(sys.modules, "yaml", yaml_stub)
    monkeypatch.setitem(sys.modules, "supabase", supabase_stub)

    spec = importlib.util.spec_from_file_location("lab_engine_under_test", ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, client


def prepare_engine(monkeypatch, module, gen=1):
    contract = {
        "id": "H990",
        "gen": gen,
        "class": "A",
        "dataset": ["fixture_dataset"],
        "vars": {"independent": ["x"], "dependent": ["y"]},
        "var_roles": {},
        "metric": {"primary": "correlation"},
        "comparison": {"type": "greater_than"},
    }
    monkeypatch.setattr(module, "load_hypothesis", lambda _hypothesis: contract)
    monkeypatch.setattr(module, "_load_catalog", lambda: {})
    monkeypatch.setattr(module, "_validate_schema_gate", lambda *_args: (True, ""))
    monkeypatch.setattr(module, "_validate_derive_gate", lambda *_args: (True, ""))
    monkeypatch.setattr(module, "_validate_contract_gate", lambda *_args: (True, ""))
    monkeypatch.setattr(module, "check_class_permissions", lambda *_args: None)
    monkeypatch.setattr(module, "measure", lambda *_args, **_kwargs: {
        "correlation": 0.8,
        "sample_size": 10,
        "sample_min": 5,
        "sample_ok": True,
    })
    monkeypatch.setattr(module, "get_existing_baseline", lambda *_args: (None, False))
    monkeypatch.setattr(module, "_compute_baseline_value", lambda *_args: (0.2, "fixture"))


def test_engine_sends_generation_to_atomic_rpc(monkeypatch, capsys):
    module, client = load_engine(monkeypatch)
    prepare_engine(monkeypatch, module, gen=1)
    monkeypatch.setenv("SUPABASE_URL", "https://fixture.invalid")
    monkeypatch.setenv("SUPABASE_KEY", "fixture-key")
    monkeypatch.setattr(sys, "argv", ["lab_engine.py", "--hypothesis", "H990"])

    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 0
    name, payload = client.rpc_args
    assert name == "rpc_insert_baseline_and_evidence"
    assert payload["p_gen"] == 1
    assert payload["p_lab_id"] == "H990"
    assert json.loads(capsys.readouterr().out)["insert_ok"] is True


def test_engine_exits_structural_code_2_when_rpc_fails(monkeypatch, capsys):
    module, _client = load_engine(monkeypatch, rpc_raises=True)
    prepare_engine(monkeypatch, module, gen=1)
    monkeypatch.setenv("SUPABASE_URL", "https://fixture.invalid")
    monkeypatch.setenv("SUPABASE_KEY", "fixture-key")
    monkeypatch.setattr(sys, "argv", ["lab_engine.py", "--hypothesis", "H990"])

    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["failure_reason"] == "atomic_persistence_unavailable"
