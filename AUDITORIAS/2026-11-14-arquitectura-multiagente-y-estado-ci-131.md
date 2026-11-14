# Arquitectura multiagente, recuperación histórica y estado E12 — 2026-11-14

**Fecha de corte:** 2026-11-14 (UTC)  
**Repositorio:** `LeoJulieta/agente-runner`  
**Rama:** `sandbox/e12-postgrest-contract-2026-11-13`  
**Commit CI #131:** `9880e2a5d59fde7ec3f55f88394e84c47deade97`  
**Propósito:** consolidar decisiones históricas de agentes, separar diseño de implementación y documentar evidencia reciente.

## 1. Dictamen ejecutivo

La estrategia multiagente es anterior a esta iteración técnica. Desde octubre se estableció la separación implementador/auditor; el 6 de noviembre se formalizó un contrato multiagente y una auditoría adversarial de Qwen. La arquitectura evolucionó documentalmente hasta un borrador v0.5, pero **no debe confundirse el contrato diseñado con una flota de agentes ya implementada o ejecutándose**.

En paralelo, E12 ya dispone de batch CAS, lease/fencing, atestación criptográfica, pruebas HTTP PostgREST y una prueba contra el Gateway real de Supabase local. El CI #131 confirma cuatro jobs: tres SUCCESS y uno FAILURE. El bloqueo actual está localizado en el acceso al esquema interno desde la RPC invocada a través del Gateway.

No hay promoción productiva demostrada. La inspección read-only previa encontró que E12 no está instalado en el proyecto Supabase productivo. El usuario amplió su autorización general para etapas productivas, condicionada a gates de seguridad, compatibilidad, backup/restore y rollback.

## 2. Recuperación histórica del diseño multiagente

### 2.1 Octubre: separación implementador/auditor

El 16-10-2026 se formuló el principio operativo: Qwen actúa como auditor independiente y Coder como implementador. Regla: **un agente implementa, otro audita, las pruebas verifican y el usuario autoriza**.

Se describió una arquitectura por planos P-producción / L-laboratorio / D-descubrimiento / E-evolución. GitHub aporta trazabilidad, y los efectos externos requieren autorización humana. Este antecedente establece la separación de funciones, no demuestra que una infraestructura multiagente completa estuviera desplegada.

### 2.2 6 de noviembre: Contrato Fundacional v0.1 y auditoría adversarial

Qwen auditó documentalmente el Contrato Fundacional v0.1 e identificó diez riesgos P1–P10. El dictamen fue **REQUIERE ENMIENDAS IMPORTANTES**.

Clasificación recuperada:
- C1–C3: críticos.
- A1–A4: altos.
- M1–M4: medios.
- B1–B3: bajos.

La auditoría señaló insuficiencias en T01–T16 y propuso T17–T24, además de ampliar T06/T14. Los temas cubiertos incluyen:
- independencia real del auditor y acceso al inventario completo;
- integridad, procedencia y completitud de evidencia;
- fuentes críticas y corroboración;
- concurrencia, aislamiento y locks con expiración;
- ciclos/dependencias y reintentos;
- scopes de autorización;
- recuperación, atomicidad y registro persistente;
- límites preventivos de presupuesto/costo y circuit breaker.

El auditor debía poder solicitar pruebas adicionales y consultar artefactos en modo lectura, pero no modificar el resultado que auditaba. El desarrollador no podía autoaprobarse.

### 2.3 Evolución v0.2–v0.5

La conversación recuperada registra cuatro rondas de auditoría documental. v0.2 incorporó correcciones y nuevas pruebas; una revisión posterior propuso T27–T43 y otra detectó requisitos todavía abiertos: enforcement independiente, autenticación/autorizaciones, evidencia completa, rollback/frescura, secretos, prompt injection, costos concurrentes, split-brain, proveedores y cobertura verificable.

El borrador v0.5 quedó descrito como T01–T58 y H01–H37, con:
- evidencia DECLARADO / OBSERVADO / CORROBORADO / VERIFICADO;
- niveles de evidencia A–D;
- controlador de autorizaciones;
- executor controlado;
- registro independiente;
- calibración del auditor;
- manejo adversarial de prompt injection;
- prohibición de auto-validación y de aprobaciones condicionales.

