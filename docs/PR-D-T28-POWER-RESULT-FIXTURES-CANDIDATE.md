# PR D T28 — fixtures candidatos de consistencia de salida de potencia

**Estado:** candidato de prueba sintética; no normativo.  
**Objetivo:** caracterizar únicamente la forma de salida y la coherencia entre `n_required_power`, `reason` y `unit`.  
**No objetivo:** calcular potencia, escoger un método estadístico, declarar potencia garantizada, ni cambiar el motor.

## Reglas de forma verificadas

- Resultado informativo válido: valor numérico, finito y estrictamente positivo; `reason=null`; unidad en `eligible_observations` o `positive_events`.
- Resultado no calculable: `value=null`; uno de los cinco motivos cerrados; `unit=null`.
- Combinaciones inconsistentes, NaN/Infinity, valores no positivos, booleanos o unidades no admitidas se rechazan como salida mal formada.

Los números `42` y `18` del fixture son ejemplos ilustrativos de forma, **no** resultados calculados ni valores de aceptación científica.

## Cinco motivos de nulidad

1. `method_not_preregistered`
2. `missing_parameters`
3. `assumptions_not_met`
4. `unsupported_family_or_model`
5. `invalid_effect_specification`

## Bloqueo que no se resuelve aquí

T24c sigue bloqueado. Antes de cualquier cálculo real o incluso de fijar un resultado de referencia, una revisión separada debe preregistrar el método de potencia, efecto mínimo, alfa, potencia objetivo, diseño y parámetros, unidad de análisis y una referencia independiente. No se infiere potencia de `n_eff >= 30` ni de EPV.

## Salvaguardas

- No se importa ni modifica `labs/lab_engine.py`.
- No se ejecutan hipótesis reales ni se accede/escribe en Supabase.
- No se modifica `docs/manifest.json`; `execution_status` debe seguir siendo `fixture`.
- E6–E11 siguen siendo candidatas; estas pruebas no certifican T28 ni la matriz completa.
