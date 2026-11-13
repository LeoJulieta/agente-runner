# E12 — auditoría adicional adversarial y baseline Supabase (solo lectura)

Fecha: 2026-11-13
Alcance: revisión de código, CI y estado productivo de Supabase. Sin escrituras ni cambios de configuración.

## Dictamen ejecutivo

La integración PostgREST descartable anterior está correctamente aislada y su CI #79 pasó. Todavía no existe evidencia suficiente para declarar integrado el worker Deno completo contra PostgREST ni para promover E12. La base Supabase productiva no tiene instalados los objetos E12 revisados en esta auditoría.

## 1. GitHub sandbox y CI

- Rama: `sandbox/e12-postgrest-contract-2026-11-13`.
- Último commit documental observado: `24a4cd6f429124b71cd114a3b3d80519cac6e037`.
- CI #79: https://github.com/LeoJulieta/agente-runner/actions/runs/43453183806
- Jobs `lease-fencing` y `postgrest-contract`: completed / success.
- El compare con la base `7d5dc7bce883c9b457e73dc0ec9357b5a4cc14a4` mostró 2 commits ahead, 0 behind y 4 archivos de integración/documentación modificados.

## 2. Hallazgo de precisión criptográfica

El test Python HTTP `tests/e12/test_postgrest_integration.py` usa una firma constante de relleno (`"A" * 86 + "=="`) y una clave pública SPKI artificial. El SQL de attestation verifica digest, registry y HMAC; almacena la firma Ed25519 pero declara explícitamente que PostgreSQL no verifica Ed25519. Esto es consistente con la arquitectura documentada: el worker debe verificar/fabricar la attestation y un auditor puede verificarla offline.

Por lo tanto:
- El test HTTP prueba HMAC, binding del payload, lease/fencing, first-write-wins y permisos.
- No prueba una firma Ed25519 válida en el recorrido HTTP.
- Los tests unitarios Deno del worker sí generan una key pair y verifican la attestation, pero todavía no conectan ese worker completo al PostgREST real.
- No se debe describir el contrato HTTP actual como verificación criptográfica Ed25519 end-to-end.

Avance posterior de esta auditoría: se añadió `supabase/functions/e12-capture/worker_postgrest_e2e_test.ts`, se actualizó `tests/e12/prepare_postgrest.py` para generar y registrar una key pair Ed25519/HMAC efímera únicamente en PostgreSQL descartable, y se añadió al workflow el paso Deno que llama al worker real con YouTube simulado y JWT local de PostgREST. La fixture de idempotency slot es un stub SQL local de test. El test además hace readback HTTP de la fila y vuelve a verificar offline la firma Ed25519 y el HMAC persistidos. Estos cambios están en commits `c34deb71fbf80735d9c9b3aaa1f435839b17245f`, `a13aceccaedb379f5c492376360d002cd455f92a`, `ccba4194107ea0837987bf9c590e89cd1b3d4c07`, `fe3a7cb03d03ff0309d6524da5e7dba8f316007b`, `4cb000c04ecd411d20413c486b52d493784bc877` y `f0853521b0c81a5d807896106de0d5586f45d77b`. Durante la revisión estática adicional detecté y corregí un defecto del adaptador de laboratorio: el worker agrega el prefijo Supabase `/rest/v1`, mientras que PostgREST standalone expone el API en `/`. El test ahora elimina ese prefijo al adaptar las solicitudes hacia el servidor descartable, y el readback consulta el root de PostgREST. Correcciones en commits `57643c78d8bbbbbdcd9e42339ea1a27796075026`, `3c73555f130cae6e51457c7e207363c723df825d` y `18b0245f28c77def7784d518881b47d7c5db9c9f`. **Estado: IMPLEMENTADO EN RAMA, NO VERIFICADO**; el conector no expuso runs ni checks asociados al commit consultado, por lo que todavía no hay logs que permitan declarar el test aprobado. No afirmar E2E aprobado hasta obtener CI verde y logs.

## 3. Baseline Supabase productivo — solo lectura

