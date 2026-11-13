# E12 batch CAS — sandbox técnico

Fecha: 2026-11-13  
Rama: `sandbox/e12-batch-cas-2026-11-13`  
Base: `a9558516c7f39de0532672dd95e2a2170f58d8dc`  
Estado: **IMPLEMENTADO_SANDBOX y VERIFICADO por GitHub Actions + PostgreSQL 17 descartable**. No desplegado ni integrado a producción.

Commit final de esta rama: `6f21b8195784c0fce2c6282b1b78dd8b0cf7f816`.

CI final: [run #78 — SUCCESS](https://github.com/LeoJulieta/agente-runner/actions/runs/43452302068). Deno: **31 passed, 0 failed**. PostgreSQL 17: **13 passed**.

## Objetivo

Reducir las llamadas HTTP de persistencia y las renovaciones de lease redundantes para el ciclo E12, sin reemplazar el CAS por observación ni relajar sus garantías.

## Diseño

### RPC de lote

Se agrega `public.pr_d_capture_views_batch(jsonb)`, con límite de 1 a 50 elementos. Cada elemento debe incluir los 18 campos de la RPC CAS actual.

La función interna:

1. exige claim JWT `service_role`;
2. exige un array JSON de 1–50 objetos y todos los campos obligatorios;
3. convierte explícitamente cada campo al tipo SQL esperado;
4. llama a `pr_d_internal.pr_d_capture_views_once(...)` para cada elemento;
5. devuelve resultados ordenados con `row_id` y `captured`.

No implementa una escritura masiva alternativa. Cada fila vuelve a pasar por la verificación actual de payload canónico, SHA-256, clave activa, HMAC, identidad, lease/fencing y first-write-wins.

### Semántica transaccional

- `captured=true`: la observación ganó el CAS.
- `captured=false`: conflicto esperado, fila ya capturada, lease/fencing no vigente o atestación inválida; no se sobrescribe la fila.
- Una excepción SQL (por ejemplo, campo ausente o tipo inválido) aborta la RPC completa y PostgreSQL revierte todas las escrituras de esa llamada.
- Una respuesta mixta true/false es válida: los conflictos por fila no abortan otras capturas válidas.
- Los duplicados dentro del lote se procesan en orden; el primero puede ganar y los siguientes pierden por first-write-wins.

### Renovación del lease

El worker renueva antes de cada lote de consulta a YouTube, no antes de cada fila. Después de recoger y firmar las observaciones, renueva de nuevo solo si el tiempo desde la última renovación alcanzó el margen de seguridad (`TTL - 30 s`). El TTL por defecto sigue siendo 90 segundos.

Cada lote de consulta y cada RPC de persistencia continúan acotados por timeouts. El CAS SQL vuelve a verificar el lease y el fencing token; el worker falla cerrado si pierde el lease.

## Modelo de solicitudes para 500 candidatos

Con 500 candidatos únicos, 10 lotes de YouTube de hasta 50, todos elegibles, sin renovación adicional por superar el margen de seguridad:

| Operación | Solicitudes |
|---|---:|
| Claim del slot | 1 |
| Claim del lease | 1 |
| Lectura de candidatos | 1 |
| Renovación del lease (una por lote) | 10 |
| YouTube (una por lote) | 10 |
| CAS por lote | 10 |
| Release del lease | 1 |
| **Total estimado** | **34** |

En CI, una prueba Deno con 500 candidatos sintéticos contó **34 solicitudes HTTP simuladas** (10 renovaciones, 10 consultas a YouTube simuladas y 10 CAS batch), en 105 ms de ejecución de esa prueba. Esto verifica el conteo y el flujo con fetch interceptado; no es una medición de red real ni de latencia externa.

## Pruebas añadidas

- Worker: dos observaciones elegibles comparten una sola RPC batch, con orden, run ID y fencing token verificados.
- Worker: 500 candidatos sintéticos recorren 10 lotes de origen y 10 lotes CAS; el fetch interceptado cuenta 34 solicitudes.
- PostgreSQL: dos RPC batch concurrentes para la misma fila producen exactamente un ganador.
- PostgreSQL 17 descartable: CAS por fila dentro del lote, first-write-wins con duplicados, HMAC incorrecto por elemento, fencing obsoleto, rollback de toda la RPC ante error de conversión y límites de tamaño/tipo.
- CI compara byte a byte `supabase/ops/e12_capture_batch_cas.sql` con la migración versionada y aplica las migraciones en PostgreSQL descartable.

## Límites y exclusiones

- No prueba todavía una instancia Supabase/PostgREST completa.
- No usa YouTube real, claves reales, Supabase productivo ni secretos reales.
- No aplica migraciones en ningún proyecto remoto, no despliega funciones ni activa Cron.
- No crea PR, no modifica `main` y no integra esta rama a la rama E12 anterior.
- La firma Ed25519 sigue verificándose en el worker; PostgreSQL verifica HMAC y la vinculación del payload, sin afirmar verificar Ed25519.

## Resultado y revisión adversarial ejecutada

- CI final #78: SUCCESS; Deno 31/31 y PostgreSQL 17 13/13.
- La primera ejecución detectó expectativas Deno antiguas; se corrigieron los tests para el nuevo endpoint.
- La segunda ejecución detectó contaminación de estado entre tests PostgreSQL; se agregó aislamiento explícito por test y se hizo autocontenido el test de expiración de lease.
- La ejecución final pasó con fixtures aislados, migraciones `ops`/versionadas comparadas byte a byte y PostgreSQL 17 descartable.
- Se verificaron concurrencia de dos RPC batch sobre la misma fila (un solo ganador), duplicados, HMAC inválido, fencing obsoleto, error de conversión con rollback, campos obligatorios y límites de 1–50 elementos.
- El worker valida cantidad, orden e identidad de cada respuesta del batch antes de contabilizar resultados.

La revisión realizada hasta aquí es una revisión técnica adversarial de código y pruebas dentro de esta sesión; no se presenta como auditoría independiente de un segundo revisor.

## Criterio de aceptación

La optimización queda **verificada en sandbox** para los escenarios cubiertos por CI. Sigue pendiente una instancia Supabase/PostgREST completamente descartable, una medición HTTP end-to-end y una auditoría independiente externa. No promover sin autorización adicional.
