# PR D v2 — correcciones inferenciales aisladas (candidatas)

## Alcance
Este paquete es una implementación de referencia aislada para revisar cuatro defectos observados en PR #90 contra el contrato normativo PR D v2. No se integra al motor, no lee el manifiesto, no consulta ni escribe Supabase y no ejecuta hipótesis reales.

## Reglas corregidas
1. Familia II: `n_eff` cuenta todas las observaciones elegibles después de filtros; `n_events` cuenta solo elegibles con `Y > 0`. El modelo OLS se ajusta únicamente a los positivos. El gate de `n_eff` no se sustituye por el recuento positivo.
2. Familia I: un tamaño elegible inferior al mínimo devuelve `INSUFFICIENT_POWER`, sin lanzar una excepción estructural ni producir p empírico.
3. BH: los miembros preregistrados `INVALID` y `INSUFFICIENT_POWER` permanecen en la familia con p de ajuste 1.0, manteniendo `p_empirical=null`. La función exige el conjunto congelado explícito de IDs y rechaza omisiones, duplicados o inyecciones.
4. Escalas Familia I: `effect_size`, `ci_low` y `ci_high` son todos coeficiente beta (log-odds). OR e IC del OR se publican en campos separados.

## Interpretación y límites
- La lista `frozen_hypothesis_ids` debe proceder de la preregistración autoritativa, no ser construida a partir de los resultados observados. Este módulo solo comprueba igualdad exacta entre esa lista y los resultados recibidos; no obtiene por sí mismo el manifiesto ni certifica su autenticidad.
- La selección de `min_n_eff`, la definición de elegibilidad y el diseño siguen dependiendo del contrato/hipótesis preregistrados.
- Estos cambios no resuelven T24c, E11, reproducibilidad/drift, versionado v3 ni el pinning de dependencias.
- No autoriza integrar estos módulos en producción ni cambiar `execution_status=fixture`.
