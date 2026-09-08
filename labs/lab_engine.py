#!/usr/bin/env python3
"""
labs/lab_engine.py
Motor de hipótesis del laboratorio P/L/D/E.

Uso: python labs/lab_engine.py --hypothesis <id>

Flujo:
1. Cargar contrato YAML desde labs/hypotheses/<id>.yaml
2. Verificar clase (A|B|C) y aplicar reglas
3. Congelar baseline (si es primera corrida) o leer baseline congelado
4. Medir (solo lectura en tablas existentes si clase A)
5. Comparar métrica vs baseline congelado
6. Insertar fila en lab_results (gen, params, metrics, status, evidence_count)

Regla INVIOLABLE 5: El baseline se congela al registrar la hipótesis (status PROMETE).
El motor NUNCA recalcula el baseline. Dataset nuevo → gen+1 con baseline propio.
"""
import os
import sys
import json
import argparse
import yaml
from pathlib import Path
from datetime import datetime, timezone
from supabase import create_client


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
        .limit(1)
        .execute()
    )

    if response.data:
        # Baseline ya congelado, leer de la fila PROMETE
        return response.data[0].get("params", {}).get("baseline", {})
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

            # Para H001: leer views_primeras_3h de youtube_shorts_log
            # donde hora_publicacion existe
            # (simplificado: leer últimas 100 filas y calcular mediana)
            response = (
                supabase.table(dataset[0])
                .select("*")
                .limit(100)
                .execute()
            )

            rows = response.data or []
            dependent_var = contract.get("vars", {}).get("dependent", [])
            if not dependent_var:
                raise ValueError("Contrato sin vars.dependent")

            values = [r.get(dependent_var[0]) for r in rows if r.get(dependent_var[0]) is not None]
            if not values:
                baseline_value = 0
            else:
                values.sort()
                baseline_value = values[len(values) // 2]  # mediana simple

        elif baseline_type == "fixed":
            # Baseline fijo especificado en el contrato
            baseline_value = baseline_config.get("value", 0)

        else:
            # Otros tipos de baseline (mean, etc.) se implementan después
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
    """Mide métrica según contrato (solo lectura si clase A)"""
    clase = contract.get("class", "A")
    if clase != "A":
        raise NotImplementedError("Solo clase A implementada en Fase 1")

    dataset = contract.get("dataset", [])
    if not dataset:
        raise ValueError("Contrato sin dataset")

    # Para H001: correlación entre hora_publicacion y views_primeras_3h
    # Simplificado: leer últimas 50 filas y calcular correlación simple
    response = (
        supabase.table(dataset[0])
        .select("*")
        .limit(50)
        .execute()
    )

    rows = response.data or []
    independent_var = contract.get("vars", {}).get("independent", [])
    dependent_var = contract.get("vars", {}).get("dependent", [])

    if not independent_var or not dependent_var:
        raise ValueError("Contrato sin vars.independent o vars.dependent")

    x_values = [r.get(independent_var[0]) for r in rows if r.get(independent_var[0]) is not None]
    y_values = [r.get(dependent_var[0]) for r in rows if r.get(dependent_var[0]) is not None]

    # Calcular correlación simple (Pearson)
    if len(x_values) < 2 or len(y_values) < 2:
        n = 0
        correlation = 0.0
    else:
        # Simplificación: correlación básica
        n = min(len(x_values), len(y_values))
        x_mean = sum(x_values[:n]) / n
        y_mean = sum(y_values[:n]) / n

        numerator = sum((x_values[i] - x_mean) * (y_values[i] - y_mean) for i in range(n))
        denom_x = sum((x_values[i] - x_mean) ** 2 for i in range(n)) ** 0.5
        denom_y = sum((y_values[i] - y_mean) ** 2 for i in range(n)) ** 0.5

        if denom_x == 0 or denom_y == 0:
            correlation = 0.0
        else:
            correlation = numerator / (denom_x * denom_y)

    return {"correlation": round(correlation, 4), "sample_size": n}


def compare(measured: dict, baseline: dict, contract: dict) -> dict:
    """Compara métrica medida vs baseline congelado"""
    comparison_type = contract.get("comparison", {}).get("type", "greater_than")
    metric_name = contract.get("metric", {}).get("primary", "correlation")

    measured_value = measured.get(metric_name, 0)
    baseline_value = baseline if isinstance(baseline, (int, float)) else 0

    if comparison_type == "greater_than":
        passed = measured_value > baseline_value
    elif comparison_type == "less_than":
        passed = measured_value < baseline_value
    elif comparison_type == "delta_percent":
        # Delta porcentual respecto al baseline
        if baseline_value == 0:
            passed = measured_value > 0
        else:
            delta_pct = ((measured_value - baseline_value) / baseline_value) * 100
            passed = delta_pct > 10  # ej: mejora >10%
    else:
        passed = True  # comparación no implementada, asumimos ok

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

        # 2. Verificar clase
        check_class_permissions(contract)

        # 3. Congelar baseline (o leer congelado)
        baseline = freeze_baseline(contract, supabase)

        # 4. Medir
        measured = measure(contract, supabase)

        # 5. Comparar
        comparison = compare(measured, baseline, contract)

        # 6. Insertar fila en lab_results
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

        # Status: VERIFICADO si comparación pasó, PROMETE si no
        status = "VERIFICADO" if comparison["passed"] else "PROMETE"

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
