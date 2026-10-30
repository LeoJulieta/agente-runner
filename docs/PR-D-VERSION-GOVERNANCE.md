# PR D — Política de versionado y autoridad contractual

**Estado:** registro documental de gobernanza. No modifica reglas estadísticas, no aprueba una nueva versión y no autoriza implementación.

## 1. Fuente normativa vigente

La única referencia contractual vigente para PR D es:

- `docs/PR-D-DESIGN.md`
- Versión: **PR D v2**.
- Alcance aprobado: **E1–E5**.
- Estado: contrato documental aprobado; implementación del motor estadístico real no autorizada.
- Huella SHA-256 declarada por el manifiesto fixture: `0ca1aa8c452b4d2bb974070f71f7ea315e5f4a156b98bc1d9a01f5e3fd019f89`.

El archivo anterior no debe recibir enmiendas E6–E11 ni cambios de semántica bajo la etiqueta v2. Cualquier modificación contractual requiere una nueva versión identificable, revisión explícita y actualización coordinada de sus referencias únicamente después de aprobación.

## 2. Candidatura v3

`docs/PR-D-DESIGN-V3-CANDIDATE.md` contiene la propuesta E6–E11 para evaluación como PR D v3.0.

Hasta que exista aprobación formal y explícita:

- E6–E11 son propuestas, no reglas normativas vigentes.
- La candidatura no reemplaza, complementa ni reinterpreta automáticamente PR D v2.
- Los fixtures y tests asociados a E6–E11 prueban únicamente los comportamientos sintéticos expresamente cubiertos; no certifican el motor ni autorizan ejecución científica.
- Una revisión favorable de una sección o fixture no equivale a aprobar la versión completa.

## 3. Autoridad de la matriz T01–T32

`docs/PR-D-TRACEABILITY-MATRIX.md` es la matriz de trazabilidad y aceptación **propuesta para la candidatura E6–E11**. Sirve para auditar cobertura, identificar bloqueantes y definir pruebas futuras. No es una fuente contractual independiente y no puede ampliar el alcance normativo de PR D v2.

La matriz debe mantener visibles tres distinciones:

1. **Regla normativa vigente:** requisito que ya pertenece al contrato aprobado v2.
2. **Regla candidata:** requisito propuesto en v3, todavía sujeto a aprobación.
3. **Evidencia de implementación:** código y pruebas que demuestran un comportamiento concreto; no convierte por sí misma una regla candidata en normativa.

Los estados de cobertura (por ejemplo, IMPLEMENTADO, PARCIAL, AUSENTE o BLOQUEADO) describen evidencia localizada para un requisito determinado. No deben agregarse en un porcentaje global que oculte bloqueantes estadísticos u operativos.

## 4. Regla para ramas y pull requests

Un pull request que introduzca E6–E11 dentro de `docs/PR-D-DESIGN.md`, cambie su semántica o reemplace su contenido sin una aprobación contractual v3 debe considerarse incompatible con esta política de versionado.

La revisión debe comprobar:

- que el archivo v2 permanezca idéntico al contenido aprobado;
- que la propuesta v3 esté separada y marcada como no aprobada;
- que la matriz identifique claramente su condición candidata;
- que el manifiesto siga apuntando al contrato v2 y conserve `execution_status: "fixture"`;
- que ninguna edición documental se presente como autorización para implementar, ejecutar hipótesis reales o escribir en Supabase de producción.

Esta regla no determina por sí sola el destino de un PR existente. Cada PR requiere revisión de su diff completo y de su estado real en GitHub.

## 5. Adopción futura de v3

Para promover la candidatura a contrato vigente se requiere, como mínimo:

1. Auditoría línea por línea de las enmiendas y su matriz de aceptación.
2. Resolución documentada de todos los bloqueantes y contradicciones.
3. Revisión metodológica y operativa independiente cuando corresponda.
4. Aprobación explícita de la versión contractual por el usuario.
5. Un cambio versionado separado que establezca la nueva referencia contractual y su huella.
6. Revisión coordinada del manifiesto y de los gates; ninguna actualización automática ni cambio de `execution_status` se presume autorizado.

La aprobación documental de v3 tampoco autorizará por sí sola la implementación del motor real. Esa fase requiere una autorización técnica separada, posterior a la auditoría de infraestructura y a la aceptación de pruebas deterministas.

## 6. Límites vigentes

Mientras no exista una autorización posterior y específica:

- `docs/manifest.json` permanece sin cambios y `execution_status` permanece `fixture`.
- No se ejecutan hipótesis reales.
- No se realizan consultas ni escrituras en Supabase de producción.
- No se modifica el motor, los workflows de producción, migraciones ni RPC.
- No se fusiona un PR por el solo hecho de que sus documentos o fixtures sean coherentes con esta política.
