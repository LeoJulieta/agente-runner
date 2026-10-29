# PR D v2 — Tabla de aceptación determinista v2

**Estado:** VERSIÓN FORMAL PARCIAL. Qwen revisó favorablemente los casos enumerados; T24c sigue bloqueado y la tabla no certifica la cobertura integral del contrato ni autoriza implementación.  
**Propósito:** registrar los casos de aceptación corregidos revisados por Qwen para la Regla 13.7. Esta versión formaliza únicamente los casos enumerados; **no sustituye** la matriz de trazabilidad T01–T32 de `docs/PR-D-TRACEABILITY-MATRIX.md` ni afirma que la cobertura contractual integral esté cerrada. Los identificadores T01/T08/T21 aquí pertenecen a la tabla de aceptación histórica y no deben confundirse con los de la matriz T01–T32.  
**Límites:** solo fixtures sintéticos. No se autoriza implementar más código Python, ejecutar hipótesis reales, cambiar docs/manifest.json, cambiar execution_status=fixture ni escribir en Supabase de producción.

## Decisiones de corrección obligatorias

1. T01 usa datos sin separación perfecta; T01b cubre separación perfecta y sigue §16.3: estado INSUFFICIENT_POWER, razón logistic_separation. p=1.0 es solo la entrada conservadora al ajuste BH, nunca un p-valor empírico.
2. T02 congela una referencia numérica HC3 calculada desde Y crudos. La prueba de la primitiva numérica no puede declarar PROMETE con n_eff=10, porque el piso general de PR D es n_eff >= 30; el estado final de hipótesis queda fuera del alcance de este caso numérico.
3. T08 congela el ajuste BH de tres p-valores con q esperados exactamente [0.03, 0.03, 0.03].
4. T21 se separa en T21a y T21b. La precedencia de §16.1–§16.2 determina que un antecedente A con estado INSUFFICIENT_POWER no respalda VERIFICADO; tampoco lo hace un antecedente A incompleto.
5. T16–T18 y T24 deben incluir entradas, criterios y salidas. Los valores indicados como “propuestos” no son datos observados y deben ser aceptados explícitamente por la auditoría antes de congelar la tabla.

## Casos de aceptación corregidos

### T01 — Familia I, logística estimable sin separación

**Entradas sintéticas:** tabla 2×2 con a=15, b=5, c=10, d=20; todas las cuatro celdas son positivas, por lo que no hay separación perfecta. n_total=50, n_eff=50. Contraste binario preregistrado, dirección esperada OR>1, efecto mínimo del fixture OR_min=1.5, q_threshold=0.05, fdr_q=0.03. Para este fixture, la inferencia primaria es logística MLE y Wald bilateral.

**Salidas esperadas:** OR=6.000000000000; SE(log OR)=0.645497224368; z=2.775781833892; p=0.005506914737; IC95% OR=[1.693140196897, 21.262267629088]. Estado esperado: PROMETE, si el resto de los gates del fixture permanece válido. Tolerancia propuesta para las salidas redondeadas: absoluta 1e-10; revisar junto con las versiones de dependencias antes de congelar.

**Aserciones negativas:** no clasificar como separación/no estimabilidad; no sustituir logística por Fisher como método primario; no confundir OR con coeficiente log(OR).

### T01b — Familia I, separación perfecta

**Entradas sintéticas:** X=[0 repetido 30 veces, 1 repetido 30 veces]; Y=[0 repetido 30 veces, 1 repetido 30 veces]; n_total=60 y n_eff=60. El predictor separa perfectamente los resultados.

**Salidas esperadas según §16.3/E8:** status=INSUFFICIENT_POWER; metrics.non_estimability_reason=logistic_separation; el p empírico no se presenta como válido; el valor de ajuste BH para conservar la posición de la hipótesis en la familia es p=1.0. No retirar la hipótesis de m.

**Aserciones negativas:** no etiquetar RECHAZA; no emitir un p-valor empírico como si la estimación fuera válida; no tratar el fallo científico de estimación como error estructural del lote.

### T02 — Referencia numérica Familia II OLS sobre ln(Y), HC3

**Entradas sintéticas exactas:**

- X=[1,2,3,4,5,6,7,8,9,10]
- Y=[2.5,4.8,7.2,9.1,12.5,14.8,18.2,20.1,23.5,25.8]
- Diseño: intercepto y X; outcome transformado ln(Y); cov_type=HC3; use_t=true; n=10.
- Esta es una prueba de la primitiva numérica, no una aceptación de estado final. Como n_eff=10 es inferior al piso contractual 30, no debe inferirse PROMETE a partir de este fixture.

**Referencia calculada en entorno aislado:** statsmodels 0.14.6 y NumPy 2.3.5.

