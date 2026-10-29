# PR-D-DESIGN.md

**Versión contractual:** PR D v2 (contrato documental aprobado; incorpora E1–E5)

**Fecha de congelamiento:** 2026-10-09

**Estado:** contrato documental aprobado y fusionado en `main` mediante PR #75; implementación del motor aún no autorizada
**Alcance:** diseño estadístico y operativo previo a implementación\
**Principio rector:** evidencia primero. Ninguna regla estadística podrá
modificarse después de observar los resultados para favorecer una
hipótesis.

> **Limitación contractual de PR D v1:** "Señal filtrada con pisos
> operativos; sin garantía de potencia al 80%".

## 1. Objetivo y alcance

Definir un protocolo reproducible para evaluar hipótesis sobre
resultados de YouTube Shorts en dos ventanas temporales disjuntas,
controlar los falsos descubrimientos dentro de familias de hipótesis,
distinguir iniciación de magnitud condicional y detectar cambios
temporales que comprometan la reproducibilidad.

Este documento especifica el contrato estadístico y operativo. No
modifica datos históricos ni autoriza por sí solo la implementación. Los
cambios futuros al método deberán identificarse mediante una nueva
versión contractual y una nueva huella de método.

## 2. Familias de hipótesis

### 2.1 Familia I: iniciación

Evalúa si una condición experimental se asocia con la probabilidad de
obtener un resultado positivo, definido como `Y > 0`.

La métrica descriptiva de iniciación es la proporción de observaciones
con `Y > 0`. El análisis inferencial principal utiliza regresión
logística según la sección 6.

### 2.2 Familia II: magnitud condicional

Evalúa la magnitud del resultado entre las observaciones con `Y > 0`. Se
utiliza la transformación natural:

`X = ln(Y)`, para `Y > 0`.

La Familia II no estima el efecto sobre la probabilidad de iniciación y
no debe interpretarse como efecto total. Un resultado no concluyente
sobre magnitud condicional no demuestra ausencia de efecto total.

Cada hipótesis deberá declarar antes del análisis: `family_id`,
población, unidad de observación, outcome primario, predictor o
contraste, covariables, dirección esperada, efecto mínimo relevante,
filtros, ventana, método inferencial y reglas de exclusión.

## 3. Ventanas temporales

-   **Ventana A:** evaluación inicial o de descubrimiento.
-   **Ventana B:** evaluación temporal posterior para examinar
    reproducibilidad.

Las ventanas serán disjuntas y quedarán definidas antes de examinar los
resultados. Una observación no podrá contribuir a ambas ventanas. La
definición del outcome, los filtros y los criterios de elegibilidad
deberán ser iguales entre ventanas, salvo diferencias preregistradas.

La evidencia de B no podrá utilizarse para modificar retrospectivamente
la hipótesis, seleccionar variables ni ajustar umbrales utilizados en A.

## 4. Contrato de datos y tamaños

Cada corrida validará como mínimo:

-   Identidad estable de hipótesis y familia.
-   Esquema y tipos de datos requeridos.
-   Variables requeridas y roles declarados.
-   Ventana temporal, filtros y reglas de elegibilidad.
-   Dirección esperada y efecto mínimo relevante.
-   Método estadístico preregistrado y `method_fingerprint`.
-   Reglas de exclusión y sincronización.
-   Estado de truncamiento y completitud de la muestra.

`n_total` contará los registros candidatos recuperados antes de aplicar
filtros analíticos. `n_eff` contará las observaciones efectivamente
elegibles para el análisis después de aplicar todos los filtros
preregistrados, incluido el filtro de sincronización de 3--6 horas
cuando corresponda.

Para Familia II se registrará `n_events`, cantidad de observaciones
elegibles con `Y > 0`. `n_eff` y `n_events` no son intercambiables: una
muestra puede tener muchos ceros y pocos eventos positivos.

