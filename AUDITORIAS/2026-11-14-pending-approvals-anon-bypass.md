# Auditoría crítica — bypass anónimo del flujo de aprobaciones

Fecha: 2026-11-14  
Proyecto Supabase: btvfhopootvkqnpbctsq  
Estado: solo lectura. No se modificó ni aprobó/rechazó ninguna solicitud.

## 1. Hallazgo confirmado

La tabla public.pending_approvals tiene RLS habilitado, pero las policies son:

- SELECT para anon con USING (true).
- UPDATE para anon con USING (true) y sin WITH CHECK explícito (PostgreSQL aplica la expresión USING como check por defecto).

El rol anon tiene grants de UPDATE y SELECT a nivel de todas las columnas. La consulta de role_column_grants confirma UPDATE sobre id, type, title, reasoning, payload, confidence, status, created_at y resolved_at.

La constraint status_check solo limita el valor a pending, approved o rejected; no impide que anon cambie pending → approved/rejected. No hay triggers en la tabla que validen actor, transición o columnas modificadas.

Prueba de solo lectura:
- BEGIN; SET LOCAL ROLE anon; SELECT count(*), count(*) FILTER (WHERE status='pending'); ROLLBACK.
- Resultado: anon ve 61 filas, incluidas las 2 actualmente pending.
- No se leyeron title, reasoning ni payload de ninguna solicitud.

## 2. Dashboard que consume la policy

El archivo agente-autonomo/index.html en main:
- etiqueta la credencial como "Anon Public Key";
- realiza REST directo con apikey y Authorization: Bearer de esa clave;
- persiste URL y clave en localStorage;
- carga pending_approvals con select=*;
- muestra botones "OK Aprobar" y "X Rechazar";
- ejecuta PATCH para cambiar status.

La función PATCH envía reviewed_at, pero el esquema productivo tiene resolved_at y no reviewed_at. Además, el dashboard no verifica res.ok antes de mostrar "Aprobado correctamente" o "Rechazado". Por tanto, puede informar éxito aunque PostgREST haya rechazado la actualización por columna inexistente.

El archivo no implementa login de Supabase Auth ni identidad autenticada de revisor. La clave anon es pública por diseño, no una credencial de identidad.

La BITACORA histórica registra que la policy anon UPDATE fue creada deliberadamente para resolver el error de conexión del dashboard. Eso explica el origen, pero no convierte el mecanismo en una aprobación segura.

## 3. Impacto

Cualquier cliente que disponga de la URL y la anon/public key puede intentar:
- cambiar el status de cualquier solicitud, incluidas las pendientes;
- modificar payload, reasoning, confidence, title y otros campos;
- leer las 61 filas y sus payloads.

Esto permite falsificar decisiones humanas y manipular los datos del circuito de aprobación. La exposición de lectura también puede revelar detalles internos de propuestas y acciones.

La autorización a nivel SQL está confirmada. No se ejecutó una petición HTTP de escritura ni se probó un cambio de fila en producción.

## 4. Contención recomendada

No ampliar la autonomía ni distribuir agentes mientras este gate permanezca abierto.

### Contención mínima
- Quitar UPDATE a anon y eliminar la policy "Permitir update anon".
- Revocar INSERT/UPDATE/DELETE/TRUNCATE de anon y authenticated sobre pending_approvals.
- Restringir SELECT de anon; no exponer reasoning/payload a clientes anónimos.
- No usar service_role en navegador.

Esta contención desactiva los botones de aprobación actuales hasta reemplazarlos; no aplicar sin coordinar el cambio del dashboard.

### Solución correcta
1. Incorporar login real con Supabase Auth para el revisor humano.
2. Identificar revisores mediante auth.uid() y app_metadata controlada por servidor; nunca confiar en claims que el propio usuario pueda editar.
3. Crear una RPC resolve_pending_approval(id, decision) con SECURITY DEFINER de propietario restringido.
4. Validar identidad/rol de revisor, decision ∈ {approved,rejected}, estado actual pending y transición CAS.
5. Actualizar solo status y resolved_at; registrar resolved_by y un audit log inmutable.
6. Revocar DML directo a anon/authenticated; la UI usa solo la RPC autenticada.
7. Corregir dashboard: no persistir claves secretas en localStorage, comprobar HTTP status y usar resolved_at.
8. Testear anon denied, authenticated no reviewer denied, reviewer allowed, repeated decision rejected, payload immutable, rollback and audit record.