| Campo | Valor esperado |
|---|---:|
| beta_0 | 1.102814110780614 |
| beta_1 / effect_size | 0.239436238706009 |
| SE(beta_0), HC3 | 0.280457530862575 |
| SE(beta_1), HC3 | 0.042039835325956 |
| t(beta_1) | 5.695460908672402 |
| p bilateral(beta_1) | 0.000456764919838 |
| IC95% beta_0, límite inferior | 0.456077884862365 |
| IC95% beta_0, límite superior | 1.749550336698862 |
| IC95% beta_1, límite inferior | 0.142492204601051 |
| IC95% beta_1, límite superior | 0.336380272810966 |
| Cov(beta_0,beta_0), HC3 | 0.078656426617532 |
| Cov(beta_0,beta_1), HC3 | -0.011319445530839 |
| Cov(beta_1,beta_1), HC3 | 0.001767347754234 |

**Residuos de referencia, en orden de X:**

[-0.425959617612467, -0.013070670278785, 0.152958199123370, 0.147715347918157, 0.225733339997599, 0.155195637753404, 0.122553812360076, -0.017584205363652, -0.100739837984577, -0.246802005913127]

**Aserciones obligatorias:** recalcular desde Y crudos; comparar beta, SE, t, p, IC, covarianza y todos los residuos; repetir la operación y comparar los arrays/resultados para determinismo. Tolerancia propuesta 1e-10 con versiones fijadas; si CI usa dependencias distintas, no congelar hasta explicar la diferencia.

### T08 — Benjamini–Hochberg con familia congelada

**Entradas:** una familia y una ventana; m=3; p válidos ordenados [0.01, 0.02, 0.03]; q_threshold=0.05. No se excluye ningún miembro.

**Salidas esperadas:** q=[0.03, 0.03, 0.03] en el mismo orden. Cada q debe derivarse del ajuste BH, no copiarse desde p. A y B no se mezclan.

**Aserciones negativas:** si un miembro no es estimable científicamente, conserva su posición en m y usa p=1.0 solo como entrada del ajuste; si ocurre un error estructural, abortar el lote y no devolver resultados parciales como válidos.

### T16 — Familia I, ventana A supera los gates

**Entradas del fixture de decisión:** window=A; n_eff=45; n_events=12; OR=2.8; IC95% OR=[1.8,4.2] (**IC sintético propuesto para este caso de lógica de gates**); fdr_q=0.04; q_threshold=0.05; dirección esperada OR>1; OR_min=1.5; método y contrato coinciden; sin drift aplicable a la decisión A.

**Salida esperada:** status=PROMETE. Deben conservarse n_eff=45, n_events=12, effect_size=2.8, ci_low=1.8, ci_high=4.2 y fdr_q=0.04. El caso verifica que una A que pasa los gates no se etiquete VERIFICADO por anticipado.

**Pendiente de congelación:** Qwen debe confirmar el IC sintético propuesto y que los gates declarados son exactamente los definidos para el fixture, sin convertirlos en umbrales globales nuevos del contrato.

### T17 — Familia I, comparación temporal compatible A/B

**Entradas sintéticas:**

- A: status=PROMETE; n_eff=45; OR=2.5; IC95% OR=[2.0,3.0]; fdr_q=0.03.
- B: n_eff=48; OR=2.3; IC95% OR=[1.9,2.8]; fdr_q=0.04.
- Mismo hypothesis_id, contract_sha256 y method_fingerprint; A.window=A, B.window=B; ventanas disjuntas; dirección consistente; ambos gates pasan; drift_flag=OK y drift_evaluation_state=complete; q_threshold=0.05.

**Salidas esperadas:** status B=VERIFICADO; reproducible=true; metrics.reproducible_state=reproducible. Los IC se superponen en [2.0,2.8]. Esta superposición es el criterio operativo del contrato, no una prueba formal de equivalencia.

**Aserciones negativas:** si se cambia una sola condición obligatoria (identidad, fingerprint, disjunción, dirección, gates, IC compatibles o drift), no debe conservarse VERIFICADO.

### T18 — B supera gates pero no tiene antecedente A

**Entradas sintéticas:** B.window=B; n_eff=48; OR=2.3; IC95% OR=[1.9,2.8]; fdr_q=0.04; q_threshold=0.05; dirección esperada y efecto mínimo cumplidos; drift_flag=OK y drift_evaluation_state=complete; antecedent_a=null.

**Salidas esperadas:** status=PROMETE; reproducible=false; metrics.reproducible_state=not_evaluable; metrics.reproducibility_reason=antecedent_not_localizable.

**Aserciones negativas:** no emitir VERIFICADO ni RECHAZA únicamente por la ausencia de A.

