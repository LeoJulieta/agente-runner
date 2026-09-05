# Arquitectura P/L/D/E - Laboratorios de Experimentación

## Constitución (4 reglas)

1. **Medición objetiva**: Todo experimento debe producir métricas cuantificables y reproducibles.
2. **Trazabilidad completa**: Cada ejecución registra `lab_id`, `gen`, `params`, `metrics`, `status`, `evidence_count`.
3. **Confianza calculada**: El `confidence` NO se guarda, se calcula al leer con fórmula transparente.
4. **Genealogía explícita**: Campo `gen` guarda la generación del experimento para seguimiento evolutivo.

## Fórmula de Confidence

```python
def calculate_confidence(status: str, evidence_count: int, reproducible: bool, last_test: datetime) -> float:
    """
    confidence = clamp(
        base[status]
        + 0.02 * min(evidence_count, 10)
        + 0.05 * reproducible
        − 0.01 * días_desde_last_test,
        0, 1
    )
    """
    base = {
        "VERIFICADO": 0.85,
        "PROMETE": 0.2,
        "STALE": 0.5,
        "CADUCADO": 0.1
    }

    from datetime import datetime, timezone
    days_since = (datetime.now(timezone.utc) - last_test).days if last_test else 0

    score = (
        base.get(status, 0)
        + 0.02 * min(evidence_count, 10)
        + 0.05 * (1 if reproducible else 0)
        - 0.01 * days_since
    )

    return max(0, min(1, score))  # clamp a [0, 1]
```

### Regla de STALE automático

Si un resultado con `status='VERIFICADO'` cae por debajo de `confidence < 0.7` debido a antigüedad (`días_desde_last_test`),
se marca automáticamente como `STALE` hasta que se re-pruebe.

## Estructura de la tabla `lab_results`

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `id` | bigserial | Primary key |
| `lab_id` | text | Identificador del experimento (ej: `lab_001`) |
| `gen` | int | Generación (default 0) |
| `params` | jsonb | Parámetros del experimento |
| `metrics` | jsonb | Métricas resultantes |
| `status` | text | `PROMETE` \| `VERIFICADO` \| `STALE` \| `CADUCADO` |
| `evidence_count` | int | Cantidad de ejecuciones exitosas acumuladas |
| `reproducible` | bool | `true` si `evidence_count >= 2` |
| `last_test` | timestamptz | Última vez que se ejecutó |
| `creado_en` | timestamptz | Timestamp de creación |

## Fase 0: Tubo de Ensayo

- **lab_001_tracer.py**: Experimento deliberadamente aburrido que mide duración de cálculo trivial + COUNT de `youtube_shorts_log`.
- **lab_tracer.yml**: Workflow dispatch manual para ejecutar el tracer.
- **Objetivo**: Validar el tubo de ensayo antes de agregar complejidad.

## Lo que NO está construido (se gana con evidencia)

- ❌ `strategy.matrix` en workflows
- ❌ Orquestador de múltiples labs
- ❌ Scheduler automático
- ❌ Evolution engine
- ❌ `lab_workers`
- ❌ Dashboards

Cada componente adicional debe justificarse con evidencia de necesidad real.