## 5. Gates antes de producción

- Reconciliar las 36 migraciones productivas; el SQL histórico completo no está versionado en los repos inspeccionados.
- Verificar backup y restore.
- Implementar y probar dashboard Auth en sandbox.
- Confirmar que la RPC solo permite al revisor humano y que el executor no puede aprobarse a sí mismo.
- Ensayar rollback y observar el flujo real antes de habilitarlo.

## 6. Evidencia

- pg_policies: SELECT anon USING(true), UPDATE anon USING(true).
- information_schema.role_column_grants: anon UPDATE en las 9 columnas.
- pg_trigger/information_schema.triggers: sin triggers en pending_approvals.
- pg_constraint: status_check permite pending, approved, rejected.
- SET LOCAL ROLE anon: 61 filas visibles, 2 pendientes; transacción revertida.
- Código actual: https://github.com/LeoJulieta/agente-autonomo/blob/main/index.html
- Histórico: BITACORA.md documenta la creación de la policy anon UPDATE para habilitar el dashboard.

No se ejecutó ninguna operación de aprobación, rechazo, modificación o lectura de payload.


## 7. Barrido de policies de escritura

Se consultaron todas las policies de public con cmd INSERT/UPDATE/DELETE/ALL y roles anon o public. El único caso con predicate no restringido para anon es pending_approvals UPDATE USING(true). Las policies service_role_full_access de trends_manual_import, yt_canales_competencia, yt_competencia_videos y yt_fechas_especiales están declaradas TO public, pero tanto USING como WITH CHECK exigen auth.role()='service_role'; no son escritura anónima efectiva. No se modificó ninguna policy.


## 8. Consecuencia adicional: XSS persistente en el dashboard

En renderApprovals(), index.html construye list.innerHTML interpolando directamente a.title y a.reasoning, sin escape HTML. Esos campos son editables por anon debido a la policy/grants observados. Por tanto, un cliente anónimo puede intentar almacenar markup/script en una fila y activar XSS cuando un operador abre el dashboard. No se insertó ningún payload ni se ejecutó una prueba de navegador.

El dashboard guarda sb_url y sb_key en localStorage. La clave prevista es anon/public, pero un operador podría pegar por error una secret key; una XSS persistente podría leer localStorage y exfiltrarla. El archivo no muestra autenticación Supabase ni sanitización de los campos de aprobación. No se verificaron headers CSP del hosting.

Remediación adicional obligatoria:
- renderizar datos con textContent o un escape HTML probado; no concatenar datos externos en innerHTML;
- eliminar handlers inline y usar event listeners con IDs validados;
- nunca persistir secret keys en navegador;
- agregar CSP apropiada al hosting, sin usarla como sustituto de sanitización;
- probar payloads XSS benignos en sandbox, nunca en producción.


## 9. SQL de contención de emergencia — NO EJECUTADO

Una vez verificados backup/restore y coordinado el corte del dashboard, la contención completa sería:

```sql
BEGIN;
DROP POLICY IF EXISTS "Permitir update anon" ON public.pending_approvals;
DROP POLICY IF EXISTS "Permitir lectura anon" ON public.pending_approvals;
REVOKE ALL PRIVILEGES ON TABLE public.pending_approvals FROM anon;
COMMIT;
```

Esto corta lectura y escritura anónimas; el dashboard actual dejará de cargar y aprobar solicitudes hasta que se despliegue una versión con Auth. No altera ni elimina filas. La reversión técnica sería recrear las policies/grants anteriores, pero eso reabre la vulnerabilidad y no debe usarse como solución permanente.

No ejecutar hasta comprobar respaldo restaurable, acordar ventana y disponer del flujo Auth de reemplazo o aceptar explícitamente el corte temporal.