Si una corrida se trunca, deberá declararlo explícitamente. Si el
contrato exige una muestra completa, el truncamiento no declarado
produce `INVALID`. El truncamiento declarado que impida completar una
evaluación individual no aborta necesariamente todo el lote; la
hipótesis conserva su lugar en la familia FDR y recibe `p = 1` para el
ajuste, con motivo registrado, según la sección 5.

## 5. Control de falsos descubrimientos (FDR)

Se aplicará Benjamini--Hochberg a los valores p de cada familia
preregistrada y ventana de evaluación. El umbral será
`q_threshold = 0.05`.

`fdr_q` representa el valor q ajustado de Benjamini--Hochberg; no es la
probabilidad individual de que una hipótesis sea falsa.

### 5.1 Congelamiento de la familia

Antes de examinar resultados se congelarán: - El conjunto de hipótesis
de cada familia. - El número de pruebas `m`. - Los contrastes y outcomes
primarios. - El procedimiento de ajuste. - Las reglas para hipótesis no
evaluables.

Ninguna hipótesis podrá eliminarse de `m` a posteriori por bajo poder,
resultado desfavorable o imposibilidad de estimación.

Cuando un miembro preregistrado no pueda producir un valor p válido por
insuficiencia individual de información o por modelo no estimable, se
utilizará `p = 1.0` en el ajuste y se conservará su posición en la
familia. Este valor es una convención conservadora del protocolo, no un
p-valor empírico. Los fallos estructurales que impidan garantizar la
integridad del lote se tratan según 13.1 y provocan aborto del lote, no
resultados parciales presentados como válidos.

Los valores q se calcularán por familia y ventana, con el conjunto
congelado completo. A y B no se mezclarán en un único ajuste salvo que
una versión contractual futura lo establezca expresamente.

## 6. Métodos inferenciales preregistrados

### 6.1 Familia I: regresión logística

-   Modelo principal: regresión logística por máxima verosimilitud.
-   Contraste principal: Wald bilateral sobre el coeficiente
    preregistrado `β1`.
-   Intervalo de confianza del 95 % para el odds ratio:
    `exp(β1 ± 1.96 × SE(β1))`, usando el error estándar correspondiente
    al método preregistrado.
-   Para predictores binarios podrá informarse una tabla 2×2, odds ratio
    crudo y prueba exacta de Fisher como diagnóstico complementario.
    Fisher no sustituye el contraste principal.

Si el modelo no converge, presenta separación que impida una estimación
válida o no es estimable por falta de información, se registra como no
estimable. No se sustituye silenciosamente por Fisher ni por otro método
posterior a la observación de los resultados.

### 6.2 Familia II: OLS sobre el logaritmo del outcome positivo

-   Modelo principal: OLS sobre `ln(Y)` entre observaciones con `Y > 0`.
-   Contraste principal: t bilateral para el coeficiente preregistrado
    `β1`.
-   Intervalo de confianza del 95 % para `β1` calculado con el mismo
    estimador de varianza que el contraste.
-   Implementación de referencia: Python `statsmodels`, con
    `OLS.fit(cov_type="HC3")` para errores estándar robustos HC3.

HC3 será el método inferencial preregistrado; no se cambiará en función
del resultado de un diagnóstico posterior. Los diagnósticos
descriptivos, incluido Breusch--Pagan si se registra, no cambiarán
automáticamente el método inferencial ni el estado de la hipótesis.

Antes de implementar deberá revisarse si la unidad de observación
satisface razonablemente la independencia requerida por el modelo. Si
existen agrupamientos o mediciones repetidas relevantes ---por ejemplo,
observaciones dependientes del mismo canal, creador o experimento--- el
tratamiento de esa dependencia deberá definirse en el contrato antes de
implementar. HC3 no corrige dependencia entre observaciones ni
especificación incorrecta del modelo.

## 7. Efecto, dirección e incertidumbre

