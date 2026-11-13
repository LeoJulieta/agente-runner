# E12 PostgREST contract — integración HTTP descartable

Fecha: 2026-11-13  
Estado: **VERIFICADO en PostgreSQL 17 + PostgREST 12.2.3 descartables**. No es un despliegue ni una integración productiva.

Rama: `sandbox/e12-postgrest-contract-2026-11-13`  
Base: batch CAS sandbox ya verificado.  
Commit de implementación: `4c57ee55068935fa541f52f031ae5ff2cb61b9ae`.

## CI

[Run #79 — SUCCESS](https://github.com/LeoJulieta/agente-runner/actions/runs/43453183806)

- Job `lease-fencing`: Deno **31/31**, PostgreSQL 17 descartable **13/13**.
- Job `postgrest-contract`: **1/1** prueba HTTP aprobada.
- Se aplicaron las tres migraciones en PostgreSQL local de CI.
- PostgREST 12.2.3 se ejecutó en un contenedor descartable conectado a PostgreSQL 17.
- La conexión DB de PostgREST usó el rol no-superusuario `authenticator`; el rol podía cambiar a `anon`, `authenticated` y `service_role`. El JWT de prueba llevaba claim `role=service_role`.

## Qué se comprobó por HTTP real

La prueba Python invocó endpoints PostgREST reales, no mocks:

1. Claim del lease mediante `POST /rpc/pr_d_claim_e12_worker_lease`.
2. Persistencia mediante `POST /rpc/pr_d_capture_views_batch`.
3. First-write-wins al repetir la misma fila con otro contador.
4. Release del lease y takeover por otro propietario.
5. Rechazo de la escritura con fencing token antiguo.
6. Escritura correcta del nuevo propietario con token incrementado.
7. Persistencia verificada de ambos outcomes consultando PostgreSQL.
8. Rechazo de ejecución de la RPC batch por el rol `anon`.

Resultado: **1 passed in 0.12s**.

## Límites de la prueba

- Es PostgREST real sobre PostgreSQL descartable, pero no es un stack Supabase completo.
- El test llama a las RPC por HTTP directamente; no ejecuta el worker Deno completo contra PostgREST.
- Para autenticar PostgREST se usó un JWT de prueba con `Authorization: Bearer`. No se probó el API Gateway de Supabase ni la validación de claves modernas `sb_secret_...` enviadas por `apikey`.
- La prueba de 500 candidatos sigue usando `fetch` interceptado: 34 solicitudes simuladas, no tráfico externo real.
- No se consultó YouTube real ni se usaron claves/secretos reales.
- No se tocó Supabase productivo, no se desplegó, no se activó Cron, no hubo PR/merge ni cambios en `main`.

## Próximos gates

1. Probar el worker Deno completo contra PostgREST descartable, con YouTube simulado y adaptador de autenticación explícito de test.
2. Probar la frontera API Gateway/clave moderna `sb_secret` en un entorno local que reproduzca esa capa, sin credenciales reales.
3. Inyectar timeouts, respuesta perdida, retry y expiración del lease durante un batch.
4. Auditoría independiente de un segundo revisor.
5. Reconciliar el grafo completo de migraciones antes de cualquier propuesta de promoción.

No promover esta rama sin autorización explícita posterior.
