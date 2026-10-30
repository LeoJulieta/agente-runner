# PR D — Propuesta de enmiendas contractuales E1–E5

**Estado:** propuesta para auditoría humana y externa; NO aprobada ni vigente todavía.  
**Contrato base auditado:** archivo local `PR-D-DESIGN.md`, versión contractual PR D v1.  
**SHA-256 del contrato base:** `0d621ff5345b0d8274dcb7c6d31e68ce1bd7ed5f2f9e869853fbb8df61bbc919`.  
**Alcance:** texto normativo únicamente. No autoriza implementación, cambios en `labs/lab_engine.py`, workflows, esquema ni datos de Supabase.  
**Regla de precedencia:** esta propuesta solo será contractual si se aprueba explícitamente, se incorpora a una versión contractual identificable y se audita el contenido exacto publicado.

## E1 — Manifiesto congelado y YAML de hipótesis ausente

### Texto propuesto para complementar §5.1 y §13.1

Antes de iniciar un lote, debe existir un manifiesto versionado en Git que identifique de manera inequívoca la versión del manifiesto, las familias, el conjunto ordenado de hipótesis de cada familia, el número de pruebas (m), los outcomes y contrastes primarios, las ventanas y el contrato/método aplicables. La implementación deberá registrar la referencia exacta del manifiesto (commit o huella criptográfica) utilizada en el lote.

- **Manifiesto ausente, ilegible, corrupto, duplicado de forma ambigua o internamente inconsistente:** fallo estructural; abortar el lote. No presentar resultados parciales como lote válido.
- **Hipótesis declarada en un manifiesto válido cuyo YAML individual está ausente o no puede cargarse:** fallo individual. La hipótesis conserva su identidad y posición en la familia congelada; se asigna (p=1.0) exclusivamente para el ajuste FDR y se registra el motivo `hypothesis_spec_missing` (o un código cerrado equivalente). No se inventan parámetros, métricas ni una evaluación estadística. El estado individual será `INVALID` con causa explícita.
- **YAML presente pero inválido o incompatible con el contrato:** clasificar según el tipo de fallo. Si afecta únicamente esa hipótesis y el manifiesto y la integridad del lote permanecen válidos, conservar su posición con (p=1.0) y causa registrada; si revela una inconsistencia del manifiesto, de la familia congelada o del método común del lote, abortar estructuralmente.

La implementación deberá definir un esquema cerrado para los códigos de causa y probar que una hipótesis individual fallida no desaparece del denominador (m).

### Justificación / cuestión para auditoría

§5.1 permite (p=1.0) para miembros preregistrados sin p válido por insuficiencia individual o modelo no estimable, pero el YAML ausente no está nombrado expresamente. Esta enmienda lo clasifica como fallo individual solo cuando el manifiesto válido demuestra que la hipótesis pertenece al conjunto congelado; no convierte una ausencia de especificación en evidencia científica.

## E2 — Contrato de retorno y clasificación de muestra en §9 y §12

### Texto propuesto

La validación de parámetros precede a la evaluación de suficiencia:

1. Si un parámetro obligatorio falta, no se puede interpretar o viola su dominio contractual —incluido `sample_min <= 0`—, el resultado será `INVALID`, con causa estable y explícita, por ejemplo `parametro_invalido`.
2. Con parámetros válidos, si (n=0) o (n < sample_min), el resultado será `INSUFFICIENT_POWER`. No se clasificará como `INVALID` por el solo hecho de que no haya observaciones suficientes.
3. Solo con parámetros válidos y requisitos mínimos satisfechos se intentará el análisis inferencial preregistrado.

`measure()` devuelve un resultado científico estructurado (estado, métricas y causas); no decide ni oculta el código de salida del proceso. La capa de orquestación clasifica por separado los errores operativos y estructurales. Un campo como `exit_code` dentro del diccionario no tendrá efecto por sí solo: la función de entrada del proceso deberá mapear explícitamente el resultado al código de salida contractual.

## E3 — Persistencia atómica de baseline y evidencia

### Texto propuesto para añadir como regla contractual

Cuando una primera corrida necesita crear un baseline y registrar la evidencia asociada, ambas persistencias deberán cumplir una garantía transaccional de todo-o-nada. Si cualquiera de las operaciones falla, no deberá quedar persistido solo el baseline ni solo la evidencia de esa corrida. Si la implementación no puede garantizar esa atomicidad, la corrida se clasificará como fallo estructural y no se presentará como evidencia completa.

