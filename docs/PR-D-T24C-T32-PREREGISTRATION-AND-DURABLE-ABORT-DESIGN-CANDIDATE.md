# PR D — diseño candidato de preregistro T24c y registro durable T32

**Estado:** propuesta documental para auditoría humana; no normativa y no aprobada para implementación.
**Base:** PR D v2 vigente (E1–E5). E6–E11 y la matriz T01–T32 continúan siendo material candidato.
**Propósito:** convertir los bloqueos T24c y T32 en decisiones explícitas, datos requeridos y criterios verificables, sin elegir un método estadístico ni una infraestructura de persistencia por inferencia.
**Límite de seguridad:** no modifica el motor, manifiesto ni esquema de Supabase; no consulta ni escribe Supabase; no ejecuta hipótesis reales. `docs/manifest.json` debe permanecer `execution_status: "fixture"`.

---

## 1. T24c — expediente de preregistro de potencia informativa

### 1.1 Estado actual y regla de bloqueo

T24c sigue **BLOQUEADO**. La mera documentación de este expediente no equivale a preregistro, aprobación científica, cálculo ni cierre de T24c.

En PR D v1, `n_required_power` es informativo y no es un gate. Los pisos operativos (`n_eff >= 30`, mínimos de eventos y diagnósticos EPV cuando correspondan) no garantizan potencia. No se debe inferir una potencia del 80 % a partir de esos pisos.

No se calculará `n_required_power` hasta que todos los campos obligatorios de este expediente estén completos, revisados y congelados para la familia, contraste y diseño específicos. Un cálculo no aplicable o cuyos supuestos no se cumplan debe permanecer no calculable (`value=null`) con una razón cerrada; nunca se sustituirá por una cifra aproximada sin fundamento.

### 1.2 Unidad de preregistro

El preregistro no es global para todo PR D. Debe identificar una combinación inequívoca de:

- versión del contrato y huella del método;
- familia estadística (Familia I o Familia II);
- outcome, predictor/contraste y estimando primario;
- población y unidad de análisis;
- diseño y estructura de dependencia;
- ventana o conjunto de ventanas al que se aplica;
- efecto mínimo relevante en la escala del estimando.

No se permite trasladar automáticamente un cálculo entre familias, outcomes, contrastes, escalas, unidades o diseños distintos.

### 1.3 Formulario obligatorio — sin valores predeterminados implícitos

El siguiente registro es una plantilla vacía. Los valores deben ser aportados y aprobados mediante revisión científica; no se completan por conveniencia ni mirando resultados observados.

| Campo | Contenido obligatorio | Estado |
|---|---|---|
| `preregistration_id` | Identificador inmutable y versionado | PENDIENTE |
| `contract_version` / `contract_hash` | Versión y hash exactos del contrato | PENDIENTE |
| `method_fingerprint` | Huella de método que se usará en la evaluación | PENDIENTE |
| `family_id` | Familia I (logística) o Familia II (OLS sobre ln(Y), HC3) | PENDIENTE |
| `hypothesis_scope` | Hipótesis/outcome/contraste primario y población | PENDIENTE |
| `estimand` / `effect_scale` | Parámetro objetivo y escala interpretable | PENDIENTE |
| `minimum_relevant_effect` | Valor, escala, dirección y justificación sustantiva | PENDIENTE |
| `alpha` | Nivel nominal y unilateralidad/bilateralidad | PENDIENTE |
| `target_power` | Potencia objetivo y justificación | PENDIENTE |
| `design` | Diseño, asignación, grupos, medidas repetidas y estructura de dependencia | PENDIENTE |
| `analysis_unit` | Unidad independiente que aporta información al cálculo | PENDIENTE |
| `parameters` | Todos los parámetros requeridos por el método, con fuente y escala | PENDIENTE |
| `assumptions` | Supuestos, diagnósticos y criterios de aplicabilidad/fallo | PENDIENTE |
| `missingness_and_exclusions` | Tratamiento preregistrado de faltantes, exclusiones y truncamiento | PENDIENTE |
| `multiplicity_scope` | Relación con familia FDR congelada y alcance del cálculo | PENDIENTE |
| `method_reference` | Referencia metodológica independiente, versión y localizador verificable | PENDIENTE |
| `independent_validation` | Procedimiento independiente de reproducción/contraste y responsable revisor | PENDIENTE |
| `software_environment` | Software, versiones, precisión numérica y tolerancias propuestas | PENDIENTE |
| `approval_record` | Revisor, fecha, decisión y hash del registro aprobado | PENDIENTE |

