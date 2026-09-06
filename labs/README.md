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

```
base =
    0.85 si status == 'VERIFICADO'
    0.20 si status == 'PROMETE'
    0.50 si status == 'STALE'
    0.10 si status == 'CADUCADO'

confidence = base
    + 0.02 * min(evidence_count, 10)
    + 0.05 * (1 si reproducible else 0)
    - 0.01 * dias_desde(last_test)
```

El resultado se recorta al rango `[0, 1]`.

## Regla STALE

Si `confidence < 0.7` en el momento de la lectura, el resultado se considera
**STALE** independientemente del `status` guardado, y debe re-testearse antes
de usarse como base de una decisión.

## Estructura de la tabla `lab_results`

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | bigserial (PK) | Identificador incremental |
| `lab_id` | text | Identificador del experimento (ej. `lab_001`) |
| `gen` | int | Generación dentro del linaje del experimento |
| `params` | jsonb | Parámetros usados en la corrida |
| `metrics` | jsonb | Métricas medidas (nunca como string, siempre como objeto) |
| `status` | text | Uno de `PROMETE`, `VERIFICADO`, `STALE`, `CADUCADO` |
| `evidence_count` | int | Cantidad acumulada de corridas que respaldan el resultado |
| `reproducible` | bool | `true` si `evidence_count >= 2` |
| `last_test` | timestamptz | Momento de la última corrida |
| `creado_en` | timestamptz | Momento de creación de la fila |

No existe columna `confidence` — se calcula siempre al leer (regla 3).

## Lo que NO está construido todavía

- El motor de hipótesis (`lab_engine`).
- El generador de experimentos.
- Cualquier worker externo (incluyendo IPs no-datacenter para reintentar el
  puente GAS).
- Cualquier automatización de merge o publicación fuera de la rama
  `fase-0-lab`.
