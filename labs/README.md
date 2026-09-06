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