Cada hipótesis deberá fijar antes de ejecutar: - Estimador del efecto. -
Dirección esperada. - Efecto mínimo relevante. - Método y nivel del
intervalo de confianza. - Método para obtener el valor p. - Requisitos
mínimos operativos de muestra y eventos.

Los campos `effect_size`, `ci_low` y `ci_high` deberán corresponder al
estimador y escala definidos en el contrato de la hipótesis. No se
compararán directamente efectos en escalas diferentes sin una
transformación preregistrada.

Un resultado `RECHAZA` significa que la hipótesis no superó los
criterios preregistrados con información suficiente; no demuestra
automáticamente ausencia de efecto.

## 8. Detección de drift en dos dimensiones

El drift entre A y B se evalúa con dos indicadores complementarios.
Estos umbrales son reglas operativas preregistradas; no son leyes
universales ni prueban por sí solos un cambio causal en el algoritmo de
YouTube.

### 8.1 Drift de iniciación

Para cada ventana `W`, `p_W = P(Y > 0 | W)`. Se define:

`d_init = abs(p_A - p_B)`.

Se activa la alerta de iniciación cuando `d_init > 0.10`, es decir, una
diferencia absoluta superior a 10 puntos porcentuales, no un aumento
relativo del 10 %.

`d_init` es una métrica descriptiva de comparación temporal, no un
contraste inferencial independiente salvo que se preregistre otro
análisis específico.

### 8.2 Drift de magnitud condicional

Se usan solo observaciones positivas:

`X_W = ln(Y) | Y > 0, W`.

`Delta_cond = abs(median(X_A) - median(X_B))`.

Para cada ventana:

`s_W = 1.4826 × median(abs(X_W - median(X_W)))`.

La escala agrupada es:

`s_pooled = sqrt(((n_A_plus - 1) × s_A^2 + (n_B_plus - 1) × s_B^2) / (n_A_plus + n_B_plus - 2))`,

donde `n_A_plus` y `n_B_plus` son los números de eventos positivos en A
y B. La constante 1.4826 es la normalización MAD habitual bajo supuestos
de referencia aproximadamente normales; no garantiza una escala positiva
en datos discretos o con empates.

Si ambas ventanas tienen al menos cinco eventos positivos y
`s_pooled > 0`:

`D_cond = Delta_cond / s_pooled`.

Se activa la alerta de magnitud cuando `D_cond > 0.50`.

### 8.3 Reglas de borde para MAD degenerada

No se utilizará `epsilon` para ocultar una escala nula.

-   Si alguna ventana tiene `n_events < 5`, `D_cond = null` y se
    registra
    `metrics.drift_degeneracy = "insufficient_positive_events"`.
-   Si ambas ventanas tienen al menos cinco eventos positivos,
    `s_pooled = 0` y las medianas condicionales coinciden:
    `D_cond = 0.0` y
    `metrics.drift_degeneracy = "scale_zero_medians_equal"`.
-   Si ambas ventanas tienen al menos cinco eventos positivos,
    `s_pooled = 0` y las medianas condicionales difieren:
    `D_cond = null`,
    `metrics.drift_degeneracy = "scale_zero_medians_differ"` y
    `drift_flag = "REGIME_SHIFT_SUSPECTED"`.

No se serializará `Infinity` en JSON/JSONB. Las claves y valores
permitidos deberán formar parte del esquema contractual.

### 8.4 Regla combinada de drift

La alerta se activa si cualquiera de los indicadores evaluables supera
su umbral:

`drift = (d_init > 0.10) OR (D_cond > 0.50)`.

Si `D_cond = null`, el detector utiliza únicamente `d_init` y la
evaluación se declara parcial. Si ningún indicador evaluable supera su
umbral, `drift_flag = "OK"` significa únicamente que no se detectó drift
con los indicadores disponibles; no demuestra estabilidad absoluta.

## 9. Estado de corrida y precedencia

`status` describe el resultado de la evaluación de una hipótesis en una
ventana. El estado y la comparación temporal se mantienen separados.

