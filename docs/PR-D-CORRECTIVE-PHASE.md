# PR D — Fase correctiva aislada E12

**Estado:** Draft para auditoría; no normativa, no producción y no autorización de fusión.

## Objetivo
Resolver la divergencia de versionado entre las líneas documentales (#90/#107/#109) y cerrar la brecha E2E de E12 sin alterar el contrato vigente.

## Base y aislamiento
- Rama creada desde `main` en el commit `b6dabd7c9aca13aa6832d6eaee193303cdfd5e17`.
- `docs/PR-D-DESIGN.md` debe permanecer idéntico al archivo de `main` (blob SHA esperado: `b18be485058342e7a85eee14fcd4492c9ae09b2a`).
- `docs/manifest.json` debe permanecer idéntico (blob SHA esperado: `6d1bd77a9d87ab60969c6931449b2148c336a5c8`), con `execution_status: fixture`.
- No se toma como base la rama de #109, que hereda el contenido documental de #90.

## Cambios delimitados
1. Sincronizar gobernanza para E6–E12 y matriz SYNC.
2. Incorporar la candidatura v3 E6–E12 sin promoverla a normativa.
3. Actualizar matriz para diferenciar pruebas implementadas, cobertura parcial y límites.
4. Incorporar módulos puros/sintéticos: parser temporal, constructor de cohorte y estimador Familia II HC3.
5. E2E sintético: recurso YouTube simulado → `snippet.publishedAt` y `statistics.viewCount` asociados al `video_id` exacto → captura → ventana 3–6h → cohorte → Familia II. El fixture incluye un recurso señuelo para verificar la asociación por identidad.
6. Mantener prueba PostgreSQL efímera para compare-and-set y concurrencia.\n7. Añadir tests deterministas parciales E6/E7/E10 para antecedentes A, precedencia de estados y tabla de drift. E8, E9 y E11/T13 permanecen expresamente pendientes.


7. Endurecer `evaluate_reproducibility()`: los tres indicadores de control deben ser booleanos exactos; añadir pruebas negativas para cadenas, enteros y nulos.
8. Añadir pruebas directas de `compute_d_init()` para límites, proporciones extremas, datos faltantes y entradas inválidas; corregir la descripción de cobertura de la matriz.
9. Ajustar los filtros de paths del workflow para incluir este documento y el manifiesto, y eliminar la ejecución duplicada del mismo E2E.

## Aceptación verificable
- Tests temporales y de exclusiones pasan (21 tests).\n- Tests sintéticos E6/E7/E10 pasan (20 tests); cobertura parcial, no cierre contractual.
- E2E suficiente devuelve `ESTIMABLE` con HC3 y conteos esperados; el outcome procede del `statistics.viewCount` del video esperado.
- E2E insuficiente devuelve `INSUFFICIENT_POWER` y `bh_input_p=1.0`.
- PostgreSQL efímero demuestra un solo escritor confirmado.
- CI exige `execution_status == fixture`.
- Diff sin cambios al contrato v2 ni al manifiesto.

## Límites
Sin YouTube real, secretos, publicación, Supabase, productor privado, migraciones, RPC, workflows productivos ni ejecución científica. E8 (Familia I/separación), E9 (potencia informativa) y E11/T13 (registro operativo durable) no se implementan ni se declaran cerrados. PostgreSQL es efímero y no certifica Supabase de producción. Primera escritura confirmada no significa captura cronológicamente más temprana.

## Cierre
El resultado es un PR Draft revisable con diffs y checks. No se fusiona ni cambia la autoridad contractual. Promoción v3 e integración productiva requieren autorización separada.