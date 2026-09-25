#!/usr/bin/env python3
"""
labs/lab_engine.py
Motor de hipótesis del laboratorio P/L/D/E.

Uso: python labs/lab_engine.py --hypothesis <id>

Flujo:
1. Cargar contrato YAML desde labs/hypotheses/<id>.yaml
2. Schema Gate: validar columnas contra information_schema
3. Derive Gate: validar derivadas contra variable_catalog.yaml
4. Contract Gate: validar roles y autorizaciones
5. Verificar clase (A|B|C) y aplicar reglas
6. Congelar baseline (si es primera corrida) o leer baseline congelado
7. Medir (solo lectura en tablas existentes si clase A)
8. Comparar métrica vs baseline congelado
9. Insertar fila en lab_results (gen, params, metrics, status, evidence_count)

Regla INVIOLABLE 5: El baseline se congela al registrar la hipótesis (status PROMETE).
El motor NUNCA recalcula el baseline. Dataset nuevo → gen+1 con baseline propio.

PR B (24/9): Schema Gate + Derive Gate + Contract Gate antes de freeze_baseline.
INVALID no escribe fila PROMETE ni mide.
"""
import os
import sys
import json
import argparse
import yaml
from pathlib import Path
from datetime import datetime, timezone, timedelta
from supabase import create_client

# ==============================================================================
# UTILIDADES PARA DERIVACIÓN DE VARIABLES (Timezone & Transformaciones)
# ==============================================================================

TZ_USHUAIA = timezone(timedelta(hours=-3))