Precedencia: 1. Contrato o datos inválidos: `INVALID`. 2. Datos válidos
pero requisitos mínimos de información no satisfechos:
`INSUFFICIENT_POWER`. 3. Evaluación suficiente pero no se cumplen los
criterios estadísticos preregistrados: `RECHAZA`. 4. La hipótesis supera
todos los gates en A: `PROMETE`. 5. La hipótesis supera todos los gates
en B y cumple el requisito de antecedente A: `VERIFICADO`.

PR D v1 utiliza pisos operativos de información mínima; no declara que
`n_eff >= 30` garantice potencia. Los gates estadísticos incluyen efecto
mínimo relevante, dirección esperada, intervalo según el contrato,
`fdr_q <= 0.05` y mínimos operativos aplicables.

Una corrida B que supere sus gates pero no tenga evidencia A válida y
compatible se registra como `PROMETE`, con motivo explícito de ausencia
de antecedente. No podrá declararse reproducibilidad temporal.

## 10. Requisito de antecedente y reproducibilidad temporal

`VERIFICADO` en B exige una evaluación previa de la misma hipótesis en
A, con ventanas y contrato compatibles, mismo `method_fingerprint` y
estado A `PROMETE` o `VERIFICADO`. La búsqueda se hará mediante
identidad estable de hipótesis y ventana, no por orden de lectura de
filas.

Se asignará reproducibilidad verdadera solo cuando: - La misma hipótesis
y contrato se hayan evaluado en A y B. - Ambas ventanas superen sus
gates. - La dirección del efecto sea consistente. - Los intervalos
satisfagan el criterio preregistrado de compatibilidad. -
`drift_flag = "OK"`. - Las ventanas sean disjuntas y las huellas de
método compatibles.

La superposición de intervalos de confianza es un criterio operativo de
compatibilidad, no una prueba formal de igualdad o equivalencia de
efectos.

La columna persistida `lab_results.reproducible` conserva el tipo
booleano existente y no requiere migración en PR D. Cuando la
reproducibilidad no sea evaluable, la columna será `false` y
`metrics.reproducible_state` expresará el matiz: - `"reproducible"` -
`"not_reproducible"` - `"not_evaluable"`

Por tanto, la columna booleana no basta por sí sola para distinguir
comparación fallida de comparación no evaluable.

## 11. Esquema de salida

Cada resultado conservará la identidad de la hipótesis, familia,
ventana, método y estado. Campos mínimos en `metrics`:

-   `effect_size`
-   `ci_low`
-   `ci_high`
-   `fdr_q`
-   `n_eff`
-   `n_events`
-   `n_required_power`
-   `family_id`
-   `window`
-   `method_fingerprint`
-   `reproducible_state`
-   `drift_flag`
-   `d_init`
-   `D_cond`
-   `drift_degeneracy`, cuando corresponda

`d_init` se serializa como número JSON de doble precisión (float64 en el
entorno Python), calculado como diferencia absoluta entre las
proporciones observadas de resultados positivos en A y B. El valor
almacenado deberá ser finito; no se utilizará NaN ni Infinity en
JSON/JSONB.

Valores permitidos de `drift_flag`: - `"OK"`: ningún indicador evaluable
superó su umbral. - `"REGIME_SHIFT_SUSPECTED"`: al menos un indicador
evaluable superó su umbral o se detectó degeneración de escala con
medianas distintas. - `null`: comparación no realizada o sin información
suficiente para asignar una conclusión.

Los valores no calculables se representarán como `null` y tendrán un
motivo explícito cuando corresponda. No se sustituirán silenciosamente
por cero.

## 12. Política de potencia de PR D v1 y deuda PR D.2

PR D v1 utilizará pisos operativos preregistrados como gates de
información mínima. Estos pisos no constituyen una garantía de potencia
estadística ni autorizan a afirmar que una hipótesis tiene una
probabilidad del 80 % de detectar el efecto relevante.