### T21a — A no supera el piso de información

**Entradas sintéticas:** B supera todos sus gates y tiene datos/contrato válidos; antecedente A tiene status=INSUFFICIENT_POWER, aunque comparta hypothesis_id, contract_sha256 y method_fingerprint.

**Salidas esperadas según §16.1–§16.2:** status B=PROMETE; reproducible=false; reproducible_state=not_evaluable; reproducibility_reason=antecedent_not_localizable. A no es antecedente elegible para VERIFICADO.

### T21b — A es localizable pero carece de un IC obligatorio

**Entradas sintéticas:** B supera sus gates; A coincide en identidad, contrato, fingerprint y window=A, con status=PROMETE, pero ci_low o ci_high está ausente/no finito.

**Salidas esperadas según E6/E7:** status B=PROMETE; reproducible=false; reproducible_state=not_evaluable; reproducibility_reason=antecedent_incomplete. No imputar el IC faltante ni degradar la comparación a incompatibilidad estadística.

**Decisión contractual congelada:** T21b no puede producir status=VERIFICADO con reproducible=false, porque §16.2 establece que VERIFICADO implica reproducible=true.

### T24 — Consistencia de potencia informativa (sin gate en PR D v1)

**T24a, Familia I, diagnóstico EPV sin método formal de potencia preregistrado**

Entradas: n_events=25; número de parámetros del fixture=2; EPV=12.5. EPV se informa como diagnóstico, no como cálculo exacto de potencia. No hay método formal de potencia preregistrado.

Salidas: n_required_power=null; n_required_power_reason=method_not_preregistered; n_required_power_unit=null. No convertir EPV en garantía de potencia ni usarlo como gate.

**T24b, Familia II, supuestos de cálculo incumplidos**

Entradas: Familia II OLS sobre ln(Y), pero la varianza residual requerida para el método de potencia propuesto es nula/no aplicable; no existe una fórmula alternativa preregistrada autorizada.

Salidas: n_required_power=null; n_required_power_reason=assumptions_not_met; n_required_power_unit=null. No fabricar un tamaño requerido.

**T24c, cálculo válido**

**BLOQUEANTE NO RESUELTO:** para congelar este subcaso se necesita especificar antes de ver resultados el método de potencia aplicable, efecto mínimo, alfa, potencia objetivo, diseño/parámetros requeridos y la unidad resultante. El contrato §16.4 prohíbe inventar una fórmula universal o elegirla después de observar resultados. No rellenar n_required_power con un número arbitrario; obtener la definición preregistrada y una salida de referencia verificable antes de aprobar T24.

## Estado de auditoría y condiciones pendientes

- Qwen emitió una revisión favorable de los casos descritos en su auditoría compartida el 2026-10-29. Esta aprobación se registra como revisión externa, no como sustituto de una reproducción independiente por CI.
- La revisión favorable cubre los casos enumerados; no demuestra que esta tabla incluya todos los requisitos del contrato ni cierra la matriz T01–T32.
- Antes de declarar congelada esta versión, fijar formalmente las versiones de dependencias o aprobar la tolerancia numérica de T02 y ejecutar una reproducción independiente en entorno controlado.
- **T24c permanece bloqueante** hasta preregistrar método de potencia, efecto mínimo, alfa, potencia objetivo, parámetros de diseño, unidad y una salida de referencia calculada independientemente. No implementar T24c antes de resolverlo.
- Mantener separados los identificadores históricos de esta tabla y los T01–T32 de la matriz de trazabilidad.
- No iniciar implementación Python adicional ni afirmar que la Regla 13.7 está cerrada hasta que se complete la cobertura contractual, la reproducción independiente y la decisión formal sobre el alcance de congelación.
- El manifiesto continúa en `fixture`; este documento no autoriza ejecución real, cambios de manifiesto ni escrituras en Supabase de producción.


**Nota de control de versión:** la V2 formal de esta tabla es parcial y se revisó contra casos de la rama de auditoría. El contrato congelado en `main` (E1–E5) tiene SHA-256 `0ca1aa8c452b4d2bb974070f71f7ea315e5f4a156b98bc1d9a01f5e3fd019f89`, coincidente con el manifiesto fixture. La rama de auditoría contiene un candidato ampliado con E6–E11 y SHA-256 `21664b7a5c6f24e876fa7072db54e29b12446a64d0f106c9d60f702478fb9cd8`; ese candidato no está referenciado por el manifiesto ni fusionado en `main`. Esta tabla no declara E6–E11 como contrato aprobado de `main` ni autoriza sincronizar hashes, ejecución científica o implementación de producción. T24c y la cobertura integral permanecen pendientes.
