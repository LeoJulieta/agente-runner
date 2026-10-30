# PR D — Auditoría del productor y la ventana de sincronización

**Fecha de auditoría:** 2026-10-30  
**Estado:** evidencia documental de solo lectura; decisiones contractuales pendientes.  
**Alcance:** inspección estática de código privado, workflows públicos, contrato congelado en `main`, matriz de trazabilidad y constructor sintético de cohortes.  
**Límite de seguridad:** no se ejecutaron scripts, no se consultaron filas reales de Supabase, no se modificaron workflows de producción, no se modificó el manifiesto y no se cambió `execution_status: "fixture"`.

## 1. Fuentes inspeccionadas

### Repositorio privado `LeoJulieta/agente-autonomo`

| Archivo | Blob SHA | Uso en la auditoría |
|---|---|---|
| `youtube_shorts_agent.py` | `d789467b0d5de6912e7ba6d0b72f8ecf37982fa5` | Registro de videos, obtención de estadísticas y sincronización |
| `youtube_uploader.py` | `a6a3297691473d7374620838f2cae988c3045ee0` | Solicitud de subida y privacidad inicial |
| `trend_monitor.py` | `155e905ac93967e2ec03390907fa036be0d9f716` | Inspección complementaria |
| `sincronizar_audiencia_demografica.py` | `60257dae4b955a352f69ed3ac3f5795556c7dc1c` | Inspección complementaria |

### Repositorio `LeoJulieta/agente-runner`

- Contrato congelado en `main`: `docs/PR-D-DESIGN.md`, blob SHA `b18be485058342e7a85eee14fcd4492c9ae09b2a`.
- Matriz T01–T32 en rama `audit/pr-d-traceability-matrix`: `docs/PR-D-TRACEABILITY-MATRIX.md`, blob SHA `d7a9c3688210e26cffac44389f0e2d9b5e1edf77`.
- Contrato candidato de la rama de trabajo `fix/pr-d-inference-block-2`: `docs/PR-D-DESIGN.md`, blob SHA `645e0ed3747fbfe1104c6746ef8edef5c13ff510`.
- PR #109 continúa abierto y sin fusionar; PR #90 continúa abierto y sin fusionar. El manifiesto permanece en modo fixture.

## 2. Flujo productor observado

En `youtube_shorts_agent.py`:

1. `main()` llama a `subir_video()` (línea 4392).
2. Si la subida devuelve un `video_id`, llama después a `registrar_en_supabase()` (línea 4397).
3. `registrar_en_supabase()` crea `now = datetime.now(timezone.utc)` (línea 2911) y escribe `created_at = now.isoformat()` en `youtube_shorts_log` (línea 2940).
4. Por lo tanto, el `created_at` insertado por este camino representa el momento de registro posterior a la respuesta exitosa de subida; el código inspeccionado no demuestra que sea el instante exacto de publicación efectiva en YouTube.

En `youtube_uploader.py`, la solicitud de subida establece `privacyStatus: "public"`. No se encontró lectura ni persistencia de `snippet.publishedAt` en los archivos privados inspeccionados.

## 3. Flujo de sincronización y discrepancia de ventana

En `youtube_shorts_agent.py`:

- `obtener_metricas_youtube_batch()` (líneas 3005–3041) solicita `part="statistics,status"`; no solicita `snippet`.
- `sincronizar_metricas()` (línea 3252) lee `created_at`, `views_primeras_3h` y otros campos.
- Calcula `antigüedad_hs = (now_utc - created_at).total_seconds() / 3600.0` (línea 3313).
- Captura cuando `views_primeras_3h` es nulo y `3.0 <= antigüedad_hs <= 12.0` (línea 3316). Ambos extremos son inclusivos.
- En esa captura escribe las vistas y `hs_al_publicar_al_sync = round(antigüedad_hs, 2)`.

**Hallazgo confirmado:** el código actual aplica una ventana de 3–12 horas, no 3–6 horas.