Los requisitos mínimos incluirán `n_eff >= 30`, los mínimos de eventos
positivos aplicables y cualquier requisito adicional declarado en el
contrato de la hipótesis. Para evaluar `D_cond` se requiere al menos
`n_events >= 5` en cada ventana; esto es un mínimo operativo, no una
garantía de estabilidad estadística.

`metrics.n_required_power` será informativo cuando el tamaño requerido
pueda calcularse mediante un método preregistrado y sus supuestos sean
aplicables. El campo deberá indicar qué cantidad representa:
observaciones elegibles, tamaño total o eventos positivos requeridos. Si
no puede calcularse o faltan parámetros, será `null` con un motivo
explícito.

Para Familia I, la regla EPV (eventos por parámetro) podrá registrarse
como diagnóstico de información del modelo logístico, pero no se
presentará como cálculo exacto de potencia.

Para Familia II, el cálculo deberá corresponder al contraste OLS sobre
`ln(Y)` y al efecto mínimo relevante preregistrado. La transformación de
Fisher solo se utilizará si el parámetro y el diseño justifican
específicamente su aplicación.

PR D.2 deberá evaluar la incorporación de potencia como gate
obligatorio. Hasta entonces, cada evidencia de PR D v1 deberá declarar:
"Señal filtrada con pisos operativos; sin garantía de potencia al 80%".

## 13. Reglas cerradas de implementación A1--A6

### 13.1 Aborto de lote y fallos individuales (A1)

El lote completo se abortará ante: - Esquema de tabla incompatible con
el catálogo contractual requerido. - Ventana temporal mal formada o
imposible de interpretar. - `method_fingerprint` inconsistente dentro de
un lote que deba utilizar el mismo método. - Fallo de conexión o lectura
que impida garantizar la integridad del conjunto de datos requerido.

El aborto no producirá resultados estadísticos parciales presentados
como válidos.

Los fallos individuales que no comprometan la integridad estructural del
lote no lo abortarán automáticamente. La hipótesis conservará su
posición en la familia FDR y recibirá `p = 1` para el ajuste cuando no
pueda obtenerse un valor p válido por insuficiencia individual de
información o modelo no estimable, con el motivo registrado. Incluye
`INSUFFICIENT_POWER`, separación o falta de convergencia, truncamiento
declarado que impida completar la evaluación y `n_events < 5` para
magnitud condicional. Estos casos no se convertirán en resultados
favorables ni se eliminarán del conjunto congelado.

### 13.2 Serialización de MAD degenerada (A2)

No se serializará `Infinity` en JSONB.

-   Escala agrupada cero y medianas iguales: `metrics.D_cond = 0.0`;
    `metrics.drift_degeneracy = "scale_zero_medians_equal"`.
-   Escala agrupada cero y medianas diferentes: `metrics.D_cond = null`;
    `metrics.drift_degeneracy = "scale_zero_medians_differ"`;
    `metrics.drift_flag = "REGIME_SHIFT_SUSPECTED"`.
-   Menos de cinco eventos positivos en alguna ventana:
    `metrics.D_cond = null`;
    `metrics.drift_degeneracy = "insufficient_positive_events"`.

Las claves y valores permitidos forman parte del esquema contractual y
no podrán inventarse dinámicamente.

### 13.3 Evidencia previa para VERIFICADO (A3)

`VERIFICADO` en B exige una evaluación previa de A para la misma
hipótesis, con contrato y `method_fingerprint` compatibles y estado A
`PROMETE` o `VERIFICADO`. Si B supera sus gates sin antecedente A
válido, se registra `PROMETE` con motivo explícito. No se declara
reproducibilidad.

### 13.4 Compatibilidad con booleano existente (A4)

`lab_results.reproducible` conserva su tipo booleano; PR D no exige
migración para introducir nulos. Cuando la reproducibilidad no sea
evaluable, se almacena `false` y
`metrics.reproducible_state = "not_evaluable"`. Valores permitidos:
`"reproducible"`, `"not_reproducible"`, `"not_evaluable"`.