**Regla de completitud:** un campo no aplicable debe contener una justificación explícita aprobada; dejarlo vacío, usar "default" o copiar un parámetro de otra familia no satisface el requisito.

### 1.4 Separación por familia — decisiones que no se presuponen

**Familia I:** el contrato inferencial principal es regresión logística por máxima verosimilitud con contraste Wald bilateral. El expediente debe definir el diseño y los parámetros que correspondan a ese estimando/modelo. EPV puede registrarse como diagnóstico de información del modelo, pero no es por sí solo un cálculo exacto de potencia. No se prescribe aquí una fórmula de potencia logística.

**Familia II:** el contrato inferencial principal es OLS sobre `ln(Y)` para `Y > 0`, con covarianza HC3 y contraste t bilateral. El expediente debe definir el efecto mínimo en la escala de `ln(Y)`, la unidad independiente, la estructura de covariables y los parámetros necesarios. No se presume que una fórmula de dos muestras simple sea válida si el diseño, covariables o dependencia no lo justifican.

La referencia a Fisher solo podrá considerarse si el parámetro y el diseño justifican específicamente su aplicación; no es una alternativa automática para ninguna familia.

### 1.5 Revisión independiente y congelamiento

Antes de habilitar cualquier cálculo:

1. Un revisor metodológico distinto de quien implementa el cálculo verifica que el método corresponde al estimando, diseño, familia y unidad de análisis.
2. Se verifica cada supuesto con evidencia previa o fixtures sintéticos; los resultados observados de las hipótesis no pueden usarse para escoger método o parámetros.
3. Se reproduce el cálculo desde el registro congelado mediante una referencia independiente.
4. Se guardan el expediente, su hash, la referencia y la evidencia de revisión en Git.
5. Se define la política para supuestos incumplidos: salida nula con motivo, sin fallback silencioso.

Cambiar método, parámetros, estimando, diseño, unidad o referencia requiere una nueva versión del preregistro y un nuevo `method_fingerprint`. No se sobrescribe el registro previo.

### 1.6 Contrato de salida de T28

Los fixtures T28 fusionados prueban únicamente la coherencia estructural entre `value`, `reason` y `unit`; los valores ilustrativos 42 y 18 no son resultados de potencia. No amplían ese alcance.

Antes de integrar un cálculo, deberá añadirse un fixture independiente por cada familia/unidad soportada que incluya:
- preregistro completo y hash esperado;
- entrada sintética congelada y supuestos satisfechos;
- resultado de referencia independiente;
- unidad explícita (`eligible_observations` o `positive_events`, según corresponda);
- tolerancia numérica justificada y aprobada;
- casos negativos para cada supuesto incumplido y salida nula con razón cerrada.

Hasta entonces, T24c permanece BLOQUEADO y T28 solo tiene cobertura parcial de forma.

---

## 2. T32 — diseño candidato del registro durable de aborto

### 2.1 Problema que debe resolver

La regla de aborto de lote prohíbe presentar resultados científicos parciales como válidos cuando un fallo estructural compromete la integridad del lote. T32 añade una necesidad operativa distinta: dejar un registro durable y recuperable del aborto.

La atomicidad de la persistencia científica y la durabilidad del registro operacional son propiedades distintas. Una transacción científica que hace rollback no puede, por sí sola, demostrar que el registro del fallo sobrevivió a ese rollback. Los tests existentes de RPC atómica/idempotente y la ruta del motor no demuestran aún el registro durable E11.

### 2.2 Sobre de evento mínimo propuesto

Cada intento debe tener identidad propia, generada antes del preflight, para poder registrar también fallos tempranos.

| Campo | Regla candidata |
|---|---|
| `batch_id` | Identidad estable del lote lógico |
| `execution_id` | Identificador único de este intento; distinto en cada reintento |
| `contract_version_hash` | Huella del contrato aplicado |
| `manifest_ref` | Referencia inmutable del manifiesto |
| `manifest_hash` | Hash del contenido exacto del manifiesto |
| `failure_code` | Uno de los códigos cerrados de §2.3 |
| `failure_phase` | Una de las fases cerradas de §2.3 |
| `status` | Literal `ABORTED` |
| `completed` | Literal booleano `false` |
| `timestamp` | Instante UTC de detección/registro, con formato acordado |
| `diagnostic_ref` | Referencia a diagnóstico/log/artifacto recuperable, sin secretos |

