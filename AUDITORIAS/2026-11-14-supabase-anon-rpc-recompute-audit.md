# Supabase — auditoría de RPC anónimo con operaciones destructivas

Fecha: 2026-11-14  
Proyecto: btvfhopootvkqnpbctsq  
Estado: inspección de catálogo y permisos, solo lectura. No se invocó la función ni se ejecutó DDL/DML.

## 1. Hallazgo

La función public.recomputar_time_patterns() está definida como PL/pgSQL, SECURITY INVOKER (no SECURITY DEFINER), sin configuración fija de search_path. Su cuerpo ejecuta, en este orden:

1. TRUNCATE TABLE yt_time_patterns;
2. INSERT INTO yt_time_patterns ... SELECT ... FROM yt_trends_history;
3. UPDATE yt_time_patterns ...;

La función tiene EXECUTE para PUBLIC, por lo que has_function_privilege confirma que anon y authenticated pueden invocarla. service_role también tiene EXECUTE.

## 2. Privilegios y RLS observados

public.yt_time_patterns:
- RLS enabled; no FORCE RLS.
- Policy anon_read_tp: SELECT para anon, USING(true).
- Policy service_all_tp: ALL para service_role.
- anon tiene grants SELECT, INSERT, UPDATE, DELETE y TRUNCATE.
- authenticated también tiene grants amplios, aunque no se observó policy que le permita leer/escribir filas.
- service_role tiene permisos necesarios para la operación backend.

public.yt_trends_history:
- RLS enabled.
- Policy anon_read_trends para SELECT anon.
- anon puede SELECT; no tiene INSERT/UPDATE/DELETE/TRUNCATE en la consulta de privilegios.

La función es SECURITY INVOKER, por lo que la llamada como anon no adquiere privilegios de postgres ni de service_role. La policy de anon en yt_time_patterns solo permite SELECT; no hay policy anon para INSERT/UPDATE. Por tanto, aunque anon tiene permiso SQL TRUNCATE (que no está protegido por RLS), el INSERT posterior debería fallar por RLS y provocar rollback de toda la llamada. **No se probó ni se afirma que anon pueda persistir un TRUNCATE.** La superficie confirmada es una RPC pública que intenta una operación destructiva y puede causar locks/contención o abuso de recursos; el rollback esperado debe validarse en sandbox.

## 3. Caller legítimo identificado

El código histórico de agente-autonomo/youtube_shorts_agent.py crea el cliente Supabase con SUPABASE_URL y SUPABASE_KEY y llama a supabase.rpc("recomputar_time_patterns"). El usuario actualiza SUPABASE_KEY con una secret key moderna; el gateway la traduce a service_role. La función no aparece en cron.job; no se encontró un cron programado para esta recomputación.

Esto hace plausible que el permiso requerido sea solo service_role. No se encontró otro uso público legítimo en los repositorios inspeccionados.

## 4. Alcance de la búsqueda de funciones públicas

Se consultaron las funciones del schema public ejecutables por anon cuyo cuerpo contiene TRUNCATE, INSERT INTO, UPDATE ... SET o DELETE FROM. Solo apareció recomputar_time_patterns(). También se consultaron las funciones SECURITY DEFINER ejecutables por anon; no se encontraron resultados.

## 5. Corrección propuesta — no aplicada

En un cambio versionado y probado:

1. Reemplazar la función fijando SET search_path = '' y calificando todas las tablas:
   - public.yt_time_patterns
   - public.yt_trends_history
2. REVOKE EXECUTE ON FUNCTION public.recomputar_time_patterns() FROM PUBLIC, anon, authenticated.
3. Mantener GRANT EXECUTE ON FUNCTION public.recomputar_time_patterns() TO service_role.
4. REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON public.yt_time_patterns FROM anon, authenticated.
5. Mantener SELECT anon solo si el dashboard público lo necesita.
6. Mantener service_role como caller backend hasta migrar a una identidad de menor privilegio.

La corrección no debe ejecutarse directamente en producción: falta reconciliar las 36 migraciones, verificar backup/restore y localizar consumidores vigentes. No alterar los grants de otras tablas sin análisis.

## 6. Pruebas requeridas en sandbox

- Antes del parche: invocar como anon dentro de transacción; confirmar que el INSERT falla por RLS y que el TRUNCATE queda revertido.
- Después del parche: anon recibe permission denied al invocar RPC.
- service_role puede ejecutar la recomputación y reconstruir los patrones.
- Confirmar que anon conserva solo SELECT en la interfaz pública prevista.
- Simular dos llamadas concurrentes y medir lock/serialización.
- Asegurar que el trabajo global de recomputación se ejecuta una sola vez mediante controlador/lease; no distribuirlo entre 8+ agentes.

## 7. Conclusión

La RPC no debería estar expuesta a anon/authenticated. La autorización actual no demuestra una escritura persistente anónima porque RLS debería abortar el INSERT y revertir el TRUNCATE, pero sí expone una operación de mantenimiento global a llamadas no privilegiadas y mantiene grants TRUNCATE innecesarios. La corrección propuesta reduce superficie sin romper el caller backend identificado.