### 13.5 Métodos inferenciales congelados (A5)

Familia I: regresión logística por máxima verosimilitud, Wald bilateral
para el coeficiente preregistrado e IC del 95 % del OR mediante
exponenciación de los límites del IC del coeficiente. Fisher exacto es
únicamente diagnóstico complementario para predictor binario; no
reemplaza el contraste principal.

Familia II: OLS sobre `ln(Y)` para `Y > 0`, contraste t bilateral e IC
del 95 % usando el mismo estimador de varianza. Implementación de
referencia: `statsmodels`, `OLS.fit(cov_type="HC3")`.

Si el modelo no es estimable conforme al método preregistrado, no se
elegirá otro método después de observar resultados. Se registra la
causa, se conserva la hipótesis en la familia y se aplica A1.

### 13.6 Potencia y mínimos operativos (A6)

PR D v1 fija como objetivo de diseño una potencia del 80 % y un nivel
nominal bilateral de significación de 0.05 para los contrastes
principales, pero no usa la potencia calculada como gate obligatorio.
Antes de ejecutar deberán estar registrados el efecto mínimo relevante y
el método aplicable de cálculo informativo de potencia.

Los mínimos operativos son filtros necesarios, no demostraciones de
potencia. `n_eff >= 30` no es una garantía; tampoco lo es un mínimo
aislado de eventos por parámetro. El ajuste FDR puede exigir más
información para alcanzar la probabilidad de descubrimiento deseada.

`n_required_power` no actuará como gate en PR D v1. Los cálculos no
aplicables o con supuestos incumplidos producirán `null` y un motivo, no
una cifra artificialmente precisa. PR D.2 evaluará el gate de potencia
obligatorio.

### 13.7 Prueba de determinismo contractual

Antes de implementar, cada regla deberá tener al menos un caso de
aceptación con datos de entrada, condiciones, estado esperado y campos
de salida esperados. La implementación se bloqueará si alguna regla
permite dos resultados distintos con los mismos datos y el mismo
contrato.

### 13.8 Potencia informativa y deuda PR D.2

`metrics.n_required_power` será informativo y no bloqueará PR D v1. Para
Familia I, EPV será diagnóstico de información, no fórmula exacta de
potencia. Para Familia II, el cálculo se corresponderá con el contraste
OLS y efecto mínimo preregistrados; Fisher no se aplicará salvo que el
parámetro y diseño lo justifiquen. PR D.2 revisará cuándo y cómo el
requisito de potencia se convierte en gate obligatorio.

### 13.9 Implementación de HC3 y registro de d_init

La implementación de referencia para Familia II será Python
`statsmodels`, usando `OLS.fit(cov_type="HC3")`. El diagnóstico
Breusch--Pagan, si se registra, será complementario y no alterará
automáticamente el método inferencial.

`metrics.d_init` se registrará como número JSON finito de doble
precisión, calculado como `abs(p_A - p_B)`. No se serializarán NaN ni
Infinity.

## 14. Condiciones para autorizar la implementación

La segunda auditoría externa aprobó el diseño para la fase contractual y
PR documental. Antes de implementar, se deberán completar y revisar
pruebas de aceptación para, como mínimo:

1.  Aborto por fallo estructural de lote.
2.  Hipótesis individual no evaluable con `p = 1` y familia FDR
    congelada.
3.  MAD degenerada con medianas iguales.
4.  MAD degenerada con medianas diferentes.
5.  `n_events < 5` y `D_cond = null`.
6.  Ventana B sin antecedente A.
7.  `reproducible = false` junto con
    `reproducible_state = "not_evaluable"`.
8.  `q > 0.05` pese a un efecto puntual grande.
9.  Truncamiento declarado frente a truncamiento no declarado.
10. `n_required_power` calculable frente a no calculable.
11. Consistencia de `method_fingerprint`.
12. Drift detectado por cualquiera de las dos dimensiones.