El registro no debe contener tokens, credenciales, claves, payloads sensibles ni copias innecesarias de datos personales. El diagnóstico debe estar limitado, redactado y protegido según la política de acceso que se apruebe.

### 2.3 Catálogos cerrados

**Códigos de fallo permitidos:**

- `SCHEMA_INCOMPATIBLE`
- `WINDOW_INVALID`
- `METHOD_FINGERPRINT_MISMATCH`
- `DATA_READ_FAILURE`
- `CONNECTION_FAILURE`
- `UNEXPECTED_ERROR`

**Fases permitidas:**

- `preflight`
- `data_read`
- `validation`
- `analysis`
- `aggregation`
- `persistence`
- `finalization`

La implementación deberá mapear excepciones a estos catálogos sin guardar mensajes arbitrarios como código. El detalle técnico adicional se conserva en el diagnóstico referenciado y saneado.

### 2.4 Secuencia operacional candidata

1. **Identificar:** crear `batch_id` y `execution_id` antes de iniciar preflight; congelar referencias y hashes disponibles.
2. **Preflight:** validar manifiesto, contrato, esquema, ventanas y huella de método antes de cualquier cálculo/publicación.
3. **Ejecutar en staging:** acumular resultados científicos fuera del destino visible/publicado. Ningún resultado parcial se presenta como lote completo.
4. **Detectar fallo estructural:** detener el lote, descartar o mantener inaccesible el staging y asignar exactamente un `failure_code` y una `failure_phase`.
5. **Abortar resultados:** garantizar que no haya publicación parcial. La transacción/operación de resultados debe ser atómica e idempotente según el contrato.
6. **Registrar el aborto:** persistir el sobre mínimo en un canal durable que no dependa exclusivamente de la misma transacción de resultados que se está revirtiendo.
7. **Verificar durabilidad:** leer el registro desde una nueva sesión/contexto y comprobar identidad, campos, hash y referencia diagnóstica.
8. **Recuperar:** permitir que un operador autorizado localice el evento por `batch_id` o `execution_id`, inspeccione diagnóstico saneado y decida reintento/cierre. Un reintento genera nuevo `execution_id`; no borra ni sobrescribe el intento abortado.

El paso 6 no selecciona proveedor ni tabla. La elección de almacenamiento es una decisión de infraestructura pendiente y requiere revisión de permisos, disponibilidad, retención, respaldo y modo de fallo.

### 2.5 Condición crítica: ¿qué pasa si falla el propio registro?

No se debe declarar T32 satisfecho si el sistema no pudo confirmar la escritura durable del evento. Debe existir un segundo mecanismo operacional de contingencia, independiente del destino primario, o una condición explícita de fallo crítico que impida continuar y requiera intervención humana. La estrategia concreta y sus garantías deben definirse antes de implementar; no se presume que un log de CI, stdout o el código de salida 2 sea por sí solo un registro durable y recuperable.

Si el canal primario y la contingencia fallan, el sistema no puede afirmar que dejó un registro durable. Debe exponer ese estado como fallo de observabilidad/registro, detener nuevos lotes y conservar la mayor evidencia local disponible para recuperación manual, sin presentarla como persistencia confirmada.

### 2.6 Idempotencia, concurrencia y recuperación

- La unicidad se define por `execution_id`; el reintento es un nuevo intento y recibe un nuevo ID.
- Una repetición de la misma solicitud de escritura para el mismo `execution_id` no crea duplicados ni altera el evento ya confirmado.
- El mismo `batch_id` puede tener varios intentos; la consulta debe mostrar su secuencia sin borrar eventos anteriores.
- Conflictos de identidad o de hash no se resuelven sobrescribiendo: se detienen y se elevan como error de integridad.
- La recuperación debe poder reconstruir qué se intentó, con qué contrato/manifiesto y por qué fase/código se abortó, sin depender de memoria del proceso que falló.

### 2.7 Decisiones de infraestructura todavía abiertas

Estas decisiones son bloqueantes; no se elige una por conveniencia ni se escribe migración antes de resolverlas:

