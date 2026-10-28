# PR D v2 — Matriz inicial de trazabilidad contractual

**Estado del documento:** borrador de auditoría; no constituye aprobación científica ni autorización de ejecución.  
**Base auditada:** `main` en el commit `ae8314192c0f031db292844004953383b3030679` (PR #89).  
**Contrato de referencia:** [`docs/PR-D-DESIGN.md`](PR-D-DESIGN.md), versión PR D v2, congelada el 2026-10-09.  
**Límite de seguridad:** mantener `docs/manifest.json` en `execution_status: "fixture"`; no ejecutar hipótesis reales ni escribir en Supabase de producción.

## Criterio de clasificación

- **[✅ IMPLEMENTADO]**: hay implementación identificada y prueba que verifica el requisito relevante; el alcance probado está delimitado.
- **[⚠️ PARCIAL]**: existe código o prueba relacionada, pero la evidencia no demuestra el cumplimiento completo del contrato.
- **[❌ AUSENTE]**: en la inspección inicial no se identificó implementación/prueba que cubra la regla. Esto significa «no demostrado en esta auditoría», no prueba universal de inexistencia.
- **[🔎 POR VERIFICAR]**: hace falta inspeccionar más código, tests o el entorno para clasificar honestamente.

Esta primera versión es una **matriz de trabajo**, no el cierre de la auditoría. Las referencias a archivos son rutas de `main`; las líneas se añadirán cuando se termine la inspección granular. No se considera un requisito verde solo porque el nombre de un campo o una función aparezca en el repositorio.

## Resumen ejecutivo

| Área contractual | Evidencia localizada | Estado inicial |
|---|---|---|
| Manifiesto congelado, hash del contrato, identidad de familias y `m` | `labs/pr_d_manifest.py`, `tests/test_pr_d_manifest.py`, `tests/test_pr_d_single_run_gate.py` | [⚠️ PARCIAL] |
| Gate de ejecución y pertenencia al manifiesto | `labs/pr_d_single_run_gate.py`; gate también integrado en `labs/lab_engine.py` | [⚠️ PARCIAL] |
| Persistencia atómica e idempotencia | `supabase/migrations/004_pr_d_v2_atomic_persistence.sql`, pruebas de RPC y E2E local | [✅ IMPLEMENTADO] para el alcance de persistencia probado; no certifica estadística |
| Recorrido motor → cliente Supabase → PostgREST/RPC local | `.github/workflows/pr-d-engine-http-e2e.yml`, `tests/e2e/test_pr_d_engine_http_e2e.py` | [✅ IMPLEMENTADO] para la prueba E2E local de H990 |
| Regresión logística Familia I | No se identificó todavía un módulo/test específico que demuestre el método contractual | [🔎 POR VERIFICAR] |
| OLS sobre ln(Y) con HC3 Familia II | No se identificó todavía una implementación/test que demuestre `statsmodels.OLS.fit(cov_type="HC3")` en el camino real | [🔎 POR VERIFICAR] |
| FDR Benjamini–Hochberg por familia y ventana congeladas | La validación del manifiesto existe; falta demostrar cálculo FDR en el camino científico | [🔎 POR VERIFICAR] |
| Ventanas A/B disjuntas y antecedente para `VERIFICADO` | Falta completar inspección de implementación y tests específicos | [🔎 POR VERIFICAR] |
| Drift `d_init`, `D_cond`, MAD degenerada y serialización finita | Falta identificar implementación y pruebas deterministas específicas | [🔎 POR VERIFICAR] |
| `method_fingerprint`, reproducibilidad y compatibilidad de efectos/IC | Campo contractual localizado; cumplimiento efectivo pendiente de trazabilidad | [🔎 POR VERIFICAR] |
| Estados, precedencia, `p=1` para fallo individual y códigos de salida | Hay gates estructurales; falta demostrar todo el retorno científico de §9, §13 y §15 | [⚠️ PARCIAL] |
| `n_total`, `n_eff`, `n_events`, truncamiento y `n_required_power` | Falta trazar cálculo, persistencia y pruebas de borde | [🔎 POR VERIFICAR] |
| Auditoría de esquema e historial de migraciones de Supabase de producción | No se realizó en esta matriz; requiere consulta separada, de solo lectura | [🔎 POR VERIFICAR] |

## Matriz de reglas contractuales

| Regla | Requisito verificable | Implementación localizada | Prueba/evidencia localizada | Estado inicial y brecha |
|---|---|---|---|---|
| §2, §6.1 | Familia I: outcome binario Y>0; regresión logística por máxima verosimilitud; Wald bilateral preregistrado; IC95% del OR; no sustituir silenciosamente por Fisher | Pendiente de localizar módulo de inferencia real | Pendiente de localizar tests específicos | [🔎 POR VERIFICAR] No marcar verde sin verificar fórmula, estimador, errores, IC y fallos de convergencia/separación |
| §2, §6.2, §13.5, §13.9 | Familia II: Y>0, transformación ln(Y), OLS, t bilateral e IC con HC3 fijo | Pendiente de localizar módulo de inferencia real | Pendiente de localizar test HC3 y casos no estimables | [🔎 POR VERIFICAR] La mención contractual a statsmodels no demuestra implementación |
| §3 | Ventanas A y B disjuntas, preregistradas; outcome, filtros y elegibilidad compatibles; B no modifica A | Pendiente | Pendiente | [🔎 POR VERIFICAR] Requiere pruebas de límites temporales y no solapamiento |
| §4, §12 | Identidad, esquema, roles, filtros, dirección, efecto mínimo, método, fingerprint, sincronización, truncamiento; separar n_total/n_eff/n_events | Validación parcial de contrato/dataset en `labs/lab_engine.py` | Tests de engine existentes por inspeccionar en detalle | [⚠️ PARCIAL] Los validadores visibles no demuestran todos los cálculos y metadatos de salida |
| §5, §5.1 | Benjamini–Hochberg con q≤0.05 por familia y ventana; mantener m congelado; miembros no evaluables con p=1 sin eliminarse | `labs/pr_d_manifest.py` valida estructura de familias y m | `tests/test_pr_d_manifest.py` valida el manifiesto; falta localizar test de cálculo FDR | [⚠️ PARCIAL] Validar m no equivale a ejecutar BH correctamente |
| §7 | effect_size, IC, dirección y efecto mínimo en escala preregistrada; RECHAZA no equivale a ausencia de efecto | Pendiente de trazar el resultado estadístico | Pendiente | [🔎 POR VERIFICAR] |
| §8.1 | d_init=abs(p_A−p_B), umbral estricto >0.10, finito y sin NaN/Infinity | Pendiente de localizar cálculo | Pendiente de tests de borde | [🔎 POR VERIFICAR] |
| §8.2–8.4, §13.2 | D_cond basado en medianas logarítmicas positivas y MAD escalada; umbral >0.50; degeneración sin epsilon; menos de 5 eventos => null; flag combinado | Pendiente de localizar cálculo | Pendiente de casos de aceptación para MAD cero/medianas iguales y distintas | [🔎 POR VERIFICAR] |
| §9 | Precedencia INVALID → INSUFFICIENT_POWER → RECHAZA → PROMETE → VERIFICADO según condiciones contractuales | Gates de validación y autorización existen; estados científicos completos por trazar | Tests del gate no prueban toda la precedencia estadística | [⚠️ PARCIAL] |
| §10, §13.3–13.4 | B requiere A compatible, mismo fingerprint, estado antecedente permitido; reproducible_state distingue reproducible/no_reproducible/not_evaluable | Columna boolean `reproducible` preservada por migración; resto por trazar | E2E valida persistencia/idempotencia, no comparación A/B | [⚠️ PARCIAL] |
| §11 | Salida incluye campos mínimos y valores no calculables como null con causa; JSON finito | Persistencia atómica está probada para la forma de evidencia de fixture | E2E no valida el esquema científico completo | [⚠️ PARCIAL] |
| §12, §13.6, §13.8 | n_required_power informativo, método aplicable y motivo cuando null; n_eff≥30 no se presenta como potencia garantizada; deuda PR D.2 explícita | Pendiente de localizar cálculo/campos | Pendiente | [🔎 POR VERIFICAR] |
| §13.1, §15.1 | Fallo estructural aborta lote; fallo individual conserva posición en m, p=1 y causa cerrada; YAML ausente no inventa resultados | `labs/pr_d_manifest.py` incluye `find_missing_hypothesis_specs`; flujo completo por trazar | Tests de manifest por inspeccionar; faltan tests científicos de p=1/posición FDR identificados | [⚠️ PARCIAL] |
| §13.7, §14 | Cada regla tiene casos deterministas con entrada, condiciones, estado y campos esperados; misma entrada/contrato no produce decisiones distintas | Test suite parcial existente | Falta inventario T01… y cobertura por regla | [⚠️ PARCIAL] |
| §13.9 | HC3 no cambia según diagnósticos; d_init finito en doble precisión | Pendiente de confirmar en camino real | Pendiente | [🔎 POR VERIFICAR] |
| §15.1 | Manifiesto versionado con commit/hash, familias ordenadas, m, outcomes, contrastes, ventanas y método; causas cerradas para specs ausentes | `labs/pr_d_manifest.py` valida campos requeridos y hash del contrato; la huella exacta de commit/manifest en cada resultado queda por trazar | Tests de manifest existentes; cobertura integral pendiente | [⚠️ PARCIAL] |
| §15.2 | Validar parámetros antes de suficiencia; INVALID para parámetros inválidos, INSUFFICIENT_POWER para n=0/n<sample_min; resultado científico estructurado y códigos de proceso mapeados | `labs/lab_engine.py` tiene validadores y gates; retorno científico completo por trazar | E2E local valida exit 0 para fixture aprobado, no todos los estados | [⚠️ PARCIAL] |
| §15.3, §15.4 | Persistencia transaccional/idempotente/concurrente; códigos 0/1/2 y conducta de lote conforme a contrato | Migración RPC y pruebas de persistencia cubren atomicidad/idempotencia; concurrencia y códigos de proceso deben mapearse regla por regla | Tests RPC/E2E; cobertura completa de concurrencia/rollback debe verificarse por archivo | [⚠️ PARCIAL] |
| §15.5–§15.6 | Gate 0 antes de credenciales/cliente; contrato congelado y autorización explícita; condiciones de salida antes de cualquier fase científica | `labs/pr_d_manifest.py`, `labs/pr_d_single_run_gate.py`, `labs/lab_engine.py`, workflows de ejecución | Tests de manifest/gate y E2E; falta comprobar cada workflow y el orden de importación/lectura de secretos | [⚠️ PARCIAL] |

## Evidencia de infraestructura ya identificada

- [Manifiesto congelado](manifest.json): en `main` debe permanecer `execution_status: "fixture"`.
- [Validador del manifiesto](../labs/pr_d_manifest.py): valida forma, hash contractual, familias, m y pertenencia opcional al inventario.
- [Gate de corrida individual](../labs/pr_d_single_run_gate.py): exige `approved` y pertenencia de la hipótesis al manifiesto.
- [Workflow E2E](../.github/workflows/pr-d-engine-http-e2e.yml) y [test E2E](../tests/e2e/test_pr_d_engine_http_e2e.py): prueban el motor real contra Supabase local descartable y reintento idempotente de H990.
- [Migración atómica](../supabase/migrations/004_pr_d_v2_atomic_persistence.sql): implementa el camino RPC de persistencia; revisar sus tests para enumerar exactamente atomicidad, idempotencia, concurrencia, grants y rollback.

## Bloqueantes para cerrar la matriz

1. Localizar todos los módulos y tests de inferencia estadística; no asumir que existen por referencias en el contrato.
2. Revisar el cuerpo completo de `labs/lab_engine.py` y los archivos importados, no solo las funciones de validación.
3. Vincular cada regla con pruebas específicas y casos de borde deterministas; los tests de persistencia no cuentan como evidencia de estadística.
4. Revisar workflows individual y batch para confirmar que los gates se ejecutan antes de credenciales y clientes, y que los disparadores CI cubren contrato/manifiesto donde corresponde.
5. La auditoría de producción es una tarea separada de solo lectura; esta matriz no afirma haber consultado ni validado el esquema de producción.

## Decisión

**No autoriza ejecución científica. No cambia el manifiesto. No sustituye la revisión humana.** La matriz debe alcanzar cobertura verificable requisito por requisito; un porcentaje global no debe ocultar reglas críticas ausentes o parciales.