No se implementará el motor de producción hasta que el contrato esté
versionado en el repositorio y la tabla de pruebas de aceptación haya
sido revisada.

**Regla de cierre:** no se implementará el diseño mientras persista una
ambigüedad que permita que dos implementaciones conformes produzcan
estados o decisiones estadísticas diferentes con los mismos datos.


## 15. Enmiendas contractuales E1–E5 — PR D v2

Esta sección incorpora normativamente E1–E5 al contrato completo PR D v1. En caso de conflicto textual, esta sección complementa y especifica las reglas señaladas; no autoriza modificar el método estadístico fuera de un cambio contractual versionado. Tras la aprobación y fusión del PR documental #75, PR D v2 es la referencia contractual vigente en `main`. Esta aprobación documental no autoriza por sí sola la implementación del motor: siguen vigentes las condiciones técnicas de aceptación de §14 y §15.6.

### 15.1 E1 — Manifiesto congelado y especificación individual ausente

Antes de iniciar un lote debe existir un manifiesto versionado en Git que identifique inequívocamente la versión del manifiesto, las familias, el conjunto ordenado de hipótesis de cada familia, el número de pruebas (`m`), los outcomes y contrastes primarios, las ventanas y el contrato/método aplicables. La corrida conservará la referencia exacta del manifiesto (commit Git o huella criptográfica) utilizada.

- Manifiesto ausente, ilegible, corrupto, ambiguo o internamente inconsistente: fallo estructural; abortar el lote y no presentar resultados parciales como lote válido.
- Hipótesis declarada en un manifiesto válido cuyo YAML individual está ausente o no puede cargarse: fallo individual. Conserva identidad y posición en la familia congelada; se asigna `p = 1.0` exclusivamente para el ajuste FDR y se registra una causa explícita cerrada, inicialmente `hypothesis_spec_missing`. No se inventan parámetros, métricas ni evaluación estadística. El estado individual es `INVALID`.
- YAML presente pero inválido o incompatible: si el fallo se limita a esa hipótesis y no compromete manifiesto, familia congelada ni método común, conservar posición, usar `p = 1.0` para FDR y registrar la causa; si revela inconsistencia estructural, abortar el lote.

La implementación deberá definir un catálogo cerrado de causas y demostrar mediante pruebas que una hipótesis fallida no desaparece de `m`. La asignación `p = 1.0` es una convención conservadora para el ajuste; no constituye un p-valor empírico ni una evaluación científica válida.

### 15.2 E2 — Validación de parámetros, muestra y retorno científico

La validación de parámetros precede a la evaluación de suficiencia:

1. Si falta un parámetro obligatorio, no puede interpretarse o viola su dominio contractual —incluido `sample_min <= 0`—, el resultado será `INVALID`, con causa estable y explícita.
2. Con parámetros válidos, si `n = 0` o `n < sample_min`, el resultado será `INSUFFICIENT_POWER`. La falta de observaciones no convierte por sí sola parámetros válidos en `INVALID`.
3. Solo con parámetros válidos y requisitos mínimos satisfechos se intentará el análisis inferencial preregistrado.

La función de medición devolverá un resultado científico estructurado (estado, métricas y causas). La capa de orquestación clasificará por separado los errores operativos y estructurales. Un campo `exit_code` dentro del resultado no produce por sí solo un código de proceso: la entrada del proceso deberá mapear explícitamente el resultado al código contractual de §15.4.

### 15.3 E3 — Persistencia atómica, idempotencia y concurrencia

Cuando una primera corrida deba crear un baseline y registrar evidencia asociada, ambas persistencias deberán garantizar una operación transaccional de todo-o-nada. Si una de las operaciones falla, no podrá quedar persistido solo el baseline ni solo la evidencia de esa corrida. Si no puede demostrarse la atomicidad, la corrida se clasificará como fallo estructural y no se presentará como evidencia completa.