**Distinción importante:** `labs/README.md` registra observaciones históricas de 3.03–9.85 horas y mediana 4.48 horas. Esos valores describen el rango observado en ese corte de datos; no limitan el máximo que permite el código, que es 12 horas.

El contrato congelado en `main`, §4, exige aplicar el filtro de sincronización de 3–6 horas cuando corresponda. No especifica en esa regla el campo temporal fuente, el evento exacto de anclaje, la inclusividad de los extremos ni la política de nulos. Por tanto, el productor actual y el contrato no son equivalentes.

## 4. Nulos y manejo de errores

- La condición de captura requiere `views_primeras_3h is None`.
- Si `created_at` es nulo, el camino actual intenta ejecutar `.replace()` sobre ese valor al parsearlo. El error queda dentro del manejo general de `sincronizar_metricas()`; no se observa una política contractual explícita de exclusión individual con causa.
- Si una fila llega a sincronización fuera de 3–12 horas y sigue sin captura, la condición no se cumple y la medición permanece nula.
- El constructor sintético `labs/pr_d_cohort_builder.py` exige que el campo elapsed-seconds, la inclusividad de ambos extremos y la política de missing sean configuración explícita. Admite `exclude_with_reason` o `raise`; no infiere el ancla temporal.

## 5. Riesgo adicional: garantía write-once y concurrencia

El sincronizador comprueba en memoria que `views_primeras_3h` sea nulo y luego actualiza la fila por `id`. En el UPDATE inspeccionado no aparece una condición adicional que vuelva a comprobar que la columna siga nula en el instante de escritura.

Los workflows públicos `solo_metricas.yml` y `solo_metricasBack.yml` tienen cron `0 */2 * * *`; ambos invocan `solo_metricas()`, que llama a `sincronizar_metricas()`. El workflow `youtube_shorts.yml` también ejecuta `sincronizar_metricas()` dentro de `main()` y tiene ejecuciones programadas a las 0 y 2 UTC, entre otros horarios. En los tres archivos inspeccionados no se encontró una declaración `concurrency`.

**Clasificación:** riesgo potencial de carrera, no incidente demostrado. La comprobación en Python es una guarda de aplicación, pero el UPDATE observado no constituye por sí solo una operación compare-and-set atómica. La auditoría previa de metadata de Supabase solo identificó el trigger general de `updated_at`, no un trigger específico para estas dos columnas. Se requiere verificar cualquier otra protección antes de afirmar una garantía write-once a nivel de base de datos.

## 6. Timestamp alternativo disponible

La documentación oficial de YouTube Data API define `snippet.publishedAt` como fecha/hora de publicación y explica que puede diferir de la subida; el recurso se puede solicitar mediante `videos.list` incluyendo `part=snippet`.

Fuentes oficiales:
- https://developers.google.com/youtube/data/reference/rest/v3/videos
- https://developers.google.com/youtube/data/reference/rest/v3/videos/list

**Propuesta técnica para evaluación, no decisión ya aprobada:** recuperar y persistir el timestamp de YouTube en un campo explícito, manteniendo separado el momento de registro de Supabase. Validar la semántica para los estados de privacidad usados por el agente antes de convertirlo en ancla contractual.

## 7. Hallazgo adicional: derivación de `hora_publicacion` en H001/H002

En la rama `fix/pr-d-inference-block-2`:

- `labs/hypotheses/H001.yaml` y `H002.yaml` definen `hora_publicacion` con `source: created_at`, `subtract_hours_from_column: hs_al_publicar_al_sync`, `tz_offset_hours: -3` y `extract: hour`.
- `labs/variable_catalog.yaml` repite esa derivación mediante `optional_subtract_column: hs_al_publicar_al_sync`.
- Sin embargo, el productor de `hs_al_publicar_al_sync` en `sincronizar_metricas()` lo calcula como `(now_utc - created_at)`, es decir, duración transcurrida desde `created_at` hasta el momento del sync; no es un timestamp ni una duración calculada desde un `publishedAt` independiente.

