# E12 — auditoría de solo lectura del esquema productivo

Fecha: 2026-11-14  
Proyecto Supabase: 'btvfhopootvkqnpbctsq'  
Estado: lectura únicamente; no se ejecutó DDL ni DML.

## 1. Proyecto y migraciones

- Proyecto ACTIVE_HEALTHY.
- PostgreSQL 17.6.1.127, región us-east-1.
- El catálogo de migraciones devuelve 36 registros; el último es '20260906020435 create_lab_results'.
- No figuran migraciones E12 de noviembre ni los objetos E12 consultados anteriormente.
- El árbol de 'LeoJulieta/agente-runner' contiene 9 archivos SQL en 'supabase/migrations': 4 PR-D/anteriores y 5 E12.
- El árbol de 'LeoJulieta/agente-autonomo' no contiene 'supabase/migrations'; contiene funciones y un 'migration_health_check.sql', pero no la historia SQL completa.
- Por tanto, la historia de 36 migraciones de producción no está versionada íntegramente en esos dos repositorios. No ejecutar 'supabase db push' ni reconstruir producción desde el conjunto actual de 9 archivos.

## 2. Esquema real de public.youtube_shorts_log

El catálogo actual muestra 23 columnas. La estructura relevante:

| Columna | Tipo productivo | Nullable |
|---|---|---|
| id | bigint | NO |
| youtube_video_id | text | YES |
| status | text | YES |
| created_at | timestamptz | YES |
| updated_at | timestamptz | YES |
| views_primeras_3h | integer (int4) | YES |
| hs_al_publicar_al_sync | numeric | YES |
| privacy_status | text | YES |
| upload_status | text | YES |
| script_texto | text | YES |
| tags | text[] | YES |

El E12 migration '20261112160000...' convierte 'views_primeras_3h' a 'numeric(20,0)' para soportar el uint64 de YouTube. Esa conversión parte de **integer en producción**, no de numeric. El test de migraciones actual usaba un baseline sintético con numeric, por lo que no ejercitaba la conversión real int4→numeric. Corregir el baseline CI para que reproduzca el tipo productivo antes de considerar cerrado el gate.

La tabla tiene RLS habilitado, no FORCE RLS, owner postgres, PK sobre id, cuatro índices, una constraint PK y un trigger 'shorts_updated_at' que ejecuta 'update_updated_at()'.

## 3. Preflight de datos para la conversión

Consulta agregada de solo lectura:

- 961 filas.
- 'views_primeras_3h': 649 NULL; mínimo 0; máximo 152; 0 negativos; 0 fraccionarios.
- 'hs_al_publicar_al_sync': 649 NULL.
- El preflight de valores unsigned del SQL E12, aplicado a los valores actuales, no detectaría negativos ni fracciones.
- Los datos observados no sugieren pérdida al convertir int4 a numeric(20,0); esto no sustituye un test real de DDL, bloqueo, backup y rollback.

Distribución 'status / privacy_status':
- published / public: 795
- published / NULL: 118
- upload_error / NULL: 38
- video_error / NULL: 10

## 4. Hallazgo de seguridad: lectura anónima de la tabla

La tabla tiene una policy RLS 'anon_read' para rol 'anon' con 'USING (true)', además de 'service_all' para 'service_role'. Los grants SQL observados a 'anon' incluyen SELECT, INSERT, UPDATE, DELETE y TRUNCATE; la RLS sin policies de escritura bloquea DML normal, pero **la policy de SELECT permite leer todas las filas**, sin filtrar 'status' ni 'privacy_status'.

La distribución anterior indica que 166 filas no tienen 'privacy_status=public' (118 publicadas con privacy NULL y 48 con estados de error). Por la policy actual, el rol anon puede leer esas filas en SQL si la tabla está expuesta a través del Data API. No se verificó una llamada HTTP anónima en esta auditoría; el hallazgo confirmado es la policy/grant SQL. Debe tratarse como posible exposición de 'script_texto', metadatos y filas no explícitamente públicas.

**No se cambió la policy.** Antes de restringirla hay que identificar clientes que dependan de lectura pública, decidir qué columnas/filas son realmente públicas y probar una vista pública sanitizada o una policy más estrecha. No aplicar cambios masivos ni revocar SELECT sin plan de compatibilidad.