**Estado:** diseño/especificación documental. No afirmar que v0.5 se implementó o desplegó como runtime multiagente.

### 2.4 Roles fundacionales ya definidos

La arquitectura histórica distingue:
1. Supervisor humano: autoriza operaciones sensibles.
2. Coordinador: descompone, asigna, prioriza y controla dependencias.
3. Investigador: reúne evidencia y formula hipótesis.
4. Desarrollador/implementador: modifica únicamente dentro del scope.
5. Auditor independiente: verifica desde evidencia y no altera el artefacto auditado.
6. Recuperador: gestiona fallos, reintentos acotados y reconciliación.
7. Registro persistente: conserva estado, evidencias, hashes y trazabilidad.

Se propusieron inicialmente máximo tres reintentos, mínimo privilegio, límites por tarea/objetivo/misión y reservas temporales de recursos. El registro persistente es un componente de control, no un agente con autoridad para aprobar.

## 3. Ocho frentes técnicos: dominios de trabajo, no agentes ya activos

La planificación técnica posterior separó ocho frentes:
1. Lease, concurrencia y fencing.
2. Migraciones y reconstrucción reproducible de base.
3. Procedencia criptográfica de observaciones.
4. Integración y endurecimiento E12.
5. Rendimiento, límites y cuotas.
6. Seguridad ofensiva y pruebas adversariales.
7. Auditoría estadística independiente.
8. Observabilidad, trazabilidad y documentación.

Estos ocho frentes no equivalen a ocho agentes autónomos ejecutándose. Son dominios que pueden asignarse a especialistas aislados bajo un plano de control común.

## 4. Propuesta de materialización en 8+ agentes especializados

Propuesta de asignación, todavía **DISEÑADA / NO IMPLEMENTADA**:

| Agente especialista | Alcance adversarial | Entregable exigido |
|---|---|---|
| A1 — Lease/fencing | carreras, expiración, takeover, worker zombi | pruebas concurrentes y regresiones |
| A2 — DB/migraciones | cadena completa, grants, RLS, owners, rollback | matriz de migraciones y catálogo efectivo |
| A3 — Criptografía/procedencia | canonicalización, HMAC, Ed25519, rotación/revocación | vectores positivos/negativos y verificación independiente |
| A4 — Gateway/API | API keys, claims, roles, RPC y límites HTTP | E2E local/hosted separado y pruebas de denegación |
| A5 — Aprobaciones/identidad | bypass anon, identidad humana, autoaprobación, CAS | pruebas de abuso y contrato de autorización |
| A6 — CI/supply chain | permisos de workflows, secretos, checkout/ref, acciones externas | inventario de capacidades y riesgos de pipeline |
| A7 — Fault injection/carga | timeout, 500, pérdida de respuesta, duplicados, cuotas | matriz de fallos y métricas escalonadas |
| A8 — Auditor/integrador independiente | contradice hallazgos, busca omisiones y verifica cobertura | dictamen independiente con evidencia reproducible |

El coordinador asigna tareas y presupuestos, pero no puede aprobar sus propias conclusiones. El implementador trabaja en ramas/entornos aislados. Un auditor distinto debe revisar cada entregable; el agente A8 realiza una segunda pasada transversal y no sustituye revisiones por dominio. El usuario conserva autorización de efectos externos y promociones.

### 4.1 Controles obligatorios por agente

- Identidad individual y credenciales no compartidas.
- Capacidades explícitas READ / WRITE_SANDBOX / EXTERNAL, denegadas por defecto.
- No distribuir `service_role` ni secretos globales a todos los agentes.
- Lease/fencing para tareas exclusivas; idempotencia para efectos.
- Presupuesto, deadline, cuota, límite de concurrencia y reintentos por agente y globales.
- Registro append-only de tarea, inputs, outputs, hashes, tool calls y decisión de auditoría.
- Evidencia independiente: el autor no puede crear la única prueba de su propia corrección.
- Prompt injection tratada como dato no confiable, nunca como instrucción para ampliar autoridad.
- Fallo cerrado ante identidad, scope, evidencia o aprobación ambiguos.

