# E12 — estado integral, evidencia y pendientes de escalabilidad

Fecha de corte: 2026-11-14 UTC  
Repositorio: `LeoJulieta/agente-runner`  
Rama de trabajo: `sandbox/e12-postgrest-contract-2026-11-13`  
SHA de código al corte: `c525af52e9c98c1c346ce7e9dafc82b75aa9f293`

## 1. Dictamen ejecutivo

E12 avanzó desde pruebas unitarias/SQL descartables hasta una integración de worker Deno completo contra PostgREST HTTP real sobre PostgreSQL descartable. Sin embargo, el último workflow CI #94 terminó **FAILURE**. No se debe declarar verde el estado actual ni promover la rama.

El job `lease-fencing` pasó. En `postgrest-contract`, el E2E Deno del worker completo pasó (1/1), pero falló la prueba Python auxiliar de contrato RPC porque el E2E anterior ya había escrito las filas fixture que el test Python esperaba capturar por primera vez. El log muestra `captured:false` donde el test esperaba `true`. La lectura de los fixtures y el orden del workflow confirman colisión/reutilización de IDs de prueba, no una demostración de fallo de la lógica de producción. Debe corregirse con fixtures independientes y volver a ejecutar CI.

## 2. Entregables implementados y verificados históricamente

### 2.1 Batch CAS — rama separada

Rama: `sandbox/e12-batch-cas-2026-11-13`

- RPC pública `public.pr_d_capture_views_batch(jsonb)`, con límite 1–50 observaciones.
- Delegación por observación a `pr_d_internal.pr_d_capture_views_once`.
- Conserva validación de payload canónico, digest, clave activa, HMAC, identidad, lease/fencing y first-write-wins.
- Worker agrupa observaciones, renueva lease antes del lote y renueva de nuevo si el margen TTL lo exige.
- Tests cubren límites, duplicados, campos/tipos, HMAC inválido, fencing obsoleto, concurrencia y rollback transaccional.
- CI #78, run `43452302068`: SUCCESS; Deno 31/31 y PostgreSQL 17 13/13.
- Prueba de carga sintética: 500 candidatos, 10 consultas YouTube simuladas y 10 RPC batch; 34 solicitudes HTTP interceptadas y 105 ms. Es una prueba con fetch interceptado, no tráfico real ni benchmark externo.
- Código: `6f21b8195784c0fce2c6282b1b78dd8b0cf7f816`.
- Documentación app: `7d5dc7bce883c9b457e73dc0ec9357b5a4cc14a4`.

### 2.2 PostgREST HTTP descartable

Rama: `sandbox/e12-postgrest-contract-2026-11-13`

- PostgreSQL 17 descartable y PostgREST 12.2.3 en contenedor.
- Rol `authenticator` no-superusuario, membresía limitada a `anon`, `authenticated` y `service_role`.
- JWT de prueba con claim `role=service_role`.
- Verificados por HTTP: claim lease, batch CAS, first-write-wins, release/takeover, incremento fencing, rechazo token obsoleto, escritura vigente, readback SQL y denegación a `anon`.
- CI #79 run `43453183806`: SUCCESS; Deno 31/31, PostgreSQL 13/13, PostgREST HTTP 1/1.
- Código base HTTP: `4c57ee55068935fa541f52f031ae5ff2cb61b9ae`.
- Límite: no reproduce Supabase API Gateway ni traduce/valida la clave moderna `sb_secret_...` enviada por `apikey`.

### 2.3 Worker Deno completo contra PostgREST

Añadido en la rama de integración:

- `supabase/functions/e12-capture/worker_postgrest_e2e_test.ts`: ejecuta `handleE12Capture` real, con fake YouTube, JWT de prueba y PostgREST HTTP real.
- Claves Ed25519/HMAC efímeras registradas solo en DB descartable.
- Verifica captura, persistencia, identidad, fencing, canonical payload, SHA-256, firma Ed25519 y HMAC mediante verificación offline.
- Repite el mismo batch después del commit simulando respuesta HTTP perdida; espera tres resultados `captured:false` para comprobar first-write-wins.
- El test E2E pasó en CI #92 y volvió a pasar en CI #94: 1 passed, 0 failed.
- El fake YouTube no consulta el servicio real.

La prueba auxiliar Python `test_postgrest_integration.py` usa una identidad HMAC determinista independiente y verifica contrato HTTP, roles, fencing y persistencia. Su firma Ed25519 es un placeholder estructural: no debe confundirse con la verificación criptográfica real que sí hace el nuevo test Deno.

