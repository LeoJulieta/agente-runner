#!/usr/bin/env python3
"""
labs/lab_engine.py
Motor de hipótesis del laboratorio P/L/D/E.

Uso: python labs/lab_engine.py --hypothesis <id> [--window "lt:<ISO>|gte:<ISO>"] [--cutoff-rows N]

Flujo (PR C, orden constitucional):
1. Cargar contrato y catálogo
2. Schema Gate / Derive Gate / Contract Gate / Class Gate
3. MEDIR (con ventana opcional). Si la muestra es inválida => INVALID, CERO inserts
4. Obtener baseline existente. Si no existe y hay ventana => INVALID, CERO inserts
5. Si no existe y no hay ventana: calcular y persistir baseline (primera corrida válida)
6. Comparar métrica vs baseline congelado
7. Insertar fila de evidencia en lab_results

Regla INVIOLABLE 5: el baseline se congela en la primera corrida válida y nunca
se recalcula. Dataset nuevo => gen+1 con baseline propio.

Test constitucional: ninguna ejecución metodológicamente inválida llega al INSERT
de lab_results, y ninguna ejecución con ventana crea o modifica el baseline.
"""
import os
import sys
import json
import hashlib
import argparse
import yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta
from supabase import create_client

MAX_ROWS = 200

TZ_USHUAIA = timezone(timedelta(hours=-3))


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _canon_ts(value):
    """Canon UTC: mismo instante => mismo string (microsegundos, sufijo Z)."""
    ts = _parse_ts(value)
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_window(window_arg):
    """Devuelve (op, iso_canonico) o None. op in {'lt','gte'}."""
    if not window_arg:
        return None
    op, _, value = window_arg.partition(":")
    if op not in ("lt", "gte") or not value:
        raise ValueError(f"window_invalido: {window_arg}")
    normalized = _canon_ts(value)
    if normalized is None:
        raise ValueError(f"window_iso_invalido: {value}")
    return op, normalized


def _derive_value(row, spec):
    if not spec:
        return None
    ts = _parse_ts(row.get(spec.get("source")))
    if ts is None:
        return None
    subtract_col = spec.get("subtract_hours_from_column")
    if subtract_col:
        hs = row.get(subtract_col)
        if hs is None:
            return None
        ts = ts - timedelta(hours=float(hs))
    tz_offset = spec.get("tz_offset_hours")
    if tz_offset is not None:
        ts = ts.astimezone(timezone(timedelta(hours=tz_offset)))
    extract = spec.get("extract", "hour")
    if extract == "hour":
        return ts.hour
    elif extract == "weekday":
        return ts.weekday()
    return None


