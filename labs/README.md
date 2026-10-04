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


## Deudas metodológicas activas

### D5 — `views_primeras_3h` no mide necesariamente primeras 3 horas
El dataset registra `hs_al_publicar_al_sync` entre 3.03 y 9.85 horas (mediana 4.48h).
La variable llamada "views_primeras_3h" es en realidad "views al primer sync",
observado entre ~3 y ~10 horas después de publicar. Cualquier interpretación de
hipótesis que usen este outcome debe llevar esta advertencia.
Descubierta 28/9/2026. No se renombra la columna (ruptura de historial) pero sí se reinterpreta.

**Observación sobre `likes` (28/9/2026):** 132 de 147 filas tienen `likes=0` (90%).
La correlación fuerte `likes → views_primeras_3h` (r=0.60) está dominada por la
dicotomía "videos con engagement vs sin engagement". Dentro del subconjunto con
`likes>0` (n=15), la correlación cae a r=0.37. El rol del catálogo
(`observational_post_publicacion`) protege contra interpretar esto como palanca causal.

## Protocolo de reproducibilidad out-of-time (PR C, 28/9/2026)

**Definición:** una hipótesis es *consistente en ventanas disjuntas* cuando pasa el
baseline preregistrado en dos particiones temporales independientes (`lt:X` y `gte:X`
con el mismo corte X). Esto mide consistencia temporal, no causalidad ni universalidad.

**Corte preregistrado gen 1:** `2026-09-11T22:15:03.182831Z`
(mediana de `created_at` sobre las 145 filas con outcome no nulo al 28/9/2026).
- Ventana A: `lt:2026-09-11T22:15:03.182831Z` (72 filas)
- Ventana B: `gte:2026-09-11T22:15:03.182831Z` (73 filas)

**Regla:** un solo corte por generación. Cambiar el corte a posteriori es p-hacking.

**Garantías del motor (PR C):**
- Una corrida con ventana REQUIERE baseline previo; nunca lo crea ni modifica.
- Muestra insuficiente o truncamiento (>200 filas) => INVALID, cero inserts.
- `reproducible=true` solo si: passed en esta corrida + evidencia previa con
  `passed=true`, `method_fingerprint` idéntico y ventana observada disjunta.
- El workflow serializa ejecuciones (`concurrency`), así dos primeras corridas
  no pueden competir por crear el baseline.

**Semántica de `metrics.window`:**
- `window.label`: límite temporal declarado y normalizado a UTC canónico
  (microsegundos, sufijo Z) que acotó la consulta. Es el límite preregistrado.
- `window.start` / `window.end`: timestamp mínimo y máximo de `created_at`
  (canon UTC) de las observaciones efectivamente utilizables en ESA corrida.
  Describen la muestra observada; NO reemplazan ni redefinen el límite de `label`.
- `universe_rows`: filas que cumplieron los filtros de la consulta experimental
  (outcome no nulo, fuentes no nulas, ventana) y fueron devueltas. No es el total
  de la tabla en la ventana. Es exacta porque el motor pide MAX+1 y solo acepta
  si vinieron <= MAX.
- `universe_rows_at_least: 201`: solo en truncamiento; significa ">= 201".
- `rows_used`: pares X/Y utilizables tras derivación y filtros.
- `dataset_rows_at_cutoff`: metadato de preregistro declarado por el operador del
  workflow. El motor lo copia verbatim y NO lo verifica. Preregistro declarado ≠
  medición verificada.

**Semántica de `sample_size`:** en corridas válidas o con muestra insuficiente es el
número de pares X/Y utilizables. En INVALID por truncamiento es `null`: el universo
se reporta como `universe_rows_at_least` y no se afirma un tamaño de muestra.

**Semántica de `evidence_count`:** número acumulado de filas de evidencia persistidas
para el lab_id. La fila de baseline (`record_type: baseline`) no cuenta como evidencia.

**Nota metodológica del baseline:** el baseline `historical_median` de la primera
corrida se calcula sobre los últimos 100 registros del mismo dataset que usa esa
primera medición, y puede compartir observaciones con ella. Es un umbral
preregistrado (Regla 5), no una muestra de control estadísticamente independiente.
La independencia que prueba el protocolo es la temporal entre ventanas disjuntas.

**Alcance de `reproducible`:** solo puede activarse entre dos corridas con ventanas
observadas disjuntas y el mismo `method_fingerprint`. Una corrida sin ventana nunca
aporta evidencia independiente. `reproducible=false` NO significa fallo experimental:
significa "todavía sin confirmación out-of-time".

**Uso:**

    python labs/lab_engine.py --hypothesis H041_EXPR \
      --window "lt:2026-09-11T22:15:03.182831Z" --cutoff-rows 145
