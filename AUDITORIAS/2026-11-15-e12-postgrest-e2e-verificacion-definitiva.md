# E12 — verificación E2E definitiva en sandbox

**Fecha de inspección:** 2026-11-15 (America/Argentina/Ushuaia)  
**Repositorio:** `LeoJulieta/agente-runner`  
**Rama:** `sandbox/e12-postgrest-contract-2026-11-13`  
**Commit de código probado / HEAD al cerrar el CI:** `d5ff12fe153d4f0c6350c6b5fa4e8acb73e77578`  
**Commit inicial solicitado:** `f0853521b0c81a5d807896106de0d5586f45d77b`

<badge>VERIFICADO EN CI AISLADO — NO APROBADO PARA PRODUCCIÓN</badge>

## 1. Resultado definitivo

[GitHub Actions run #141 — 43627552314](https://github.com/LeoJulieta/agente-runner/actions/runs/43627552314)

- Evento: `push`
- Estado: `completed`
- Conclusión: `success`
- Inicio: 2026-11-14 18:36:33 UTC
- Fin: 2026-11-14 18:37:56 UTC
- SHA del run: `d5ff12fe153d4f0c6350c6b5fa4e8acb73e77578`
- Ref Git consultado: `refs/heads/sandbox/e12-postgrest-contract-2026-11-13` → mismo SHA.
- Comparación desde `f0853521b0c81a5d807896106de0d5586f45d77b`: 96 commits ahead, 0 behind.
- Check Runs API: 4 checks; los cuatro completados con `success`. No se encontraron status contexts legacy adicionales.

| Check | Resultado | Job |
|---|---|---|
| `postgrest-contract` | SUCCESS | [132546725979](https://github.com/LeoJulieta/agente-runner/actions/runs/43627552314/job/132546725979) |
| `lease-fencing` | SUCCESS | [132546725972](https://github.com/LeoJulieta/agente-runner/actions/runs/43627552314/job/132546725972) |
| `full-migration-chain` | SUCCESS | [132546726074](https://github.com/LeoJulieta/agente-runner/actions/runs/43627552314/job/132546726074) |
| `supabase-gateway-contract` | SUCCESS | [132546725813](https://github.com/LeoJulieta/agente-runner/actions/runs/43627552314/job/132546725813) |

## 2. E2E PostgREST: worker real + PostgreSQL descartable

Archivo: [worker_postgrest_e2e_test.ts](https://github.com/LeoJulieta/agente-runner/blob/d5ff12fe153d4f0c6350c6b5fa4e8acb73e77578/supabase/functions/e12-capture/worker_postgrest_e2e_test.ts)

Resultado en el job `postgrest-contract`: **1 passed / 0 failed**.

Evidencia del log:
- PostgreSQL 17 y PostgREST v12.2.3 se iniciaron en servicios descartables.
- Se ejecutó el worker Deno completo contra HTTP real de PostgREST.
- YouTube fue simulado; la prueba no hizo llamadas reales a YouTube.
- El worker capturó tres candidatos sintéticos y realizó el batch CAS.
- El replay de la solicitud ya confirmada devolvió `captured=false` para las tres filas: first-write-wins.
- El readback HTTP recuperó el registro, payload canónico y campos de atestación.
- La prueba comprobó identidad del video, contador observado, run ID, fencing token positivo, algoritmo Ed25519, key ID, digest SHA-256, firma Ed25519, HMAC y payload canónico de 12 campos.
- `verifyObservationAttestation(...)` validó offline la firma Ed25519 y el HMAC usando la clave pública y el secreto HMAC efímeros del test.

El mismo job ejecutó `tests/e12/test_postgrest_integration.py`: **1 passed**. La línea PostgreSQL `permission denied for function pr_d_capture_views_batch` que aparece en el log corresponde al intento negativo de ejecutar la RPC con el rol no autorizado; el test de frontera de rol pasó. No es un fallo del job.

## 3. E2E adicional: Gateway Supabase local real

Archivo: [worker_supabase_gateway_e2e_test.ts](https://github.com/LeoJulieta/agente-runner/blob/d5ff12fe153d4f0c6350c6b5fa4e8acb73e77578/supabase/functions/e12-capture/worker_supabase_gateway_e2e_test.ts)

Resultado en `supabase-gateway-contract`: **1 passed / 0 failed**.

Evidencia del log:
- Se creó y arrancó un proyecto Supabase local descartable.
- Las migraciones se aplicaron a su PostgreSQL local; la identidad Ed25519 y el HMAC fueron efímeros.
- La clave moderna `sb_secret_` se envió solo en `apikey`; el test comprobó que el worker no la envía como Bearer JWT.
- Contexto de la petición observado por el probe de CI: `current_user=service_role`, `session_user=authenticator`, claim `service_role`, `claims_present=true`, `internal_schema_usage=true`.
- ACL efectiva registrada: `service_role_schema_usage=true`, `service_role_internal_slot_execute=true`, `service_role_public_slot_execute=true`, `authenticator_can_set_service_role=true`.
- El probe de candidatos devolvió HTTP 200 y una fila sintética.
- Resultado del worker: `candidates=1`, `uniqueCandidates=1`, `slotClaimed=true`, `leaseClaimed=true`, `eligible=1`, `captured=1`, `casLost=0`, `nonEligible=0`.
- El replay mientras el lease seguía activo y el replay posterior preservaron first-write-wins.
- El readback HTTP recuperó payload canónico, SHA-256, firma Ed25519 y HMAC; `verifyObservationAttestation(...)` los validó offline.
- La clave publishable/anon no pudo ejecutar la RPC protegida (respuesta dentro de 401/403/404, según la aserción).

El probe de contexto es fixture de diagnóstico del job local; no forma parte de las migraciones productivas.

## 4. Cobertura complementaria

- Worker, collector, lease y provenance Deno: **32 passed / 0 failed**.
- PostgreSQL lease/fencing adversarial: **14 passed / 0 failed**.
- Cadena de cinco migraciones aplicada en orden sobre un baseline legado sintético limpio: PASS.
- Se verificó la conversión del fixture de `views_primeras_3h` de integer a `numeric(20,0)` sin alterar el valor legado; preservación de políticas, grants, índices y trigger del baseline; ownership/RLS y privilegios de RPC; rechazo de replay de slot.
- Los errores SQL intencionales del job de lease/fencing (casts inválidos, item/tamaño inválido, mutación/borrado de datos capturados y acceso directo denegado al registro de claves) corresponden a pruebas negativas adversariales; el job terminó `success`.

## 5. Fallos intermedios y resolución

- El run #85 sobre el commit inicial `f0853521...` falló; la prueba PostgREST se corrigió en commits posteriores y quedó verde en el run #141.
- Una ejecución Gateway anterior falló por ACL del esquema interno (`permission denied for schema pr_d_internal`). El run final registra los privilegios efectivos requeridos como verdaderos, sin conceder `USAGE` a `anon` o `authenticated`.
- El run [#140 / 43627233582](https://github.com/LeoJulieta/agente-runner/actions/runs/43627233582) falló por interferencia del fixture: `full_migration_chain.py` reclamó el mismo bucket de minuto que luego necesitaba el worker Gateway. El worker respondió `skippedDuplicateInvocation=true`; no era un fallo de firma ni de autenticación.
- El commit final de código [d5ff12fe](https://github.com/LeoJulieta/agente-runner/commit/d5ff12fe153d4f0c6350c6b5fa4e8acb73e77578) cambió el fixture de slot a un bucket de minuto anterior y liberó explícitamente el lease sintético. El run #141 posterior pasó los cuatro checks.

## 6. Logs y conservación de evidencia

Los logs completos de los cuatro jobs se consultaron durante esta revisión y permanecen vinculados al [run #141](https://github.com/LeoJulieta/agente-runner/actions/runs/43627552314). GitHub no devolvió artifacts separados para ese run. Este informe conserva SHA, IDs de jobs, enlaces y resultados relevantes; no copia secretos ni valores de credenciales.

Advertencias no bloqueantes observadas:
- avisos de deprecación de Node.js 20 en `actions/checkout@v4` y `actions/setup-python@v5` al ejecutarse bajo Node.js 24;
- aviso de deprecación del módulo `punycode`.

## 7. Límites y bloqueos para producción

Este resultado **no autoriza ni demuestra readiness productiva**:
1. PostgreSQL y Supabase fueron locales/descartables; no se consultó ni escribió el proyecto Supabase productivo.
2. YouTube fue simulado; no se utilizaron claves ni secretos reales.
3. Las claves Ed25519 y HMAC fueron efímeras, creadas solo para CI.
4. La cadena sintética reproduce explícitamente una política `anon_read` y un grant `TRUNCATE` a `anon` del baseline legado para mantener visible ese riesgo. El PASS no avala esos permisos: hace falta una auditoría read-only de roles, ACL, grants y RLS del proyecto productivo.
5. No se verificaron drift ni compatibilidad contra el esquema productivo real, ni backup, restauración, recuperación o rollback.
6. No hubo deploy, Cron/Vault, cambios de permisos productivos, PR, merge ni cambios en `main`.

**Puerta de salida:** antes de cualquier cambio productivo se requiere revisión específica del esquema y permisos reales, compatibilidad, respaldo restaurable, procedimiento de recuperación y plan de reversión. Hasta entonces, E12 queda **VERIFICADO EN SANDBOX / BLOQUEADO PARA PRODUCCIÓN**.