### 4.2 Escalado gradual

No pasar directamente a 8 agentes con permisos de escritura. Primero validar un agente lector aislado, luego 2, 4, 8 y 16 bajo carga sintética. Medir throughput, latencia p50/p95/p99, errores, colisiones, coste, consumo de cuotas, recuperación y trazabilidad. La primera fase no debe llamar YouTube ni escribir en Supabase productivo.

## 5. E12 — evidencia técnica consolidada

### 5.1 Batch CAS verificado

Rama previa `sandbox/e12-batch-cas-2026-11-13`:
- RPC `public.pr_d_capture_views_batch(jsonb)`, límite 1–50.
- Conserva validación canónica, digest, clave activa, HMAC, identidad, lease/fencing y first-write-wins.
- Tests Deno 31/31 y PostgreSQL 17 13/13 en CI #78.
- Carga sintética: 500 candidatos, 10 consultas YouTube simuladas, 10 RPC batch, 34 solicitudes HTTP interceptadas y 105 ms. No es tráfico externo ni benchmark de YouTube.
- Commit: `6f21b8195784c0fce2c6282b1b78dd8b0cf7f816`.

### 5.2 PostgREST standalone verificado

- PostgreSQL 17 descartable + PostgREST 12.2.3.
- HTTP verifica claim lease, batch CAS, first-write-wins, release/takeover, incremento de fencing, rechazo de token obsoleto, escritura vigente, readback y denegación a anon.
- CI #79 run `43453183806`: SUCCESS.
- Esto no es Supabase API Gateway.

### 5.3 Worker Deno completo contra PostgREST

- Ejecuta `handleE12Capture` real con YouTube simulado, claves efímeras y persistencia HTTP.
- Verifica offline Ed25519/HMAC y replay idempotente.
- E2E Deno pasó en ejecuciones posteriores; tests auxiliares Python usan firma Ed25519 placeholder estructural, no deben confundirse con la verificación criptográfica real del test Deno.

### 5.4 Cadena completa de migraciones y Gateway local

CI #131, run `43614553615`, SHA `9880e2a5d59fde7ec3f55f88394e84c47deade97`:
- `full-migration-chain`: SUCCESS.
- `lease-fencing`: SUCCESS.
- `postgrest-contract`: SUCCESS.
- `supabase-gateway-contract`: FAILURE.

El job Gateway levantó Supabase local, exportó endpoints/keys modernas, aplicó las cinco migraciones E12, registró identidad efímera y candidato, y ejecutó el worker Deno completo contra el API Gateway local real.

Error exacto capturado:
`POST /rest/v1/rpc/pr_d_claim_e12_worker_slot -> 403`
`code=42501`
`permission denied for schema pr_d_internal`

Esto demuestra que el flujo de autenticación llegó a PostgreSQL y que la denegación actual es de privilegio efectivo sobre el esquema privado. No demuestra todavía qué rol efectivo ni qué ruta de privilegios produce la denegación. No añadir grants amplios por intuición.

Siguiente diagnóstico:
1. capturar `current_user`, `session_user` y claims efectivos sin secretos;
2. comprobar `has_schema_privilege` y `has_function_privilege` para roles pertinentes;
3. verificar owner, `SECURITY DEFINER`, `search_path` y cadena de invocación de wrapper público/interno;
4. comparar configuración local del Gateway y roles después de migraciones;
5. corregir únicamente el permiso/configuración mínimo y añadir regresión de denegación a anon/authenticated.

Run: https://github.com/LeoJulieta/agente-runner/actions/runs/43614553615

## 6. Otros gates de seguridad conocidos

### 6.1 Aprobaciones humanas

