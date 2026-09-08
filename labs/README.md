# Laboratorio P/L/D/E — Fase 0

Este directorio contiene el laboratorio de experimentación controlada (Promete /
Verificado / Stale / Caducado) para hipótesis del sistema `agente-runner`.
Fase 0 solo establece la infraestructura mínima de medición y trazabilidad.
No implementa todavía el motor de hipótesis ni ningún worker externo.

## Constitución (5 reglas)

1. **Medición objetiva.** Todo resultado se basa en una métrica medible y
   reproducible (duración, conteos, deltas) — nunca en una apreciación
   subjetiva de si "funcionó bien".
2. **Trazabilidad.** Cada corrida queda registrada en `lab_results` con su
   `lab_id`, sus `params`, sus `metrics` y su `status`. Nada se descarta ni se
   sobrescribe: la historia completa vive en la tabla.
3. **Confidence calculada al leer, no al escribir.** El campo de confianza no
   se guarda como columna; se calcula en el momento de la lectura a partir de
   `status`, `evidence_count`, `reproducible` y la antigüedad del último test
   (ver fórmula abajo).
4. **Genealogía por `gen`.** Cada evolución de una hipótesis incrementa `gen`
   en vez de reemplazar la fila anterior, preservando el linaje completo de
   cómo llegó a su estado actual.
5. **Baseline congelado — INVIOLABLE.** Una vez que un `lab_id` establece su
   primera medición base, esa fila no se edita ni se borra bajo ninguna
   circunstancia. Todo cambio posterior es una fila nueva.

## Fórmula de confidence

Calculada al leer, no almacenada:

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

Si un resultado con `status='VERIFICADO'` cae por debajo de `confidence < 0.7` debido a antigüedad (`días_desde_last_test`), se marca automáticamente como `STALE` hasta que se re-pruebe.

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

## Motor de hipótesis (Fase 1)

El motor `lab_engine.py` ejecuta hipótesis declaradas en `labs/hypotheses/*.yaml`.

### Contrato YAML

Cada hipótesis es un archivo YAML con esta estructura:

```yaml
id: H001
description: "Descripción de la hipótesis"
class: A  # A (read-only) | B (recurso externo) | C (producción/dinero)
gen: 0

dataset:
  - nombre_tabla

vars:
  independent:
    - columna_independiente
  dependent:
    - columna_dependiente

# Opcional: deriva variables virtuales (ej: hora_local desde timestamp)
derive:
  nombre_variable_virtual:
    source: columna_origen
    subtract_hours_from_column: columna_restar
    tz_offset_hours: -3
    extract: hour

metric:
  primary: nombre_metrica

baseline:
  type: fixed  # fixed | historical_median | mean
  value: 0.3   # valor fijo para baseline
  description: "Descripción del baseline"

comparison:
  type: greater_than  # greater_than | less_than | delta_percent
  description: "Descripción de la comparación"

sample_min: 30
max_runtime: 300

evidence_required: true
reproducibility_required: true

cost_limit: 0
authorized: false  # true solo si clase B tiene aprobación
```

**Regla de muestreo**: Si `sample_size < sample_min`, el motor reporta `status: PROMETE` con `reason: "muestra insuficiente"` y NO calcula la métrica (correlation = null).

### Clases de hipótesis

- **Clase A**: Read-only sobre tablas existentes. Puede ejecutarse tras aprobación de batch.
- **Clase B**: Requiere recurso externo (API, sandbox, worker). Necesita `authorized: true` en el contrato.
- **Clase C**: Producción, dinero, terceros. El motor SIEMPRE la rechaza (camino humano obligatorio).

### Regla INVIOLABLE 5: Baseline congelado

Al registrar una hipótesis (primera corrida), el motor calcula el baseline y lo congela en una fila con `status: PROMETE`. Ese baseline NUNCA se recalcula. Si el dataset cambia, se crea `gen+1` con baseline propio.

### Uso

```bash
python labs/lab_engine.py --hypothesis H001
```

O desde GitHub Actions: **Actions → Lab Run → Run workflow → hypothesis_id: H001**