1. **Destino durable:** dónde se almacena el sobre operacional y qué evidencia demuestra durabilidad tras reinicio/fallo.
2. **Independencia transaccional:** cómo se garantiza que el evento de aborto sobreviva al rollback de resultados.
3. **Contingencia:** segundo canal o procedimiento de recuperación si falla el destino primario.
4. **Autenticación y permisos:** identidad de escritura/lectura, mínimo privilegio, RLS si aplica, y separación entre operadores y procesos.
5. **Retención y respaldo:** duración, política de borrado, backup y prueba de restauración.
6. **Integridad:** unicidad, restricciones de campos/catálogos, hashes y protección contra modificación accidental.
7. **Observabilidad:** alerta verificable ante fallo del registro, sin filtrar secretos.
8. **Recuperación:** procedimiento operativo, responsables y criterio para reintentar o cerrar.
9. **Prueba aislada:** PostgreSQL local descartable o entorno E2E explícitamente aislado; nunca producción para desarrollar estos tests.

### 2.8 Pruebas de aceptación propuestas para T32

La cobertura solo podrá elevarse a IMPLEMENTADO cuando exista evidencia reproducible de, al menos:

| Caso | Inyección/condición | Aserción obligatoria |
|---|---|---|
| T32-01 | Fallo estructural en preflight | Evento durable con fase `preflight`; cero resultados científicos publicados |
| T32-02 | Fallo durante lectura | Código/fase correctos; lote abortado; sin resultados parciales |
| T32-03 | Huella inconsistente | `METHOD_FINGERPRINT_MISMATCH`; no se publica evidencia |
| T32-04 | Fallo durante persistencia científica | Rollback completo de resultados y evento operacional durable independiente |
| T32-05 | Repetición de escritura del mismo `execution_id` | Una sola identidad/evento, sin duplicación |
| T32-06 | Dos intentos concurrentes del mismo lote | Intentos distinguibles; ningún evento se sobrescribe |
| T32-07 | Reinicio del proceso tras registrar aborto | Evento recuperable desde un nuevo proceso/sesión |
| T32-08 | Fallo del destino operacional primario | Contingencia ejecutada o fallo crítico explícito; nunca afirmar durabilidad no confirmada |
| T32-09 | Diagnóstico con secretos simulados | Secretos redactados; campos de identidad y clasificación preservados |
| T32-10 | Código/fase fuera del catálogo | Rechazo controlado; no persistir categoría dinámica |
| T32-11 | Conflicto de hash/identidad | Detención y señal de integridad; sin sobrescritura |
| T32-12 | Restauración/recuperación | Operador puede localizar evento, leer diagnóstico permitido y reconstruir el intento |

Los tests deben probar el evento desde un contexto de lectura nuevo y después del límite transaccional relevante. Una aserción sobre retorno de función, stdout o exit code no demuestra durabilidad.

### 2.9 No objetivos

Este diseño no elige Supabase, PostgreSQL, GitHub Actions artifacts, almacenamiento externo ni otro proveedor como destino final. No propone migraciones, RPC, tablas, secretos, políticas RLS ni cambios al motor. Tampoco convierte E11 en regla normativa ni autoriza ejecutar hipótesis.

---

## 3. Puertas de salida y próximos artefactos

### T24c puede pasar de BLOQUEADO a PREREGISTRADO solo cuando:

- todos los campos aplicables de §1.3 estén completos;
- la referencia metodológica independiente esté disponible y versionada;
- la revisión metodológica independiente esté registrada;
- el cálculo de referencia sea reproducible con fixtures sintéticos;
- los supuestos y salidas nulas estén probados;
- el registro y su hash estén congelados antes de observar resultados de hipótesis.

Aun entonces, `n_required_power` continúa siendo informativo en PR D v1, no un gate.

### T32 puede pasar de PARCIAL a IMPLEMENTADO solo cuando:

- la arquitectura de almacenamiento/contingencia haya sido elegida y revisada;
- la independencia del rollback esté demostrada;
- todos los casos críticos de §2.8 pasen en infraestructura aislada;
- el registro sea recuperable tras reinicio y lectura desde una sesión nueva;
- permisos, retención, respaldo y saneamiento estén probados;
- la evidencia esté vinculada a commit, fixture, versión y hashes.

### Límites que permanecen vigentes

- No cambiar `docs/manifest.json` ni `execution_status: "fixture"`.
- No implementar cálculo real de potencia ni seleccionar fórmula mediante este documento.
- No modificar `labs/lab_engine.py`, workflows de producción, migraciones ni RPC.
- No ejecutar hipótesis reales ni consultar/escribir Supabase.
- No considerar E6–E11 aprobadas por la existencia de esta propuesta.
- Cualquier implementación futura requiere una autorización explícita separada después de la auditoría documental y de infraestructura.