El mecanismo concreto (transacción dentro de una única operación de base de datos, RPC transaccional u otro mecanismo demostrado equivalente) queda sujeto a una revisión técnica previa. La regla no prescribe una RPC antes de verificar esquema, permisos, claves de idempotencia, restricciones, comportamiento de reintentos y concurrencia.

La operación deberá ser idempotente conforme a una clave de corrida definida contractualmente. En concurrencia, si el baseline leído para calcular resultados deja de ser el baseline vigente o entra en conflicto con otro proceso, la operación deberá abortar sin persistencia parcial o recalcular explícitamente usando el baseline definitivo antes de registrar la evidencia. No se permitirá registrar silenciosamente una evidencia calculada contra un baseline distinto del que queda asociado al resultado.

### Condición de aceptación

Pruebas aisladas deben demostrar: fallo entre las dos escrituras sin filas parciales; reintento idempotente sin duplicación; y concurrencia con baselines en conflicto sin evidencia calculada contra una versión distinta. No se harán estas pruebas contra datos reales de producción durante la fase contractual.

## E4 — Códigos de salida y conducta del lote

### Texto propuesto para añadir a §13.1

Los códigos de salida del proceso serán:

- `0`: resultado científico registrado de forma íntegra. Incluye estados científicos `INVALID` e `INSUFFICIENT_POWER` cuando el resultado y su causa se registraron correctamente.
- `1`: error operativo inesperado o no estructural que impidió completar/registrar la corrida individual, sin evidencia de que se haya comprometido la integridad global del lote.
- `2`: fallo estructural que exige abortar el lote, incluyendo los supuestos enumerados en §13.1 y cualquier error no clasificado cuya seguridad estructural no pueda demostrarse.

La clasificación de errores será explícita y conservadora. Los errores desconocidos se tratarán como estructurales por defecto (código `2`). El workflow no deberá absorber códigos de fallo mediante comandos que conviertan el estado del paso a éxito. Debe distinguir entre continuar con un fallo individual admisible y abortar ante un fallo estructural; un lote con fallos individuales deberá producir un resumen/manifiesto de resultados que identifique cada hipótesis, su estado, causa y pertenencia al conjunto congelado. Un lote abortado no se presentará como completo ni válido.

El código de salida describe el estado operativo del proceso/lote, no sustituye el campo científico `status`.

## E5 — Fuente de verdad del manifiesto

### Texto propuesto para complementar §5.1

La fuente de verdad del conjunto preregistrado será un manifiesto versionado en el mismo repositorio Git del laboratorio. Cada ejecución deberá fijar y conservar la referencia exacta al commit del manifiesto o su hash, y verificar que el conjunto de hipótesis ejecutado coincide con el conjunto congelado. No se permite construir (m) a partir de los archivos que casualmente estén presentes en el checkout durante la ejecución.

Una ausencia, modificación no autorizada o discrepancia entre el manifiesto congelado y el conjunto que pretende ejecutar el lote será un fallo estructural. Los cambios a la familia o a (m) requieren un cambio versionado aprobado antes de observar los resultados del lote al que se aplicarán.

## Decisiones y límites pendientes

1. Aprobar, rechazar o modificar E1–E5 por separado; esta propuesta no presupone aceptación automática.
2. Definir el esquema y la ruta definitiva del manifiesto, junto con los campos obligatorios y el procedimiento de versionado.
3. Cerrar los códigos de causa permitidos para fallos individuales y estructurales.
4. Verificar en código y esquema cómo se identifica una corrida, cómo se guarda el baseline y cómo se garantiza atomicidad/idempotencia/concurrencia. La presente propuesta no afirma que ya exista una RPC ni que las garantías estén implementadas.
5. Actualizar la versión contractual solo después de auditoría textual. El contrato base PR D v1 no debe editarse silenciosamente ni tratar esta propuesta como norma vigente.

## Fuera de alcance explícito

- No modificar `labs/lab_engine.py`, workflows ni hipótesis.
- No ejecutar experimentos ni escribir datos en Supabase.
- No implementar ni desplegar RPC, migraciones, triggers o cambios de esquema.
- No fusionar esta rama ni declarar aprobadas las enmiendas.
- Las rutas H3 (YAML ausente) y H5 (`sample_min=0, n=0`) siguen siendo inferencias de lectura estática hasta que se ejecuten pruebas aisladas reproducibles; esta propuesta no afirma que se haya completado una prueba runtime.

## Criterio de salida de la fase documental

La fase documental termina cuando la propuesta está versionada en una rama separada, el diff exacto fue revisado y una auditoría independiente confirma que el texto no contradice el contrato base. La implementación requiere una autorización y una fase de pruebas posteriores independientes.
