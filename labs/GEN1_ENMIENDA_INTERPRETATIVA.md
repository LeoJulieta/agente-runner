# Enmienda interpretativa de Gen 1 (04/10/2026)

**Alcance:** este documento NO modifica resultados, NO modifica código y NO reabre
hipótesis cerradas. Fija la interpretación autorizada de los resultados de Gen 1
(H041–H080, corridas del 28/9/2026) a la luz de la auditoría estadística del dataset
(zero-inflation, restricción de rango y power). El historial de `lab_results` es
inmutable: los status originales quedan como registro de lo que el motor midió y
declaró en su momento.

**Regla de oro:** no estamos corrigiendo retroactivamente los números de Gen 1.
Estamos corrigiendo qué podemos afirmar legítimamente a partir de esos números.

## 1. Los 5 VERIFICADOS de `likes` son evidencia de INICIACIÓN, no de magnitud

H041_EXPR, H046_EXPR, H050_EXPR, H076_DISC y H079_DISC midieron r ≈ 0.6043 entre
`likes` y `views_primeras_3h` en la corrida de Gen 1 del 28/9/2026.

**Universo de la corrida:** 130/145 filas con `likes = 0` al momento de esa ejecución.
**Auditoría posterior (28/9):** 132/147 filas con `likes = 0` en el dataset completo
(incluyendo 2 filas adicionales que llegaron entre la corrida y la auditoría).

Un coeficiente de Pearson sobre esa distribución zero-inflated mide principalmente
la separación entre el grupo (likes = 0, views ≈ 0) y el grupo (likes > 0, views > 0).

**Interpretación autorizada:** asociación de iniciación — tener likes > 0 co-ocurre
con tener views > 0. NO es evidencia de una relación dosis-respuesta entre la
cantidad de likes y la cantidad de views.

**Lectura retirada explícitamente:** la caída de r = 0.60 a r = 0.37 al restringir a
`likes > 0` NO demuestra que la relación sea más débil dentro del grupo con
engagement. Esa caída es restricción de rango (Thorndike): al truncar X se reduce su
varianza y el coeficiente se hunde mecánicamente. Cualquier texto anterior que haya
usado esa caída como evidencia sustantiva queda sin efecto.

El rol de catálogo `observational_post_publicacion` sigue vigente: ni antes ni ahora
`likes` es palanca accionable pre-publicación.

## 2. El VERIFICADO de `hs_al_publicar_al_sync` (H071_RECO) es señal de medición, no palanca

Con `hs_al_publicar_al_sync` entre 3.03 y 9.85 horas (deuda D5), esa variable es el
confusor primario del outcome: parte de su correlación con `views_primeras_3h`
(r = 0.219) refleja que a más tiempo hasta el sync, más vistas acumuladas se
observan. Su VERIFICADO se interpreta como evidencia sobre integridad/ventana de
medición, jamás como recomendación de timing.

## 3. Los no-pass de timing NO son evidencia de ausencia

Las hipótesis de `hora_publicacion` (r ≈ 0.1945) y `dia_semana` (r ≈ -0.0283) no
cruzaron sus baselines con N = 145.

**Lectura retirada explícitamente:** cualquier afirmación del tipo "la hora de
publicación no influye" o "el día de la semana no importa".

**Formulación correcta:** "en este dataset y bajo esta especificación correlacional,
`hora_publicacion` no alcanzó el umbral preregistrado". El re-análisis de timing
corresponde a Familia I/II de PR-D-DESIGN.md con sus guard rails de power, no a Gen 1.

## 4. Regla de cita futura

Ningún resultado de Gen 1 puede citarse como hallazgo de MAGNITUD sin re-análisis
bajo Familia II (modelo sobre la cola positiva) de PR D. Los resultados de Gen 1
quedan habilitados únicamente como: (a) registro histórico del instrumento,
(b) evidencia de iniciación para las variables con masa de ceros documentada, y
(c) insumo de preregistro para Gen 2.

## 5. Vinculación

El marco que re-analiza estos datos es `PR-D-DESIGN.md` (Familia I — Iniciación,
Familia II — Magnitud, power por análisis, FDR por `family_id`, covariable
`hs_al_publicar_al_sync`, estabilidad entre ventanas por superposición de ICs).
Esta enmienda y ese diseño son complementarios: la enmienda congela el pasado,
el diseño gobierna el futuro.
