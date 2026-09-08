#!/usr/bin/env python3
"""
lab_001_tracer.py - El tubo de ensayo (deliberadamente aburrido)

Fase 0 P/L/D/E:
(a) Mide duración de cálculo trivial + COUNT de youtube_shorts_log (solo lectura)
(b) Compara: lee última fila de lab_results para lab_001 y calcula delta
(c) Registra: inserta fila nueva con gen=0, evidence_count=anterior+1,
    reproducible=(evidence_count>=2), status='VERIFICADO' o 'PROMETE'
"""

import os
import json
import time
from datetime import datetime, timezone
from supabase import create_client, Client

def run(client: Client) -> dict:
    """Ejecuta el experimento lab_001 y retorna resultados."""

    lab_id = "lab_001"
    start_time = time.time()

    # (a) Cálculo trivial + COUNT de youtube_shorts_log (solo lectura)
    try:
        count_response = client.table("youtube_shorts_log").select("id", count="exact").limit(1).execute()
        total_shorts = count_response.count if hasattr(count_response, 'count') else 0

        # Simular cálculo trivial
        dummy_calc = sum(range(1000))

        duration_ms = (time.time() - start_time) * 1000

        metrics = {
            "duration_ms": round(duration_ms, 2),
            "total_shorts": total_shorts,
            "dummy_calc": dummy_calc
        }
        status = "VERIFICADO"

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics = {
            "duration_ms": round(duration_ms, 2),
            "error": str(e)
        }
        status = "PROMETE"

    # (b) Leer última fila de lab_results para lab_001
    try:
        last_response = client.table("lab_results")\
            .select("*")\
            .eq("lab_id", lab_id)\
            .order("creado_en", desc=True)\
            .limit(1)\
            .execute()

        last_row = last_response.data[0] if last_response.data else None

        if last_row:
            prev_evidence_count = last_row.get("evidence_count", 0)
            prev_metrics = last_row.get("metrics", {})

            # Calcular delta de métricas (si hay datos comparables)
            delta = {}
            if "duration_ms" in metrics and "duration_ms" in prev_metrics:
                delta["duration_delta_ms"] = round(
                    metrics["duration_ms"] - prev_metrics["duration_ms"], 2
                )
            if "total_shorts" in metrics and "total_shorts" in prev_metrics:
                delta["shorts_delta"] = metrics["total_shorts"] - prev_metrics.get("total_shorts", 0)
        else:
            prev_evidence_count = 0
            delta = {}

    except Exception as e:
        prev_evidence_count = 0
        delta = {"error_comparing": str(e)}

    # (c) Registrar nueva fila
    new_evidence_count = prev_evidence_count + 1
    reproducible = new_evidence_count >= 2

    new_row = {
        "lab_id": lab_id,
        "gen": 0,
        "params": {"trivial": True},
        "metrics": metrics,
        "status": status,
        "evidence_count": new_evidence_count,
        "reproducible": reproducible,
        "last_test": datetime.now(timezone.utc).isoformat()
    }

    try:
        insert_response = client.table("lab_results").insert(new_row).execute()
        insert_id = insert_response.data[0]["id"] if insert_response.data else None
    except Exception as e:
        insert_id = None
        status = "PROMETE"

    # Resultado final
    result = {
        "lab_id": lab_id,
        "run_id": insert_id,
        "gen": 0,
        "evidence_count": new_evidence_count,
        "reproducible": reproducible,
        "status": status,
        "metrics": metrics,
        "delta": delta,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    return result


if __name__ == "__main__":
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        print(json.dumps({
            "error": "Faltan SUPABASE_URL o SUPABASE_KEY en variables de entorno",
            "status": "PROMETE"
        }))
        exit(1)

    supabase: Client = create_client(supabase_url, supabase_key)
    result = run(supabase)
    print(json.dumps(result, indent=2))