def _method_fingerprint(contract: dict, baseline_value) -> str:
    """Hash de los parámetros metodológicos que definen el experimento lógico.
    Dos corridas con el mismo fingerprint miden el mismo protocolo."""
    canon = {
        "dataset": contract.get("dataset"),
        "vars": contract.get("vars"),
        "derive": contract.get("derive"),
        "metric": contract.get("metric"),
        "comparison": contract.get("comparison"),
        "sample_min": contract.get("sample_min"),
        "baseline_value": baseline_value,
    }
    raw = json.dumps(canon, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_baseline_row(row: dict) -> bool:
    """Identifica el registro que congela el baseline.
    Registros post-PR C: params.record_type == 'baseline' o baseline_frozen True.
    Históricos (gen 0/1 pre-PR C): params.baseline es escalar (el valor congelado).
    Las filas de evidencia tienen params.baseline como dict (bloque del contrato),
    por eso el chequeo de escalar las excluye."""
    p = row.get("params") or {}
    if p.get("record_type") == "baseline" or p.get("baseline_frozen") is True:
        return True
    b = p.get("baseline")
    return b is not None and not isinstance(b, dict)


def _disjoint(w1, w2) -> bool:
    """Dos ventanas observadas son disjuntas si sus intervalos no se solapan.
    Compara instantes (datetime aware), no strings."""
    if not w1 or not w2:
        return False
    s1, e1 = _parse_ts(w1.get("start")), _parse_ts(w1.get("end"))
    s2, e2 = _parse_ts(w2.get("start")), _parse_ts(w2.get("end"))
    if not all([s1, e1, s2, e2]):
        return False
    return e1 < s2 or e2 < s1


def _load_catalog():
    path = Path("labs/variable_catalog.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Catálogo no encontrado: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validate_schema_gate(contract: dict, catalog: dict, supabase) -> tuple:
    dataset = contract.get("dataset", [])
    if not dataset:
        return False, "contrato_sin_dataset"
    table_name = dataset[0]
    vars_dict = contract.get("vars", {})
    independent = vars_dict.get("independent", [])
    dependent = vars_dict.get("dependent", [])
    try:
        response = supabase.rpc("get_table_columns", {"table_name": table_name}).execute()
        if not response.data:
            cols_response = supabase.table(table_name).select("*").limit(1).execute()
            if not cols_response.data:
                return False, f"tabla_{table_name}_vacia_o_inexistente"
            db_columns = set(cols_response.data[0].keys())
        else:
            db_columns = {row["column_name"] for row in response.data}
    except Exception:
        try:
            cols_response = supabase.table(table_name).select("*").limit(1).execute()
            if not cols_response.data:
                return False, f"tabla_{table_name}_vacia_o_inexistente"
            db_columns = set(cols_response.data[0].keys())
        except Exception:
            return False, f"no_se_puede_leer_schema_de_{table_name}"
    if dependent:
        dep_col = dependent[0]
        if dep_col not in db_columns:
            return False, f"dependiente_{dep_col}_no_existe"
    derive = contract.get("derive", {}) or {}
    catalog_vars = catalog.get("variables", {})
    for indep in independent:
        is_derived = indep in catalog_vars and catalog_vars[indep].get("type") == "derived"
        if is_derived:
            if indep not in derive:
                continue
            source = derive[indep].get("source")
            if source and source not in db_columns:
                return False, f"fuente_{source}_de_{indep}_no_existe"
            subtract_col = derive[indep].get("subtract_hours_from_column")
            if subtract_col and subtract_col not in db_columns:
                return False, f"columna_resta_{subtract_col}_no_existe"
        else:
            if indep not in db_columns:
                return False, f"independiente_{indep}_no_existe"
    return True, ""


def _validate_derive_gate(contract: dict, catalog: dict) -> tuple:
    derive = contract.get("derive", {}) or {}
    catalog_vars = catalog.get("variables", {})
    derive_allowlist = catalog.get("derive_allowlist", [])
    independent_vars = contract.get("vars", {}).get("independent", [])
    for indep_var in independent_vars:
        if indep_var in catalog_vars and catalog_vars[indep_var].get("type") == "derived":
            if indep_var not in derive:
                return False, f"variable_{indep_var}_es_derived_pero_contrato_no_tiene_derive"
    if not derive:
        return True, ""
    for var_name, spec in derive.items():
        if var_name not in catalog_vars:
            return False, f"derivada_{var_name}_no_en_catalogo"
        if catalog_vars[var_name].get("type") != "derived":
            return False, f"{var_name}_no_es_derivada_segun_catalogo"
        extract = spec.get("extract", "hour")
        if extract not in derive_allowlist:
            return False, f"transformacion_{extract}_no_permitida"
        info = catalog_vars[var_name]
        authorized_spec = {
            "source": info.get("source"),
            "extract": info.get("extract", "hour"),
        }
        if "tz_offset_hours" in info:
            authorized_spec["tz_offset_hours"] = info["tz_offset_hours"]
        if "optional_subtract_column" in info:
            authorized_spec["subtract_hours_from_column"] = info["optional_subtract_column"]
        spec_keys = set(spec.keys())
        authorized_keys = set(authorized_spec.keys())
        unauthorized = spec_keys - authorized_keys
        if unauthorized:
            return False, f"parametros_no_autorizados_en_derive_{var_name}: {','.join(unauthorized)}"
        missing = authorized_keys - spec_keys
        if missing:
            return False, f"parametros_faltantes_en_derive_{var_name}: {','.join(missing)}"
        for param, expected in authorized_spec.items():
            if spec.get(param) != expected:
                return False, f"parametro_{param}_en_{var_name}_tiene_valor_{spec.get(param)}_pero_catalogo_autoriza_{expected}"
    return True, ""


def _validate_contract_gate(contract: dict, catalog: dict) -> tuple:
    catalog_vars = catalog.get("variables", {})
    population_allowlist = catalog.get("population_allowlist", {})
    vars_dict = contract.get("vars", {})
    independent = vars_dict.get("independent", [])
    dependent = vars_dict.get("dependent", [])
    population = contract.get("population_type")
    if not independent or not dependent:
        return False, "contrato_sin_vars"
    dep_col = dependent[0]
    if dep_col not in catalog_vars:
        return False, f"dependiente_{dep_col}_no_en_catalogo"
    if catalog_vars[dep_col].get("role") != "outcome":
        return False, f"dependiente_{dep_col}_no_es_outcome"
    for indep in independent:
        if indep not in catalog_vars:
            return False, f"independiente_{indep}_no_en_catalogo"
        info = catalog_vars[indep]
        if info.get("role") == "outcome":
            return False, f"{indep}_es_outcome_no_puede_ser_independiente"
        if not info.get("independent", True):
            return False, f"{indep}_no_autorizada_como_independiente"
        if population and population in population_allowlist:
            if indep not in population_allowlist[population]:
                return False, f"{indep}_no_autorizada_para_{population}"
    declared_roles = contract.get("var_roles")
    if declared_roles is None:
        return False, "contrato_sin_var_roles_obligatorio"
    missing_roles = (set(independent) | set(dependent)) - set(declared_roles.keys())
    if missing_roles:
        return False, f"var_roles_faltantes_para_{','.join(missing_roles)}"
    for var_name, declared_role in declared_roles.items():
        if var_name not in catalog_vars:
            return False, f"var_roles_{var_name}_no_en_catalogo"
        catalog_role = catalog_vars[var_name].get("role")
        if declared_role != catalog_role:
            return False, f"var_roles_{var_name}_declarado_{declared_role}_distinto_al_catalogo_{catalog_role}"
    if set(independent) & set(dependent):
        return False, "independiente_y_dependiente_superpuestas"
    return True, ""


def load_hypothesis(hypothesis_id: str) -> dict:
    path = Path("labs/hypotheses") / f"{hypothesis_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Hipótesis no encontrada: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def check_class_permissions(contract: dict) -> None:
    clase = contract.get("class", "A")
    if clase == "C":
        raise PermissionError("Clase C requiere aprobación humana. El motor no ejecuta.")
    elif clase == "B":
        if not contract.get("authorized", False):
            raise PermissionError("Clase B requiere authorized: true en el contrato.")


def _baseline_scalar(baseline):
    if isinstance(baseline, dict):
        return baseline.get("value", 0)
    return baseline if isinstance(baseline, (int, float)) else 0


def get_existing_baseline(lab_id: str, supabase):
    """Lee el baseline congelado sin persistir nada. Devuelve (valor, encontrado)."""
    response = (
        supabase.table("lab_results")
        .select("params")
        .eq("lab_id", lab_id)
        .eq("status", "PROMETE")
        .order("id", desc=False)
        .execute()
    )
    for row in response.data or []:
        if _is_baseline_row(row):
            return _baseline_scalar((row.get("params") or {}).get("baseline", {})), True
    return None, False


def _compute_baseline_value(contract: dict, supabase):
    """Calcula el baseline SIN persistirlo (Regla 5: se congela una sola vez)."""
    baseline_config = contract.get("baseline", {})
    baseline_type = baseline_config.get("type", "historical_median")
    if baseline_type == "historical_median":
        dataset = contract.get("dataset", [])
        if not dataset:
            raise ValueError("Contrato sin dataset para calcular baseline")
        dependent_var = contract.get("vars", {}).get("dependent", [])
        if not dependent_var:
            raise ValueError("Contrato sin vars.dependent")
        resp = (
            supabase.table(dataset[0])
            .select(dependent_var[0])
            .not_.is_(dependent_var[0], None)
            .order("created_at", desc=True)
            .limit(100)
            .execute()
        )
        values = [r.get(dependent_var[0]) for r in (resp.data or [])
                  if r.get(dependent_var[0]) is not None]
        if not values:
            return 0, baseline_type
        values.sort()
        return values[len(values) // 2], baseline_type
    return baseline_config.get("value", 0), baseline_type


def persist_baseline(contract: dict, supabase, baseline_value, baseline_type) -> None:
    """Persiste el baseline congelado. Solo se llama tras una medición válida."""
    supabase.table("lab_results").insert({
        "lab_id": contract["id"],
        "gen": contract.get("gen", 0),
        "params": {
            "baseline": baseline_value,
            "baseline_type": baseline_type,
            "baseline_frozen": True,
            "record_type": "baseline",
        },
        "metrics": {},
        "status": "PROMETE",
        "evidence_count": 0,
        "reproducible": False,
        "last_test": datetime.now(timezone.utc).isoformat(),
    }).execute()


def measure(contract: dict, supabase, window=None, cutoff_rows=None) -> dict:
    clase = contract.get("class", "A")
    if clase != "A":
        raise NotImplementedError("Solo clase A implementada en Fase 1")
    dataset = contract.get("dataset", [])
    if not dataset:
        raise ValueError("Contrato sin dataset")
    independent_var = contract.get("vars", {}).get("independent", [])
    dependent_var = contract.get("vars", {}).get("dependent", [])
    if not independent_var or not dependent_var:
        raise ValueError("Contrato sin vars.independent o vars.dependent")
    x_name = independent_var[0]
    y_name = dependent_var[0]
    derive = contract.get("derive", {}) or {}
    x_spec = derive.get(x_name)

    cols = {y_name}
    if x_spec:
        cols.add(x_spec.get("source"))
        if x_spec.get("subtract_hours_from_column"):
            cols.add(x_spec.get("subtract_hours_from_column"))
    else:
        cols.add(x_name)
    select_cols = ",".join(sorted(c for c in cols if c))
    order_col = (x_spec.get("source") if x_spec else "created_at") or "created_at"

    query = supabase.table(dataset[0]).select(select_cols).not_.is_(y_name, None)
    if x_spec:
        query = query.not_.is_(x_spec.get("source"), None)
        if x_spec.get("subtract_hours_from_column"):
            query = query.not_.is_(x_spec.get("subtract_hours_from_column"), None)
    else:
        query = query.not_.is_(x_name, None)
    if window is not None:
        op, iso = window
        if op == "lt":
            query = query.lt("created_at", iso)
        else:
            query = query.gte("created_at", iso)

    response = query.order(order_col, desc=True).limit(MAX_ROWS + 1).execute()
    rows = response.data or []

    def _window_meta(rows_key, rows_val, used):
        meta = {
            "label": f"{window[0]}:{window[1]}",
            rows_key: rows_val,
            "rows_used": used,
        }
        if cutoff_rows is not None:
            meta["dataset_rows_at_cutoff"] = cutoff_rows
        return meta

    if len(rows) > MAX_ROWS:
        result = {
            "correlation": None,
            "sample_size": None,
            "sample_min": int(contract.get("sample_min", 0) or 0),
            "sample_ok": False,
            "reason": "ventana_excede_max_rows",
        }
        if window is not None:
            result["window"] = _window_meta("universe_rows_at_least", MAX_ROWS + 1, 0)
        return result

    x_values, y_values, used_ts = [], [], []
    for r in rows:
        y = r.get(y_name)
        if y is None:
            continue
        x = _derive_value(r, x_spec) if x_spec else r.get(x_name)
        if x is None:
            continue
        x_values.append(float(x))
        y_values.append(float(y))
        used_ts.append(_canon_ts(r.get("created_at")) or r.get("created_at"))

    sample_min = int(contract.get("sample_min", 0) or 0)
    n = len(x_values)

    if n < sample_min:
        result = {
            "correlation": None,
            "sample_size": n,
            "sample_min": sample_min,
            "sample_ok": False,
            "reason": f"muestra insuficiente: {n} < {sample_min}",
        }
        if window is not None:
            meta = _window_meta("universe_rows", len(rows), n)
            meta["start"] = min(used_ts) if used_ts else None
            meta["end"] = max(used_ts) if used_ts else None
            result["window"] = meta
        return result

    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n
    numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
    denom_x = sum((v - x_mean) ** 2 for v in x_values) ** 0.5
    denom_y = sum((v - y_mean) ** 2 for v in y_values) ** 0.5
    correlation = 0.0 if (denom_x == 0 or denom_y == 0) else numerator / (denom_x * denom_y)

    result = {
        "correlation": round(correlation, 4),
        "sample_size": n,
        "sample_min": sample_min,
        "sample_ok": True,
    }
    if window is not None:
        meta = _window_meta("universe_rows", len(rows), n)
        meta["start"] = min(used_ts) if used_ts else None
        meta["end"] = max(used_ts) if used_ts else None
        result["window"] = meta
    return result


def compare(measured: dict, baseline_value, contract: dict) -> dict:
    comparison_type = contract.get("comparison", {}).get("type", "greater_than")
    metric_name = contract.get("metric", {}).get("primary", "correlation")
    measured_value = measured.get(metric_name)
    if measured_value is None:
        return {
            "measured_value": None,
            "baseline_value": _baseline_scalar(baseline_value),
            "comparison_type": comparison_type,
            "passed": False,
        }
    baseline_value = _baseline_scalar(baseline_value)
    if comparison_type == "greater_than":
        passed = measured_value > baseline_value
    elif comparison_type == "less_than":
        passed = measured_value < baseline_value
    elif comparison_type == "delta_percent":
        passed = measured_value > 0 if baseline_value == 0 else \
            ((measured_value - baseline_value) / baseline_value) * 100 > 10
    else:
        passed = True
    return {
        "measured_value": measured_value,
        "baseline_value": baseline_value,
        "comparison_type": comparison_type,
        "passed": passed,
    }


def main():
    parser = argparse.ArgumentParser(description="Motor de hipótesis P/L/D/E")
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--window", required=False, default=None)
    parser.add_argument("--cutoff-rows", required=False, default=None, type=int)
    args = parser.parse_args()

    try:
        window = _parse_window(args.window)
    except ValueError as e:
        print(json.dumps({"error": str(e), "hypothesis": args.hypothesis, "status": "ERROR"}))
        sys.exit(1)

    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

    try:
        contract = load_hypothesis(args.hypothesis)
        catalog = _load_catalog()

        schema_ok, schema_reason = _validate_schema_gate(contract, catalog, supabase)
        if not schema_ok:
            print(json.dumps({"lab_id": contract["id"], "status": "INVALID",
                              "failure_reason": "invalid_hypothesis",
                              "gate_failed": "schema_gate", "reason": schema_reason}))
            sys.exit(0)

        derive_ok, derive_reason = _validate_derive_gate(contract, catalog)
        if not derive_ok:
            print(json.dumps({"lab_id": contract["id"], "status": "INVALID",
                              "failure_reason": "invalid_hypothesis",
                              "gate_failed": "derive_gate", "reason": derive_reason}))
            sys.exit(0)

        contract_ok, contract_reason = _validate_contract_gate(contract, catalog)
        if not contract_ok:
            print(json.dumps({"lab_id": contract["id"], "status": "INVALID",
                              "failure_reason": "invalid_hypothesis",
                              "gate_failed": "contract_gate", "reason": contract_reason}))
            sys.exit(0)

        check_class_permissions(contract)

        # 3. MEDIR PRIMERO: ninguna persistencia antes de validar la muestra
        measured = measure(contract, supabase, window, args.cutoff_rows)
        if not measured.get("sample_ok", False):
            print(json.dumps({"lab_id": contract["id"], "status": "INVALID",
                              "failure_reason": "medicion_invalida",
                              "reason": measured.get("reason"),
                              "window": measured.get("window")}))
            sys.exit(0)

        # 4. Baseline existente; con ventana, DEBE existir
        baseline_value, found = get_existing_baseline(contract["id"], supabase)
        if not found:
            if window is not None:
                print(json.dumps({"lab_id": contract["id"], "status": "INVALID",
                                  "failure_reason": "baseline_required",
                                  "reason": "corrida_con_ventana_requiere_baseline_existente"}))
                sys.exit(0)
            # 5. Primera corrida válida: calcular y recién ahora persistir
            baseline_value, baseline_type = _compute_baseline_value(contract, supabase)
            persist_baseline(contract, supabase, baseline_value, baseline_type)

        comparison = compare(measured, baseline_value, contract)
        passed = bool(comparison["passed"])
        status = "VERIFICADO" if passed else "PROMETE"

        lab_id = contract["id"]
        fingerprint = _method_fingerprint(contract, baseline_value)

        history_response = (
            supabase.table("lab_results")
            .select("metrics")
            .eq("lab_id", lab_id)
            .order("id", desc=False)
            .execute()
        )
        history = history_response.data or []
        current_window = measured.get("window")
        prior_independent = any(
            (row.get("metrics") or {}).get("passed") is True
            and (row.get("metrics") or {}).get("method_fingerprint") == fingerprint
            and _disjoint((row.get("metrics") or {}).get("window"), current_window)
            for row in history
        )
        reproducible = bool(passed) and prior_independent

        last_response = (
            supabase.table("lab_results")
            .select("evidence_count")
            .eq("lab_id", lab_id)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        last_rows = last_response.data or []
        previous_evidence_count = last_rows[0].get("evidence_count", 0) if last_rows else 0
        new_evidence_count = previous_evidence_count + 1

        metrics = {**measured, **comparison, "method_fingerprint": fingerprint}
        params = dict(contract)
        params["record_type"] = "evidence"

        insert_response = supabase.table("lab_results").insert({
            "lab_id": lab_id,
            "gen": contract.get("gen", 0),
            "params": params,
            "metrics": metrics,
            "status": status,
            "evidence_count": new_evidence_count,
            "reproducible": reproducible,
            "last_test": datetime.now(timezone.utc).isoformat(),
        }).execute()

        print(json.dumps({"lab_id": lab_id, "status": status,
                          "evidence_count": new_evidence_count,
                          "reproducible": reproducible, "metrics": metrics,
                          "insert_ok": bool(insert_response.data)}))

    except Exception as e:
        print(json.dumps({"error": str(e), "hypothesis": args.hypothesis, "status": "ERROR"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