El mecanismo concreto —transacción dentro de una única operación de base de datos, RPC transaccional u otro mecanismo demostrado equivalente— se decidirá tras revisar esquema, permisos, claves de idempotencia, restricciones, reintentos y concurrencia. Esta regla no presupone que exista una RPC ni autoriza por sí sola crearla.

La operación será idempotente conforme a una clave de corrida definida antes de implementar. Si, por concurrencia, el baseline usado para calcular resultados deja de ser el vigente o entra en conflicto con otro proceso, la operación abortará sin persistencia parcial o recalculará explícitamente contra el baseline definitivo antes de registrar evidencia. No se registrará silenciosamente evidencia calculada contra un baseline distinto del asociado al resultado.

La aceptación requiere pruebas aisladas que demuestren: (a) fallo entre escrituras sin filas parciales; (b) reintento idempotente sin duplicación; y (c) concurrencia con baselines en conflicto sin evidencia calculada contra una versión distinta. Estas pruebas no se ejecutarán contra datos reales de producción durante la fase contractual.

### 15.4 E4 — Códigos de salida y conducta del lote

Los códigos de salida del proceso serán:

- `0`: resultado científico registrado íntegramente. Incluye estados científicos `INVALID` e `INSUFFICIENT_POWER` si el resultado y su causa se registraron correctamente.
- `1`: error operativo inesperado o no estructural que impidió completar o registrar la corrida individual, sin evidencia de compromiso de la integridad global del lote.
- `2`: fallo estructural que exige abortar el lote, incluidos los casos de §13.1 y cualquier error no clasificado cuya seguridad estructural no pueda demostrarse.

La clasificación será explícita y conservadora. Los errores desconocidos se tratarán como estructurales (`2`) por defecto. El workflow no absorberá códigos de fallo mediante comandos que conviertan un paso fallido en exitoso. Deberá distinguir entre continuar tras un fallo individual admisible y abortar por fallo estructural. Un lote con fallos individuales producirá un resumen/manifiesto que identifique cada hipótesis, estado, causa y pertenencia al conjunto congelado. Un lote abortado no se presentará como completo ni válido.

El código de salida describe el estado operativo del proceso/lote y no sustituye el campo científico `status`.

### 15.5 E5 — Fuente de verdad y correspondencia del manifiesto

La fuente de verdad del conjunto preregistrado será un manifiesto versionado en el mismo repositorio Git del laboratorio. Cada ejecución fijará y conservará la referencia exacta al commit del manifiesto o su hash y verificará que el conjunto de hipótesis ejecutado coincide con el conjunto congelado. No se construirá `m` a partir de los archivos que casualmente estén presentes en el checkout.

La ausencia, modificación no autorizada o discrepancia entre el manifiesto congelado y el conjunto que pretende ejecutar el lote será un fallo estructural. Los cambios en la familia o en `m` requerirán un cambio versionado aprobado antes de observar resultados del lote al que se aplicarán.

### 15.6 Condiciones de aceptación documental y límites

Antes de implementar deberán definirse la ruta y el esquema definitivos del manifiesto, sus campos obligatorios, el catálogo cerrado de causas y el mecanismo técnico de atomicidad/idempotencia/concurrencia. La incorporación contractual no demuestra que estas garantías existan en el código o en la base de datos.

La aceptación técnica posterior deberá incluir, como mínimo, pruebas aisladas de: manifiesto ausente/corrupto; YAML individual ausente conservando `m`; parámetro inválido `sample_min <= 0`; muestra válida con `n = 0`; códigos de salida 0/1/2 y error desconocido; workflow que no absorbe fallos estructurales; atomicidad e idempotencia; y concurrencia de baseline. Las pruebas de aceptación existentes en §14 siguen vigentes.

Esta sección no autoriza cambios en el motor, workflows, hipótesis, esquema ni datos de Supabase; tampoco autoriza ejecutar pruebas de escritura en producción. Esas fases requieren revisión técnica y autorización separadas.