La auditoría del repo privado `agente-autonomo` encontró:
- `pending_approvals` expuesta a UPDATE anónimo mediante política permisiva;
- dashboard que usaba Anon Public Key sin autenticación Supabase Auth;
- riesgo de XSS por interpolación de datos externos en `innerHTML`;
- flujo que marcaba `resolved_at` antes de completar la acción, con riesgo de pérdida/duplicación;
- `notify-approval` desplegada históricamente con `--no-verify-jwt` y sin autenticación propia visible.

No se probó explotación efectiva. No aplicar contención a producción sin compatibilidad de consumidores y reemplazo seguro. Antes de agentes con escritura: login real, rol revisor, RPC CAS, identidad humana no falsificable, audit log, no autoaprobación y UI con APIs seguras como `textContent`.

### 6.2 Estado productivo E12

La auditoría read-only previa del proyecto Supabase productivo encontró que las funciones/tablas E12 consultadas no estaban instaladas y que el historial productivo observado era anterior a estas migraciones. E12 sandbox no debe tratarse como desplegado. La cadena sintética no es clon completo de producción ni prueba hosted Gateway.

## 7. Autorizaciones y límites vigentes

El usuario autorizó:
- cambios técnicos en ramas sandbox aisladas de `agente-runner`;
- tests automatizados y PostgreSQL descartable;
- regresiones reproducibles, auditoría y documentación;
- preparar y eventualmente ejecutar etapas productivas cuando los gates estén demostrados.

La autorización productiva general no elimina gates. Se requiere destino exacto, reconciliación de migraciones, respaldo y restore probado, análisis de permisos/impacto, rollback, monitorización y canary.

No se autoriza por defecto:
- merge, PR o modificación de `main`;
- distribuir secretos o `service_role` a agentes;
- activar Cron, ejecutar agentes externos, consumir cuotas cloud;
- llamadas reales a YouTube o publicación;
- escrituras productivas mientras el contrato y el Gateway no estén verificados.

## 8. Próximos pasos ordenados

1. Diagnosticar el 403 Gateway con roles/claims/privilegios efectivos.
2. Corregir el permiso mínimo en sandbox y repetir CI completo.
3. Implementar fault injection de timeouts, 500, desconexión pre/post commit, respuesta perdida, retries, expiración y takeover.
4. Completar auditoría de aprobaciones/XSS en rama aislada, incluyendo todos los consumidores.
5. Formalizar contrato v0.5 como requisitos verificables antes de implementar el runtime multiagente.
6. Preparar agentes especialistas con identidad/capacidades separadas y un auditor transversal.
7. Ejecutar carga sintética gradual 1→2→4→8→16.
8. Reconciliar esquema productivo, backup/restore y rollback antes de cualquier promoción.

## 9. Referencias

- Batch CAS: https://github.com/LeoJulieta/agente-runner/blob/sandbox/e12-postgrest-contract-2026-11-13/AUDITORIAS/2026-11-13-e12-batch-cas-sandbox.md
- PostgREST: https://github.com/LeoJulieta/agente-runner/blob/sandbox/e12-postgrest-contract-2026-11-13/AUDITORIAS/2026-11-13-e12-postgrest-contract.md
- Estado integral anterior: https://github.com/LeoJulieta/agente-runner/blob/sandbox/e12-postgrest-contract-2026-11-13/AUDITORIAS/2026-11-14-e12-estado-integral-y-escalabilidad.md
- Inventario central de aprobaciones: https://github.com/LeoJulieta/infraestructura-ia-inventario/blob/docs/paquete-despliegue-controlado-aprobaciones-2026-11-11/PLANES/PAQUETE_DESPLIEGUE_CONTROLADO_APROBACIONES.md
- CI #131: https://github.com/LeoJulieta/agente-runner/actions/runs/43614553615

**Clasificación final:** batch CAS = VERIFICADO en CI; PostgREST HTTP = VERIFICADO en CI; cinco migraciones = VERIFICADO sobre baseline sintético; Gateway Supabase local = IMPLEMENTADO, EJECUTADO y FALLIDO por privilegio de schema; runtime 8+ agentes = DISEÑADO, NO IMPLEMENTADO; producción E12 = NO INSTALADO según última auditoría read-only.