Proyecto observado: `btvfhopootvkqnpbctsq`, estado `ACTIVE_HEALTHY`, PostgreSQL 17.6.

### 3.1 E12 no está instalado en producción

La lista de migraciones productivas termina en `20260906020435 create_lab_results`; no contiene las migraciones E12 candidatas de noviembre.

Una consulta SELECT de catálogo confirmó ausencia de:
- `pr_d_internal.e12_worker_lease`
- `pr_d_internal.e12_collector_key_registry`
- `public.pr_d_capture_views_batch(jsonb)`
- `public.pr_d_claim_e12_worker_lease(uuid,integer)`

La inspección de `information_schema.columns` de `public.youtube_shorts_log` tampoco encontró las columnas E12 `published_at`, `sync_captured_at` ni `elapsed_seconds_e12` en el esquema productivo consultado.

**Gate obligatorio:** no desplegar ni activar el worker sobre este proyecto hasta reconciliar y probar todas las migraciones predecesoras y el esquema requerido. Este hallazgo es evidencia de ausencia actual, no una autorización para instalarlo.

### 3.2 Supabase Security Advisors

Lectura del advisory de seguridad (observado 2026-11-13):
- 5 tablas con RLS habilitado pero sin políticas: `fuentes_rss`, `lab_results`, `pain_points`, `paso1_candidatos_pendientes`, `workflow_logs`.
- 4 funciones con `search_path` mutable: `update_updated_at`, `buscar_tendencias_similares`, `recomputar_time_patterns`, `trg_lab_results_proteccion`.
- Extensión `vector` instalada en schema `public`.
- Protección de contraseñas filtradas de Auth deshabilitada.

RLS activo sin políticas suele resultar en denegación por defecto para roles sujetos a RLS; no se clasifica automáticamente como exposición. Hay que inspeccionar grants, roles y políticas antes de emitir un veredicto de acceso. No se modificó ninguna política ni configuración.

### 3.3 Supabase Performance Advisors

- 1 FK sin índice de cobertura: `affiliate_clicks.programa_id`.
- 4 avisos `auth_rls_initplan`.
- 12 índices reportados como no utilizados.
- 20 avisos de políticas permisivas múltiples.

Los índices no utilizados no deben borrarse sin analizar ventanas de observación, consultas y costos de escritura. Los avisos de políticas múltiples requieren revisar su semántica antes de consolidar; no son por sí solos una prueba de bypass.

### 3.4 Health

El advisory de salud no devolvió hallazgos en la consulta realizada.

## 4. Matriz de siguientes pruebas

1. Ejecutar y corregir hasta verde el nuevo test Worker Deno real → PostgREST real → PostgreSQL 17 descartable, con YouTube completamente simulado.
2. Claves Ed25519/HMAC efímeras generadas en CI y registro solo en DB descartable.
3. Pérdida de respuesta después del commit y retry: confirmar first-write-wins y ausencia de doble mutación.
4. HTTP 500, timeout, conexión cortada antes del commit y conexión cortada después del commit.
5. Expiración de lease durante colección/batch, takeover y rechazo de token viejo.
6. Respuesta batch duplicada, truncada, reordenada o con row_id incorrecto: el worker debe fallar cerrado.
7. Verificar que el workflow siga restringido a ramas sandbox y permisos mínimos.
8. Reconciliar migraciones versionadas, SQL operativo, prerequisitos y orden desde instalación limpia y upgrade.
9. Auditoría independiente por segundo revisor; hasta entonces, la revisión adversarial de esta sesión no debe etiquetarse como independiente.

## 5. Límites y no-acciones

- No se ejecutaron escrituras en Supabase productivo.
- No se aplicaron migraciones ni se cambiaron políticas, claves, Auth, extensiones o configuración.
- No hubo YouTube real, secretos reales, despliegue, Cron, PR, merge ni cambios en `main`.
- El proyecto productivo se inspeccionó exclusivamente mediante listados, advisors y consultas SELECT de catálogo.