**Incoherencia semántica confirmada:** restar a `created_at` una duración que ya fue calculada como `sync_now - created_at` no reconstruye la hora real de publicación. La operación resultante equivale a `2 * created_at - sync_now` en términos temporales, no a `publishedAt`. Además, el código inspeccionado no persiste el timestamp de sincronización utilizado en ese cálculo.

**Impacto potencial:** las variables `hora_publicacion` de H001/H002 podrían estar derivándose desde un ancla temporal incorrecta. No se cuantificó el efecto sobre filas históricas porque esta auditoría no leyó registros reales de Supabase.

**Acción requerida:** bloquear cualquier interpretación de H001/H002 como medición válida de hora real de publicación hasta definir una fuente temporal coherente y auditar el cálculo histórico. No corregir retrospectivamente ni recalcular filas sin una decisión contractual y un plan de migración/reproducibilidad aprobado.

## 8. Contraste contractual y bloqueos

| Tema | Contrato / arquitectura PR D | Productor actual | Estado |
|---|---|---|---|
| Ventana | 3–6 h cuando corresponda | 3–12 h inclusivas | Desviación confirmada |
| Campo fuente | No queda identificado en §4 | `created_at` | Decisión pendiente |
| Ancla temporal | No queda identificada en §4 | Registro posterior al upload | No equivalente a publicación verificada |
| Límites | Inclusividad no fijada en §4 | 3 y 12 inclusivos | Decisión pendiente |
| Missing timestamp | Política no fijada en §4 | Excepción general al parsear `created_at` nulo | Política insuficiente/no contractual |
| Missing elapsed | Debe definirse antes de construir cohorte | El builder requiere política explícita | Builder preparado; contrato pendiente |
| Write-once | Se describe como write-once en metadata | Guarda previa en Python; UPDATE sin condición `IS NULL` | Riesgo de carrera por verificar |

### Decisiones necesarias antes de integrar

1. **Ancla:** decidir si la elegibilidad se calcula desde `snippet.publishedAt` de YouTube o desde otro evento contractual expresamente justificado. No tratar `created_at` como publicación real sin validación.
2. **Campo persistido:** si se adopta `publishedAt`, definir nombre, tipo, backfill y comportamiento para datos históricos sin ese valor. No ejecutar migraciones en esta etapa.
3. **Ventana:** confirmar 3–6 horas y decidir inclusividad de 3 h y 6 h.
4. **Missing:** definir si timestamp ausente invalida la hipótesis, excluye la observación con causa o provoca otro resultado contractual. Distinguir fallo de esquema/lote de missing individual.
5. **Write-once:** decidir y probar protección atómica frente a sincronizadores concurrentes; no asumir que el control Python actual basta.
6. **Derivaciones:** revisar `variable_catalog.yaml` y H001/H002, que derivan variables horarias desde `created_at` y contemplan `hs_al_publicar_al_sync`. Confirmar que la resta temporal y el significado de esa duración son coherentes con el ancla finalmente elegida.

## 9. Límites y siguiente etapa

- Este informe es evidencia de auditoría estática; no modifica el contrato ni resuelve por sí mismo las decisiones anteriores.
- PR #110 aporta un constructor sintético configurable, pero no conecta el productor privado, el sincronizador ni el motor real con Familia II.
- No se ha demostrado una ruta E2E desde publicación real hasta estimación Familia II.
- No se consultaron filas reales de Supabase ni se ejecutó ningún workflow.
- No cambiar `docs/manifest.json`, `execution_status`, motor de producción, workflows ni datos reales hasta resolver y aprobar las decisiones contractuales.

**Siguiente hito recomendado:** resolver las decisiones 1–5 con auditoría humana y revisión externa; después diseñar fixtures sintéticos que cubran los límites exactos y adyacentes, timestamp faltante, ancla alternativa y concurrencia. Solo entonces conectar el builder con una ruta E2E sintética suficiente para demostrar tanto una estimación exitosa como `INSUFFICIENT_POWER`.
