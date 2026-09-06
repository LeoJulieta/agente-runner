"""
labs/lab_001_tracer.py

Lab 001 - Tracer básico del laboratorio P/L/D/E.
Mide un cálculo trivial + hace un COUNT exact (solo lectura) de youtube_shorts_log,
compara contra la última fila registrada en lab_results para lab_id='lab_001',
e inserta una nueva fila con la evidencia acumulada.

Env requeridas: SUPABASE_URL, SUPABASE_KEY
"""

import os
import json
import time
from datetime import datetime, timezone

from supabase import create_client

LAB_ID = "lab_001"


def main() -> None:
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]
    supabase = create_client(supabase_url, supabase_key)

    # (a) Medir duración de un cálculo trivial + COUNT exact de youtube_shorts_log (solo lectura)
    start = time.perf_counter()
    _ = sum(i * i for i in range(100_000))  # cálculo trivial, no toca producción
    count_response = (
        supabase.table("youtube_shorts_log")
        .select("id", count="exact")
        .limit(1)
        .execute()
    )
    total_shorts = count_response.count
    duration_ms = round((time.perf_counter() - start) * 1000, 3)

    metrics = {
        "duration_ms": duration_ms,
        "total_shorts": total_shorts,
    }

    # (b) Leer última fila de lab_results con lab_id='lab_001' y calcular deltas
    last_row_response = (
        supabase.table("lab_results")
        .select("*")
        .eq("lab_id", LAB_ID)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    last_rows = last_row_response.data or []

    previous_evidence_count = 0
    delta_duration_ms = None
    delta_total_shorts = None

    if last_rows:
        last_row = last_rows[0]
        previous_evidence_count = last_row.get("evidence_count") or 0
        last_metrics = last_row.get("metrics") or {}
        prev_duration = last_metrics.get("duration_ms")
        prev_total_shorts = last_metrics.get("total_shorts")

        if prev_duration is not None:
            delta_duration_ms = round(duration_ms - prev_duration, 3)
        if prev_total_shorts is not None and total_shorts is not None:
            delta_total_shorts = total_shorts - prev_total_shorts

    metrics["delta_duration_ms"] = delta_duration_ms
    metrics["delta_total_shorts"] = delta_total_shorts

    new_evidence_count = previous_evidence_count + 1
    reproducible = new_evidence_count >= 2

    # (c) Insertar fila nueva. Round-trip ok si pudimos leer el COUNT sin error.
    round_trip_ok = total_shorts is not None
    status = "VERIFICADO" if round_trip_ok else "PROMETE"

    insert_payload = {
        "lab_id": LAB_ID,
        "gen": 0,
        "params": {"trivial": True},
        # CRÍTICO: la columna metrics es jsonb -> pasar el dict tal cual,
        # NUNCA json.dumps(metrics), o Supabase lo guarda como string escapado.
        "metrics": metrics,
        "status": status,
        "evidence_count": new_evidence_count,
        "reproducible": reproducible,
        "last_test": datetime.now(timezone.utc).isoformat(),
    }

    insert_response = supabase.table("lab_results").insert(insert_payload).execute()

    output = {
        "lab_id": LAB_ID,
        "status": status,
        "evidence_count": new_evidence_count,
        "reproducible": reproducible,
        "metrics": metrics,
        "insert_ok": bool(insert_response.data),
    }

    print(json.dumps(output))


if __name__ == "__main__":
    main()