El grant TRUNCATE a anon también merece revisión: TRUNCATE no está protegido por RLS, aunque PostgREST no ofrece una operación REST directa de TRUNCATE. Verificar funciones SECURITY DEFINER expuestas antes de concluir explotabilidad.

## 5. Compatibilidad E12 y riesgos

- El SQL E12 asume 'hs_al_publicar_al_sync', 'views_primeras_3h', 'id' y 'youtube_video_id'; esos campos existen.
- El tipo productivo de 'views_primeras_3h' es int4, mientras que el baseline CI actual lo había declarado numeric. Debe corregirse el test.
- La tabla tiene policies públicas preexistentes. La migración E12 agrega policies para 'pr_d_capture_owner', pero no elimina 'anon_read'; no resuelve el posible acceso público.
- El worker sigue autenticándose con una secret key que el gateway traduce a 'service_role', rol con BYPASSRLS. El diseño de menor privilegio sigue pendiente.
- No se encontraron tablas/funciones E12 en el catálogo productivo consultado.

## 6. Backups y restore

El conector disponible no expone listado de backups ni ejecución de restore, y la información de proyecto no incluye el plan contratado. No se puede afirmar que exista un backup utilizable ni que se haya probado restauración.

La documentación oficial indica que los backups diarios automáticos dependen de planes Pro/Team/Enterprise; para proyectos Free recomienda exportaciones periódicas con Supabase CLI. Los backups de base de datos no incluyen los objetos de Storage; la restauración implica indisponibilidad durante el proceso y puede requerir restablecer contraseñas de roles personalizados. PITR es un add-on de pago. No se habilitó ni se asumió que esté activo.

La creación de una branch Supabase para staging tiene costo cotizado de USD 0.01344 por hora. No se creó ninguna branch ni se incurrió en ese costo.

## 7. Próximos pasos

1. Corregir el baseline de 'full_migration_chain.py' a int4 y replicar las policies, grants, índices y trigger preexistentes relevantes.
2. Ejecutar en Supabase local el API Gateway E2E (CI #110) y verificar 'sb_secret' solo en 'apikey'.
3. Obtener un schema-only dump verificable de producción o construir un baseline fiel, sin copiar datos privados ni secretos.
4. Reconciliar los 36 registros de migración con SQL versionado antes de cualquier 'db push'.
5. Auditar funciones SECURITY DEFINER accesibles por anon y el efecto del grant TRUNCATE.
6. Revisar la intención de 'anon_read' y diseñar exposición pública mínima sin romper consumidores.
7. Verificar backup disponible y ensayo de restore en entorno aislado antes de producción.
8. Resolver privilegio de 'service_role' para E12.

## 8. Evidencia y referencias

- Lectura del proyecto y migraciones mediante Supabase connector el 2026-11-14.
- Consulta de catálogo de columnas, índices, constraints, policies, triggers, grants, roles y extensiones.
- Consulta agregada de conteos, rangos y distribución status/privacy; no se leyeron textos de filas.
- Supabase backups: https://supabase.com/docs/guides/platform/backups
- Supabase CLI db dump: https://supabase.com/docs/reference/cli/supabase-db-dump


## Addendum: verificación directa del rol anon — 2026-11-14

Se ejecutó una transacción de solo lectura con 'SET LOCAL ROLE anon', se consultaron solo agregados y se hizo ROLLBACK. Resultado:
- filas visibles para anon: 961;
- filas con privacy_status distinto de public o NULL: 166;
- filas con status distinto de published: 48.

Esto confirma que no es solo una inferencia a partir de la policy: el rol SQL anon efectivamente ve las 961 filas. Sigue sin ser una petición HTTP a la API REST, por lo que el alcance exacto de exposición externa depende de la configuración del Data API; la capacidad de lectura anónima a nivel de base está verificada.

Una búsqueda de funciones SECURITY DEFINER del schema public ejecutables por anon no encontró resultados. También se hizo una búsqueda acotada de funciones SECURITY DEFINER que mencionen youtube_shorts_log, TRUNCATE o DELETE FROM y no hubo coincidencias. Esto reduce un posible vector de abuso del grant TRUNCATE, pero no sustituye una auditoría completa de todas las funciones y wrappers.

No se cambió ninguna policy, grant, tabla ni dato.
