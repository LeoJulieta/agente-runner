# Laboratorio P/L/D/E — Fase 0

Este directorio contiene el laboratorio de experimentación controlada (Promete /
Verificado / Stale / Caducado) para hipótesis del sistema `agente-runner`.
Fase 0 solo establece la infraestructura mínima de medición y trazabilidad.
El motor de hipótesis está VERIFICADO desde Fase 1.

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
| metrics | jsonb | Métricas resultantes (**siempre objeto**, nunca string) |
| `status` | text | `PROMETE` \| `VERIFICADO` \| `STALE` \| `CADUCADO` |
| `evidence_count` | int | Cantidad de ejecuciones exitosas acumuladas |
| `reproducible` | bool | `true` si `evidence_count >= 2` |
| `last_test` | timestamptz | Última vez que se ejecutó |
| `creado_en` | timestamptz | Timestamp de creación |
**Nota técnica**: No existe columna confidence — se calcula al leer (regla 3).
**Seguridad**: RLS habilitado (deny-all anon) + trigger de protección Regla 2/5 a nivel DB (migration 002).

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
- ❌ Generador de experimentos
- ❌ Workers externos / IP no-datacenter del puente GAS
- ❌ Automatización de merge o publicación fuera de PRs auditados

Cada componente adicional debe justificarse con evidencia de necesidad real.

## Publicación automática

El sistema cuenta con dos workflows para gestionar el flujo de publicación:

### Workflow `auto_pr.yml`

- **Propósito**: Crear PRs automáticamente desde GitHub Actions
- **Trigger**: `workflow_dispatch` con inputs `branch_name` y `commit_message`
- **Permisos**: `contents: write` (mínimo necesario)
- **Funcionamiento**: 
  1. Crea una rama desde `main`
  2. El contenido del commit es generado por el workflow que lo invoca
  3. Realiza commit y push
  4. Abre un PR automáticamente con `gh pr create`

### Guard-rail `guard_canal_manual.yml`

- **Propósito**: Detectar y registrar commits directos a `main` sin pasar por PR
- **Trigger**: `on: push` a `main`
- **Acción**: Si el autor NO es `github-actions[bot]` ni un merge de PR, abre automáticamente un issue con:
  - Título: `⚠️ Commit directo a main detectado`
  - Body: hash del commit, autor y mensaje
- **Objetivo**: Prevenir incidentes de canal incorrecto sin intervención humana

### Tu rol como maintainer

- **Solo mergeás PRs**, nunca publicás manual a menos que sea emergencia
- Los workflows automáticos (`github-actions[bot]`) están permitidos
- Los merges de PR están permitidos
- Cualquier otro commit directo a `main` disparará una alerta vía issue

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
## Batches y aprobación

- **Generador determinístico**: Los lotes se generan con `labs/gen_batch.py` (el catálogo vive en el código y se audita en el PR).
- **Flujo**: generador → PR → auditoría de lote por Qwen → verde único de Leo → dos dispatches de `Lab Batch` (reproducibilidad) → veredictos en `lab_results`.
- **Múltiples comparaciones**: con n≈66 y |r|>0.3, ~1.4% de falso positivo por test (~0.10 esperados en 7 tests); sin corrección a esta escala.
- **Guardía out-of-time**: todo ganador se re-dispatchea a los 7 días; si cae, pasa a STALE.

## Constitución v2 — Espacio de búsqueda abierto

1. **Máquina de experimentos, no de laboratorios.** No construimos 100 laboratorios: construimos una máquina que ejecuta N experimentos en el mismo laboratorio.
2. **Descubrimiento, no catálogo.** No le enseñamos a la máquina todas las formas de ganar dinero: construimos una máquina capaz de descubrir formas que todavía no conocemos.
3. **La taxonomía es un mapa, no una frontera.** Describe lo que sabemos hoy; el enjambre tiene permiso permanente para descubrir lo que todavía no sabemos nombrar. Los namespaces son `known`, `combination`, `emerging` (vacía al inicio) y `unknown` (presupuesto, no catálogo).
4. **Un ganador no elimina el bosque.** Ninguna generación puede asignar más del 60% del presupuesto experimental a una sola familia de hipótesis, y el presupuesto `unknown` nunca llega a 0. Regla técnica anti-convergencia prematura.
5. **Un experimento no fracasa: produce evidencia.** Favorable, desfavorable, insuficiente o inválida. Los estados son `VERIFIED / PROMISING / INCONCLUSIVE / FAILED / INVALID / STALE`, y todo `FAILED` o `INCONCLUSIVE` lleva `failure_reason` estructurado (metodológicas: `insufficient_sample`, `weak_effect`, `high_variance`, `temporal_instability`, `invalid_hypothesis`; de mercado: `no_demand`, `saturated_offer`, `price_insufficient`, `no_distribution`, `market_shifted`, `wrong_product`, `wrong_channel`) más `pivot_hint`.
6. **Cinco poblaciones simultáneas.** 🟢 Exploradores (territorios nuevos), 🔵 Explotadores (ramas con evidencia), 🟣 Reexploradores (caminos descartados: el mundo cambia), 🟡 Recombinadores (cruces entre ramas), 🟠 Descubridores (rompen suposiciones del sistema declarando `assumption_under_test`).
7. **Exploración sin dirección, confirmación con dirección.** En exploración no se fija `expected_direction`; al promover una señal a validación confirmatoria, la dirección se preregistra antes de medir.
8. **Lo desconocido que funciona propone, no certifica.** Una hipótesis `category: unknown` que llega a `VERIFIED` propone una entrada nueva en `emerging:`; la creación real requiere auditoría + verde humano.
9. **La imaginación puede ser infinita; la evidencia no.** Toda hipótesis nace `PROMETE` con `evidence_count=0`; ninguna se convierte en hecho sin evidencia reproducible.