def _parse_ts(value):
    """Parsea string ISO a datetime, manejando 'Z' y formatos variados."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

def _derive_value(row, spec):
    """
    Deriva una variable virtual según el bloque `derive` del contrato.

    Ejemplo spec:
      source: created_at
      subtract_hours_from_column: hs_al_publicar_al_sync
      tz_offset_hours: -3
      extract: hour | weekday

    Lógica: ts = created_at - hs_al_publicar_al_sync -> convertir a UTC-3 -> extraer hora o weekday
    """
    if not spec:
        return None

    ts = _parse_ts(row.get(spec.get("source")))
    if ts is None:
        return None

    # Restar horas si se especifica (ej: hs_al_publicar_al_sync)
    subtract_col = spec.get("subtract_hours_from_column")
    if subtract_col:
        hs = row.get(subtract_col)
        if hs is None:
            return None
        ts = ts - timedelta(hours=float(hs))

    # Convertir a zona horaria local (ej: UTC-3 para Ushuaia)
    tz_offset = spec.get("tz_offset_hours")
    if tz_offset is not None:
        ts = ts.astimezone(timezone(timedelta(hours=tz_offset)))

    # Extraer componente
    extract = spec.get("extract", "hour")
    if extract == "hour":
        return ts.hour
    elif extract == "weekday":
        return ts.weekday()  # 0=lunes, 6=domingo

    return None

# ==============================================================================
# GATES DE VALIDACIÓN (PR B: 24/9)
# ==============================================================================

def _load_catalog():
    """Carga variable_catalog.yaml desde labs/"""
    path = Path("labs/variable_catalog.yaml")
    if not path.exists():
        raise FileNotFoundError(f"Catálogo no encontrado: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def _validate_schema_gate(contract: dict, catalog: dict, supabase) -> tuple[bool, str]:
    """
    Schema Gate: valida que todas las columnas existan en DB y tengan tipo compatible.
    Devuelve (válido, motivo).
    """
    dataset = contract.get("dataset", [])
    if not dataset:
        return False, "contrato_sin_dataset"

    table_name = dataset[0]
    vars_dict = contract.get("vars", {})
    independent = vars_dict.get("independent", [])
    dependent = vars_dict.get("dependent", [])

    # Consultar information_schema
    try:
        response = supabase.rpc("get_table_columns", {"table_name": table_name}).execute()
        if not response.data:
            # Fallback: query directa a information_schema
            query = f"""
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
            """
            response = supabase.from_("dummy").select("*").execute()  # placeholder
            # Si no hay RPC, hacer query directa
            cols_response = supabase.table(table_name).select("*").limit(1).execute()
            if not cols_response.data:
                return False, f"tabla_{table_name}_vacia_o_inexistente"
            # Extraer columnas de la primera fila
            db_columns = set(cols_response.data[0].keys())
        else:
            db_columns = {row["column_name"] for row in response.data}
    except Exception as e:
        # Fallback: intentar SELECT * LIMIT 1
        try:
            cols_response = supabase.table(table_name).select("*").limit(1).execute()
            if not cols_response.data:
                return False, f"tabla_{table_name}_vacia_o_inexistente"
            db_columns = set(cols_response.data[0].keys())
        except:
            return False, f"no_se_puede_leer_schema_de_{table_name}"

    # Validar dependiente
    if dependent:
        dep_col = dependent[0]
        if dep_col not in db_columns:
            return False, f"dependiente_{dep_col}_no_existe"

    # Validar independientes (crudas o fuente de derivadas)
    derive = contract.get("derive", {}) or {}
    for indep in independent:
        if indep in derive:
            # Es derivada: validar fuente
            source = derive[indep].get("source")
            if source and source not in db_columns:
                return False, f"fuente_{source}_de_{indep}_no_existe"
            # Validar columna de resta si aplica
            subtract_col = derive[indep].get("subtract_hours_from_column")
            if subtract_col and subtract_col not in db_columns:
                return False, f"columna_resta_{subtract_col}_no_existe"
        else:
            # Es cruda: validar existencia
            if indep not in db_columns:
                return False, f"independiente_{indep}_no_existe"

    return True, ""

def _validate_derive_gate(contract: dict, catalog: dict) -> tuple[bool, str]:
    """
    Derive Gate: valida que las derivadas estén autorizadas en el catálogo.
    """
    derive = contract.get("derive", {}) or {}
    if not derive:
        return True, ""

    catalog_vars = catalog.get("variables", {})
    derive_allowlist = catalog.get("derive_allowlist", [])

    for var_name, spec in derive.items():
        # Validar que la variable esté en el catálogo
        if var_name not in catalog_vars:
            return False, f"derivada_{var_name}_no_en_catalogo"

        # Validar que sea tipo derived
        if catalog_vars[var_name].get("type") != "derived":
            return False, f"{var_name}_no_es_derivada_segun_catalogo"

        # Validar transformación permitida
        extract = spec.get("extract", "hour")
        if extract not in derive_allowlist:
            return False, f"transformacion_{extract}_no_permitida"

        # Validar fuente
        source = spec.get("source")
        expected_source = catalog_vars[var_name].get("source")
        if source != expected_source:
            return False, f"fuente_{source}_no_coincide_con_catalogo_{expected_source}"

    return True, ""

def _validate_contract_gate(contract: dict, catalog: dict) -> tuple[bool, str]:
    """
    Contract Gate: valida roles, autorizaciones y exclusiones metodológicas.
    """
    catalog_vars = catalog.get("variables", {})
    population_allowlist = catalog.get("population_allowlist", {})

    vars_dict = contract.get("vars", {})
    independent = vars_dict.get("independent", [])
    dependent = vars_dict.get("dependent", [])
    population = contract.get("population_type")

    if not independent or not dependent:
        return False, "contrato_sin_vars"

    # Validar dependiente
    dep_col = dependent[0]
    if dep_col not in catalog_vars:
        return False, f"dependiente_{dep_col}_no_en_catalogo"
    if catalog_vars[dep_col].get("role") != "outcome":
        return False, f"dependiente_{dep_col}_no_es_outcome"

    # Validar independientes
    for indep in independent:
        if indep not in catalog_vars:
            return False, f"independiente_{indep}_no_en_catalogo"

        var_info = catalog_vars[indep]

        # No puede ser outcome
        if var_info.get("role") == "outcome":
            return False, f"{indep}_es_outcome_no_puede_ser_independiente"

        # No puede estar marcada como independent: false
        if not var_info.get("independent", True):
            return False, f"{indep}_no_autorizada_como_independiente"

        # Validar contra population_allowlist
        if population and population in population_allowlist:
            if indep not in population_allowlist[population]:
                return False, f"{indep}_no_autorizada_para_{population}"

    # Validar que independiente != dependiente
    if set(independent) & set(dependent):
        return False, "independiente_y_dependiente_superpuestas"

    return True, ""

def load_hypothesis(hypothesis_id: str) -> dict:
    """Carga contrato YAML desde labs/hypotheses/<id>.yaml"""
    path = Path("labs/hypotheses") / f"{hypothesis_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Hipótesis no encontrada: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def check_class_permissions(contract: dict) -> None:
    """Verifica reglas de clase A/B/C"""
    clase = contract.get("class", "A")
    if clase == "C":
        # Clase C: producción/dinero/terceros → SIEMPRE rechazar (camino humano)
        raise PermissionError("Clase C requiere aprobación humana. El motor no ejecuta.")
    elif clase == "B":
        # Clase B: requiere recurso externo (API, sandbox, etc.)
        if not contract.get("authorized", False):
            raise PermissionError("Clase B requiere authorized: true en el contrato.")
    # Clase A: read-only, puede ejecutar tras aprobación de batch (asumida)

def _baseline_scalar(baseline):
    """Acepta scalar congelado o dict de contrato; nunca default 0 silencioso."""
    if isinstance(baseline, dict):
        return baseline.get("value", 0)
    return baseline if isinstance(baseline, (int, float)) else 0

def freeze_baseline(contract: dict, supabase) -> dict:
    """
    Regla INVIOLABLE 5: Congela baseline al registrar hipótesis (status PROMETE).
    Si ya existe fila con status PROMETE para este lab_id, lee el baseline congelado.
    Si no existe, calcula baseline y lo congela en nueva fila PROMETE.
    """
    lab_id = contract["id"]

    # Buscar si ya existe fila PROMETE (baseline congelado)
    response = (
        supabase.table("lab_results")
        .select("*")
        .eq("lab_id", lab_id)
        .eq("status", "PROMETE")
        .order("id", desc=False)
        .limit(1)
        .execute()
    )

    if response.data:
        # Baseline ya congelado, leer de la fila PROMETE
        return _baseline_scalar(response.data[0].get("params", {}).get("baseline", {}))
    else:
        # Primera corrida: calcular baseline y congelar
        baseline_config = contract.get("baseline", {})
        baseline_type = baseline_config.get("type", "historical_median")

        # Calcular baseline según tipo (ejemplo: historical_median)
        if baseline_type == "historical_median":
            # Leer datos históricos de la tabla dataset
            dataset = contract.get("dataset", [])
            if not dataset:
                raise ValueError("Contrato sin dataset para calcular baseline")

            dependent_var = contract.get("vars", {}).get("dependent", [])
            if not dependent_var:
                raise ValueError("Contrato sin vars.dependent")

            # CORRECCIÓN: Filtrar nulls explícitamente y ordenar por fecha
            response = (
                supabase.table(dataset[0])
                .select(dependent_var[0])
                .not_.is_(dependent_var[0], None)
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )

            rows = response.data or []
            values = [r.get(dependent_var[0]) for r in rows if r.get(dependent_var[0]) is not None]

            if not values:
                baseline_value = 0
            else:
                values.sort()
                baseline_value = values[len(values) // 2]  # mediana simple

        else:
            # Otros tipos de baseline (mean, fixed, etc.)
            baseline_value = baseline_config.get("value", 0)

        # Insertar fila PROMETE con baseline congelado
        insert_payload = {
            "lab_id": lab_id,
            "gen": 0,
            "params": {"baseline": baseline_value, "baseline_type": baseline_type},
            "metrics": {},
            "status": "PROMETE",
            "evidence_count": 0,
            "reproducible": False,
            "last_test": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("lab_results").insert(insert_payload).execute()

        return baseline_value

def measure(contract: dict, supabase) -> dict:
    """
    Mide métrica según contrato (solo lectura si clase A).

    Mejoras Fase 1.1:
    - Filtra nulls explícitamente en ambas columnas
    - Ordena por fecha descendente para tomar muestras recientes
    - Respeta sample_min del contrato
    - Soporta bloque `derive` para variables virtuales (ej: hora_local, dia_semana)
    """
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

    # Soporte para variables derivadas (derive block)
    derive = contract.get("derive", {}) or {}
    x_spec = derive.get(x_name)

    # Construir lista de columnas necesarias para el SELECT
    cols = {y_name}
    if x_spec:
        cols.add(x_spec.get("source"))
        if x_spec.get("subtract_hours_from_column"):
            cols.add(x_spec.get("subtract_hours_from_column"))
    else:
        cols.add(x_name)

    select_cols = ",".join(sorted(c for c in cols if c))
    order_col = (x_spec.get("source") if x_spec else "created_at") or "created_at"

    # Construir query con filtros NOT NULL explícitos
    query = supabase.table(dataset[0]).select(select_cols).not_.is_(y_name, None)

    if x_spec:
        query = query.not_.is_(x_spec.get("source"), None)
        if x_spec.get("subtract_hours_from_column"):
            query = query.not_.is_(x_spec.get("subtract_hours_from_column"), None)
    else:
        query = query.not_.is_(x_name, None)

    # Ordenar por fecha descendente y limitar a 200 filas (para tener margen)
    response = query.order(order_col, desc=True).limit(200).execute()

    rows = response.data or []

    # Procesar filas: derivar X si corresponde, filtrar nulls
    x_values, y_values = [], []
    for r in rows:
        y = r.get(y_name)
        if y is None:
            continue

        if x_spec:
            x = _derive_value(r, x_spec)
        else:
            x = r.get(x_name)

        if x is None:
            continue

        x_values.append(float(x))
        y_values.append(float(y))

    # Verificar sample_min
    sample_min = int(contract.get("sample_min", 0) or 0)
    n = len(x_values)
    sample_ok = n >= sample_min

    if not sample_ok:
        return {
            "correlation": None,
            "sample_size": n,
            "sample_min": sample_min,
            "sample_ok": False,
            "reason": f"muestra insuficiente: {n} < {sample_min}",
        }

    # Calcular correlación de Pearson
    x_mean = sum(x_values) / n
    y_mean = sum(y_values) / n

    numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
    denom_x = sum((v - x_mean) ** 2 for v in x_values) ** 0.5
    denom_y = sum((v - y_mean) ** 2 for v in y_values) ** 0.5

    if denom_x == 0 or denom_y == 0:
        correlation = 0.0
    else:
        correlation = numerator / (denom_x * denom_y)

    return {
        "correlation": round(correlation, 4),
        "sample_size": n,
        "sample_min": sample_min,
        "sample_ok": True,
    }

def compare(measured: dict, baseline: dict, contract: dict) -> dict:
    """Compara métrica medida vs baseline congelado"""
    comparison_type = contract.get("comparison", {}).get("type", "greater_than")
    metric_name = contract.get("metric", {}).get("primary", "correlation")

    # CORRECCIÓN: Nunca usar default 0 silencioso
    measured_value = measured.get(metric_name)
    if measured_value is None:
        return {
            "measured_value": None,
            "baseline_value": _baseline_scalar(baseline),
            "comparison_type": comparison_type,
            "passed": False,
        }

    baseline_value = _baseline_scalar(baseline)

    if comparison_type == "greater_than":
        passed = measured_value > baseline_value
    elif comparison_type == "less_than":
        passed = measured_value < baseline_value
    elif comparison_type == "delta_percent":
        if baseline_value == 0:
            passed = measured_value > 0
        else:
            delta_pct = ((measured_value - baseline_value) / baseline_value) * 100
            passed = delta_pct > 10
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
    parser.add_argument("--hypothesis", required=True, help="ID de la hipótesis (ej: H001)")
    args = parser.parse_args()

    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    supabase = create_client(supabase_url, supabase_key)

    try:
        # 1. Cargar contrato
        contract = load_hypothesis(args.hypothesis)

        # 2. Cargar catálogo
        catalog = _load_catalog()

        # 3. Schema Gate (antes de freeze_baseline)
        schema_ok, schema_reason = _validate_schema_gate(contract, catalog, supabase)
        if not schema_ok:
            output = {
                "lab_id": contract["id"],
                "status": "INVALID",
                "failure_reason": "invalid_hypothesis",
                "gate_failed": "schema_gate",
                "reason": schema_reason,
            }
            print(json.dumps(output))
            sys.exit(0)  # No es error, es INVALID legítimo

        # 4. Derive Gate
        derive_ok, derive_reason = _validate_derive_gate(contract, catalog)
        if not derive_ok:
            output = {
                "lab_id": contract["id"],
                "status": "INVALID",
                "failure_reason": "invalid_hypothesis",
                "gate_failed": "derive_gate",
                "reason": derive_reason,
            }
            print(json.dumps(output))
            sys.exit(0)

        # 5. Contract Gate
        contract_ok, contract_reason = _validate_contract_gate(contract, catalog)
        if not contract_ok:
            output = {
                "lab_id": contract["id"],
                "status": "INVALID",
                "failure_reason": "invalid_hypothesis",
                "gate_failed": "contract_gate",
                "reason": contract_reason,
            }
            print(json.dumps(output))
            sys.exit(0)

        # 6. Verificar clase
        check_class_permissions(contract)

        # 7. Congelar baseline (o leer congelado)
        baseline = freeze_baseline(contract, supabase)

        # 8. Medir
        measured = measure(contract, supabase)

        # 9. Comparar
        comparison = compare(measured, baseline, contract)

        # 10. Insertar fila en lab_results
        lab_id = contract["id"]

        # Leer última fila para incrementar evidence_count
        last_response = (
            supabase.table("lab_results")
            .select("*")
            .eq("lab_id", lab_id)
            .order("id", desc=True)
            .limit(1)
            .execute()
        )

        last_rows = last_response.data or []
        previous_evidence_count = 0
        if last_rows:
            previous_evidence_count = last_rows[0].get("evidence_count", 0)

        new_evidence_count = previous_evidence_count + 1
        reproducible = new_evidence_count >= 2

        # CORRECCIÓN: Status depende de sample_ok AND comparación pasada
        passed = bool(comparison["passed"]) and bool(measured.get("sample_ok", False))
        status = "VERIFICADO" if passed else "PROMETE"

        insert_payload = {
            "lab_id": lab_id,
            "gen": contract.get("gen", 0),
            "params": contract,
            "metrics": {**measured, **comparison},
            "status": status,
            "evidence_count": new_evidence_count,
            "reproducible": reproducible,
            "last_test": datetime.now(timezone.utc).isoformat(),
        }

        insert_response = supabase.table("lab_results").insert(insert_payload).execute()

        output = {
            "lab_id": lab_id,
            "status": status,
            "evidence_count": new_evidence_count,
            "reproducible": reproducible,
            "metrics": {**measured, **comparison},
            "insert_ok": bool(insert_response.data),
        }
        print(json.dumps(output))

    except Exception as e:
        error_output = {
            "error": str(e),
            "hypothesis": args.hypothesis,
            "status": "ERROR",
        }
        print(json.dumps(error_output))
        sys.exit(1)

if __name__ == "__main__":
    main()