## 3. Estado CI al corte

| Run | SHA | Resultado | Interpretación |
|---|---|---|---|
| #79 / `43453183806` | `4c57ee5...` | SUCCESS | PostgREST HTTP básico y tests anteriores |
| #92 / `43540290764` | `9dbae430...` | FAILURE | E2E Deno pasó; Python falló por registro de clave HMAC distinto |
| #93 / — | `530f8f7...` | CANCELLED | Sustituida por un commit posterior |
| #94 / `43546440805` | `c525af52...` | FAILURE | E2E Deno pasó; Python esperaba first-write pero recibió `captured:false` |

Run #94: https://github.com/LeoJulieta/agente-runner/actions/runs/43546440805

### Diagnóstico concreto de #94

El workflow ejecuta primero `worker_postgrest_e2e_test.ts` y luego `test_postgrest_integration.py) sobre la misma base descartable. El E2E procesa tres candidatos; el test Python después intenta usar IDs 1 y 2 como si fueran nuevos. El log Python muestra que el primer CAS devuelve `{"row_id":"1","captured":false}`, porque el E2E anterior ya escribió esa fila. El helper de preparación y ambos tests confirman que comparten la misma DB y fixtures. Esto es contaminación entre pruebas por IDs compartidos.

Corrección prevista: reservar IDs dedicados y filas propias para el test Python (por ejemplo, 101 y 102), verificar explícitamente que no existan antes del test, y consultar únicamente esas filas. No cambiar semántica first-write-wins para hacer pasar el test. Ejecutar la suite completa de nuevo.

## 4. Qué está probado y qué no

**VERIFICADO en CI descartable**
- Deno unit/worker/collector/lease/provenance en los runs indicados.
- PostgreSQL 17 con migraciones E12 y tests adversariales SQL.
- PostgREST HTTP real para las RPC y límites de roles.
- Worker Deno completo contra PostgREST real, con YouTube simulado.
- Verificación Ed25519/HMAC del registro persistido y replay batch idempotente en el test Deno.

**NO probado**
- Supabase API Gateway real, autenticación con `sb_secret_...` y su traducción a JWT/claims.
- YouTube API real, cuota, latencia o comportamiento externo.
- Carga real, rendimiento de red y escalabilidad de 8+ workers/agentes.
- Fault injection exhaustiva: timeout, HTTP 500, desconexión antes/después del commit, respuesta perdida en cada frontera, expiración del lease en mitad del lote, takeover simultáneo y retry concurrente.
- Instalación/upgrade/replay/rollback/restore sobre una copia íntegra del esquema productivo.
- Auditoría independiente por un segundo revisor.
- Promoción o despliegue productivo.

## 5. Estado productivo observado previamente

En inspección de solo lectura del proyecto Supabase `btvfhopootvkqnpbctsq`:
- Proyecto ACTIVE_HEALTHY, PostgreSQL 17.6.
- El historial de migraciones productivas observado terminaba en `20260906020435 create_lab_results`.
- No se encontraron las tablas/funciones E12 consultadas (`pr_d_internal.e12_worker_lease`, `pr_d_internal.e12_collector_key_registry`, `public.pr_d_capture_views_batch(jsonb)`, `public.pr_d_claim_e12_worker_lease(uuid,integer)`).
- En `youtube_shorts_log` no se encontraron las columnas E12 consultadas (`published_at`, `sync_captured_at`, `elapsed_seconds_e12`).
- Por lo tanto, la rama sandbox no está instalada en producción. No inferir compatibilidad del SQL con el esquema real ni desplegarla.

Security Advisor previamente observado: cinco tablas con RLS sin policies, cuatro funciones con search_path mutable, extensión vector en public y protección de contraseñas filtradas deshabilitada. Performance Advisor: una FK sin índice de cobertura, cuatro auth_rls_initplan, doce índices reportados no usados y veinte avisos de políticas permisivas múltiples. Estos avisos requieren análisis individual; no justifican borrar índices o cambiar políticas en bloque. RLS habilitado sin policies suele denegar acceso, no prueba exposición por sí solo.

## 6. Escalabilidad segura: ocho agentes o más

La expansión no debe consistir en multiplicar procesos que comparten credenciales y escriben libremente. La arquitectura objetivo debe tratar los ocho frentes como dominios de trabajo y, cuando se materialicen como agentes concurrentes, aplicar el mismo plano de control:

1. **Orquestador/controlador:** asigna tareas acotadas, presupuesto, deadline y política de reintentos.
2. **Executor aislado:** ejecuta solo herramientas/capacidades autorizadas; no decide su propia autoridad.
3. **Lease + fencing:** propiedad exclusiva temporal, heartbeat, token monotónico y rechazo de workers antiguos.
4. **Registro de evidencia append-only:** identidad del agente, tarea, inputs/outputs hash, tool calls, timestamps, resultados y causalidad.
5. **Procedencia criptográfica:** identidad de cada worker, firma/HMAC de payloads, rotación/revocación de claves; no equivale a verdad del origen externo.
6. **Idempotencia y límites:** claves por tarea/efecto, deduplicación, rate limits, cuotas y presupuestos globales por proveedor.
7. **Aislamiento de fallos:** colas separadas, circuit breakers, backpressure, cancelación segura y límites por agente.
8. **Auditor independiente:** verifica resultados contra evidencia que no controla el agente autor; no autoaprobación.

### Gates antes de pasar de 1 a 8+

- G0: contratos de tareas, capacidades y datos; clasificación de efectos READ/WRITE/EXTERNAL.
- G1: pruebas de concurrencia y fencing con N workers simultáneos; incluir workers pausados/revividos.
- G2: fault injection de red, DB y procesos; no duplicar efectos ante respuesta perdida.
- G3: presupuesto global y por agente; cuotas y límites comprobados.
- G4: aislamiento de secretos y credenciales de mínimo privilegio por worker/rol.
- G5: auditoría de evidencia, firmas, logs append-only y replay.
- G6: prueba de carga escalonada 1→2→4→8→16, primero sintética y luego con servicios controlados; medir throughput, latencia p50/p95/p99, errores, colisiones, costo y recuperación.
- G7: canary con capacidad de detener nuevas asignaciones, drenar leases y volver a versión previa.
- G8: promoción solo tras backup/restore ensayado, migraciones reconciliadas y rollback probado.

No aumentar concurrencia simplemente porque las pruebas unitarias pasan. La primera carga debe ser totalmente sintética, con proveedores falsos y límites explícitos.

## 7. Próximos pasos técnicos

1. Aislar los fixtures Python de los del E2E Deno; repetir CI sin alterar la semántica CAS.
2. Ampliar fault injection: timeout, 500, socket close antes/después de commit, respuesta perdida, retry y takeover.
3. Verificar expiración de lease en medio de batch y concurrencia de dos workers.
4. Reconciliar el conjunto completo de migraciones contra el catálogo real y el esquema productivo; solo lectura.
5. Diseñar pruebas reproducibles de instalación limpia, upgrade, replay, estado parcial, rollback y restore en clones descartables.
6. Modelar la capa API Gateway Supabase y su contrato `apikey` sin exponer ni copiar secretos reales.
7. Solicitar/revisar una segunda auditoría independiente de código, SQL, CI y amenazas.
8. Implementar observabilidad, métricas y evidencia de operación antes de probar 8+ workers.
9. No abrir PR, mergear, tocar `main`, activar Cron, llamar YouTube real ni desplegar hasta superar los gates correspondientes.

## 8. Seguridad y autorización

El usuario autorizó ampliar el trabajo técnico y manifestó que también autoriza producción, manteniendo la seguridad como prioridad máxima. Esa autorización habilita preparar y ejecutar etapas productivas solo cuando el destino y el cambio estén identificados y los gates estén demostrados; no elimina la obligación de backup verificable, restore ensayado, migraciones reconciliadas, revisión de permisos/RLS/grants, plan de rollback, observabilidad y ventana de cambio.

No se hicieron escrituras productivas, despliegues, cambios de secretos/permisos, llamadas reales a YouTube, activación de Cron ni merges en este corte. La rama permanece aislada.

## 9. Fuentes de evidencia

- CI #78: https://github.com/LeoJulieta/agente-runner/actions/runs/43452302068
- CI #79: https://github.com/LeoJulieta/agente-runner/actions/runs/43453183806
- CI #92: https://github.com/LeoJulieta/agente-runner/actions/runs/43540290764
- CI #94: https://github.com/LeoJulieta/agente-runner/actions/runs/43546440805
- Rama: https://github.com/LeoJulieta/agente-runner/tree/sandbox/e12-postgrest-contract-2026-11-13
- Informe anterior: AUDITORIAS/2026-11-13-e12-postgrest-contract.md


## Addendum de auditoría de migraciones — 2026-11-14

Una inspección adicional de `tests/e12/test_worker_lease_fencing.py` y `tests/e12/prepare_postgrest.py` detectó una limitación importante del setup CI: `support.bootstrap()` crea directamente un esquema base sintético, incluye una función CAS placeholder y filas de prueba; después el job aplica solo las tres migraciones E12 de lease, atestación y batch. El directorio contiene además dos migraciones E12 anteriores:
- `20261112160000_pr_d_sync_capture_provenance_candidate.sql`
- `20261112180000_pr_d_e12_worker_run_slot.sql`

Por tanto, el test actual **no demuestra una instalación limpia de las cinco migraciones E12 en secuencia** ni valida la migración del run-slot tal como está versionada. El worker E2E usa una función slot creada manualmente por `prepare_postgrest.py`, no la función desplegada desde la migración `20261112180000...`. La base descartable prueba contratos seleccionados y lógica posterior, no el grafo completo de instalación. Esto se agrega como gate prioritario: reconstruir un baseline realista desde migraciones versionadas y aplicar el conjunto E12 completo en orden, sin precrear objetos que las migraciones deben crear. Mantener una prueba aparte para upgrade desde un esquema preexistente. No promover hasta resolverlo.


## Addendum CI #95 — 2026-11-14

- Run #95 `43547004395`, SHA `1ee2b65dca82eb3054877d910f6f8a264af44a03`: **SUCCESS**.
- Job `lease-fencing`: SUCCESS; Deno unit suite, formatter and PostgreSQL 17 adversarial tests passed.
- Job `postgrest-contract`: SUCCESS; worker Deno E2E 1/1 and Python PostgREST RPC/role-boundary test 1/1 passed.
- La corrección aisló el test Python en filas propias IDs 101 y 102, evitando reutilizar las filas que captura el E2E Deno. No se debilitó la semántica CAS.
- Run: https://github.com/LeoJulieta/agente-runner/actions/runs/43547004395

Este SUCCESS valida el alcance actual de los tests, pero no cierra el hallazgo del addendum de migraciones: el bootstrap aún crea un esquema base sintético y no aplica las cinco migraciones E12 completas en orden. Ese es ahora el siguiente gate técnico prioritario.


## Addendum CI #98 — migraciones completas E12 — 2026-11-14

Run #98: `43547245149`, SHA `2b8591d935e0d96f259ce6d544ec8c41541165fd`.

El nuevo job `full-migration-chain` terminó **SUCCESS**. Logs confirman aplicación secuencial de las cinco migraciones:
1. `20261112160000_pr_d_sync_capture_provenance_candidate.sql`
2. `20261112180000_pr_d_e12_worker_run_slot.sql`
3. `20261112231203_e12_worker_lease_fencing.sql`
4. `20261112232558_e12_collector_attestation.sql`
5. `20261113090000_e12_capture_batch_cas.sql`

Comprobaciones pasadas:
- fila legacy de captura conservada sin alterar sus valores;
- schema privado `pr_d_internal` con owner esperado;
- RLS habilitado;
- `anon` sin EXECUTE y `service_role` con EXECUTE en RPC seleccionadas;
- run-slot versionado acepta una reclamación y rechaza el replay del mismo minuto;
- lease versionado permite reclamar una ejecución.

En la consulta de jobs, `postgrest-contract` también terminó SUCCESS y el paso de tests SQL/lease de `lease-fencing` terminó SUCCESS; ese job aún estaba en limpieza al momento de la lectura. No se declara el run completo SUCCESS hasta confirmar su conclusión final.

**Límite:** el baseline de esta prueba es sintético y recrea las columnas/roles legacy mínimas necesarias; no es clon de producción ni reproduce el historial completo de 37 migraciones de Supabase. Tampoco prueba upgrade desde cada versión histórica ni rollback/restore. El hallazgo de brecha de migración queda reducido, pero no cerrado en sentido productivo.


## Cierre de CI #98 — 2026-11-14

La ejecución completa #98 terminó **SUCCESS** (no solo sus jobs individuales): https://github.com/LeoJulieta/agente-runner/actions/runs/43547245149

Los tres jobs quedaron SUCCESS:
- `lease-fencing`
- `postgrest-contract`
- `full-migration-chain`

El nuevo job de migraciones aplicó las cinco migraciones E12 en orden sobre un baseline sintético y comprobó preservación de fila legacy, RLS/owner, privilegios, replay del run-slot y claim del lease. Esto cierra la omisión anterior de no ejecutar las cinco migraciones E12 juntas sobre un baseline limpio sintético. No cierra la brecha entre ese baseline y el historial/esquema real de producción ni valida las 37 migraciones históricas de Supabase.
