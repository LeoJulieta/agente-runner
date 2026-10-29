# PR D — decisión propuesta de versionado contractual

**Estado:** propuesta para auditoría humana; no aprobada ni vigente en `main`.
**Fecha:** 2026-10-29
**Base normativa vigente:** PR D v2, E1–E5, congelado el 2026-10-09.
**Alcance:** control documental y versionado. No autoriza implementación, hipótesis reales ni escrituras en Supabase.

## 1. Decisión propuesta

1. Mantener **PR D v2 (E1–E5)** como contrato vigente y congelado en `main`.
2. Tratar E6–E11 como **candidato de revisión PR D v3.0**, exclusivamente para revisión. No es una aprobación ni una declaración de compatibilidad ya demostrada.
3. No sobrescribir el contrato vigente ni modificar `docs/manifest.json` en esta etapa.
4. Si la auditoría humana y externa aprueba E6–E11, integrar la versión candidata mediante un cambio coordinado y revisable: contrato versionado, huella SHA-256 actualizada en el manifiesto de fixture y pruebas de consistencia documental. La actualización del manifiesto será un cambio separado o una etapa explícita posterior, con su propia revisión.
5. Mantener `execution_status: "fixture"`. Esta decisión no autoriza activar ejecuciones, modificar datos ni fusionar el PR de trazabilidad (#90).

## 2. Evidencia de control de versiones

Las huellas se calcularon sobre el contenido UTF-8 de `docs/PR-D-DESIGN.md`:

| Referencia | SHA-256 | Estado |
|---|---|---|
| `main:docs/PR-D-DESIGN.md` | `0ca1aa8c452b4d2bb974070f71f7ea315e5f4a156b98bc1d9a01f5e3fd019f89` | Contrato vigente E1–E5 |
| `docs/pr-d-v2-amendments-e6-e11:docs/PR-D-DESIGN.md` | `21664b7a5c6f24e876fa7072db54e29b12446a64d0f106c9d60f702478fb9cd8` | Candidato que añade E6–E11 |
| `main:docs/manifest.json` → `contract_sha256` | `0ca1aa8c452b4d2bb974070f71f7ea315e5f4a156b98bc1d9a01f5e3fd019f89` | Coincide con el contrato vigente |

La diferencia de huellas corresponde a una diferencia contractual real: el candidato añade la sección 16 (E6–E11). No es correcto describir esas enmiendas como ya aprobadas en `main`.

## 3. Regla de versionado y clasificación de E6–E11

E6–E11 se presentan para cerrar ambigüedades detectadas en la matriz, pero varias cambian resultados observables: estados de B, semántica de reproducibilidad, clasificación de no estimabilidad y reglas de drift/aceptación. Por ello, no es prudente etiquetarlas como versión menor. Regla de versionado propuesta: **patch** solo para cambios editoriales sin efecto contractual; **minor** para extensiones compatibles que no cambian estados, gates, estimandos, inferencia, criterios de reproducibilidad ni campos obligatorios; **major** para cambios que alteren cualquiera de esos elementos, la interpretación de resultados o el `method_fingerprint`. Bajo esta regla, E6–E11 deben auditarse como candidato mayor PR D v3.0. Esta clasificación es propuesta y no aprueba el método ni la implementación.

## 4. Condiciones obligatorias antes de promover el candidato

- Revisión humana de cada enmienda E6–E11 y su interacción con E1–E5.
- Tabla de aceptación completa, con criterios de entrada/salida inequívocos y casos negativos; T24c sigue bloqueado hasta preregistrar método de potencia, efecto mínimo, alfa, potencia objetivo, parámetros de diseño, unidad y referencia calculada independientemente.
- Verificación de correspondencia entre contrato, tabla, matriz, pruebas y huellas; ninguna referencia debe llamar “vigente” a la candidata antes de aprobación.
- Revisión del impacto de versión sobre `method_fingerprint` y manifiestos; no inferir equivalencia de método por el mero hecho de ser una enmienda documental.
- CI y revisión de los cambios documentales en la rama candidata.
- Autorización explícita antes de fusionar cualquier PR. PR #90 permanece sin fusionar.

## 5. Límites de seguridad

Esta propuesta no modifica `main`, el contrato vigente ni `docs/manifest.json`; no cambia código estadístico, workflows, hipótesis, esquema ni datos; no conecta ni escribe en Supabase; no cambia `execution_status`; no autoriza ejecución de hipótesis reales. El código y las pruebas que existan en ramas candidatas siguen siendo evidencia aislada hasta que se auditen y prueben en el flujo integrado.

## 6. Resultado solicitado a los revisores

Confirmar o rechazar explícitamente:

1. Mantener E1–E5 como PR D v2 vigente.
2. Adoptar **PR D v3.0** como identificador provisional del candidato E6–E11, sujeto a revisión; no promocionar como v2.1 porque las enmiendas afectan semántica observable.
3. Requerir aprobación separada y sincronización de hash/manifiesto antes de promoverlo a vigente.
4. Mantener bloqueado cualquier cambio de implementación o ejecución hasta cerrar la tabla de aceptación y los bloqueos técnicos.

**No se registra aprobación automática por la creación de este documento o de un pull request.**
