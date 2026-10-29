# PR D — Fixtures estadísticos de referencia (candidato)

**Estado:** artefacto documental candidato; pendiente de revisión humana. No autoriza implementación ni ejecución científica real.  
**Contrato:** PR D v2 vigente para los métodos estadísticos; los requisitos adicionales E6–E11 siguen siendo candidatos v3.0 hasta aprobación explícita.  
**Alcance:** fixtures sintéticos D07, D09 y D10 con valores de referencia calculados; no modifica el motor, el manifiesto ni la infraestructura.  
**Seguridad:** mantener `docs/manifest.json` en `execution_status: "fixture"`; no ejecutar hipótesis reales ni escribir en Supabase de producción.

## 1. Entorno de cálculo observado

Los valores de esta versión se calcularon en el siguiente entorno local:

| Componente | Versión observada |
|---|---:|
| Python | 3.13.5 |
| NumPy | 2.3.5 |
| SciPy | 1.17.0 |
| statsmodels | 0.14.6 |
| pandas | 2.2.3 |

**Importante:** la tabla anterior conserva el entorno original donde se calcularon los valores iniciales. Después se añadió una reproducción aislada para Python 3.12 en `requirements/pr-d-statistical-fixtures-py312.txt`, con versiones exactas, y un workflow dedicado. GitHub Actions run [40902480659](https://github.com/LeoJulieta/agente-runner/actions/runs/40902480659) terminó en `success`: instalación, registro de versiones y hashes, pruebas D07/D09/D10 y comprobación de `execution_status: "fixture"` pasaron. El entorno reproducible usa NumPy 2.2.6, SciPy 1.15.3, statsmodels 0.14.5 y pandas 2.2.3. Por tanto, la compatibilidad con Python 3.12 y la reproducción de estos fixtures sí se verificaron en CI; aun así, los valores siguen siendo referencias candidatas hasta revisión humana y no son todavía referencias normativas congeladas.

No usar rangos de versiones abiertos. La futura referencia debe incluir archivo de dependencias con versiones exactas, versión de Python, comando reproducible, y hash del archivo de fixture. Toda actualización del entorno debe requerir revisión de los cambios numéricos.

## 2. D07 — Regresión logística MLE

### Fixture

Modelo: `Y ~ 1 + X`, con predictor binario `X`.

| X | Y=1 | Y=0 | Total |
|---:|---:|---:|---:|
| 0 | 10 | 30 | 40 |
| 1 | 20 | 20 | 40 |

La forma de datos expandida tiene 80 filas: para `X=0`, diez filas con `Y=1` y treinta con `Y=0`; para `X=1`, veinte filas con `Y=1` y veinte con `Y=0`. Incluir intercepto. Estimación por MLE; error estándar convencional de la matriz de covarianza del modelo; contraste Wald bilateral normal; IC del 95 % del coeficiente con `z=1.959963984540054`; los límites del OR son la exponencial de los límites del coeficiente.

### Valores de referencia candidatos

| Campo | Valor |
|---|---:|
| Intercepto `beta_0` | -1.0986122886681104 |
| Coeficiente `beta_1` | 1.0986122886681104 |
| Error estándar de `beta_1` | 0.48304589153964794 |
| Wald `z` | 2.274343510440431 |
| `p_value` bilateral | 0.022945341019457003 |
| IC 95 % de `beta_1` | [0.15185973837035927, 2.0453648389658614] |
| OR | 3.000000000000002 |
| IC 95 % del OR | [1.1639969608711032, 7.731978950584768] |

Los resultados deben compararse con tolerancia numérica explícita aprobada por la suite; no comparar cadenas decimales exactas entre bibliotecas/plataformas. Los estados, método, dimensiones, nombres de campos y reglas de precedencia sí requieren igualdad exacta.

Aserciones adicionales:
- El método primario es logística MLE; Fisher no lo sustituye.
- El valor p es bilateral.
- El IC del OR se calcula exponenciando el IC del coeficiente, no construyendo un intervalo separado en escala OR.
- El fixture no representa una hipótesis real ni demuestra por sí mismo el cumplimiento integral de la Regla 13.7.

## 3. D09 — OLS de ln(Y) con covarianza HC3

### Fixture

Usar las observaciones siguientes como valores de `ln(Y)`; todos los valores de `Y` son positivos.

```python
x = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
ln_y = [
    1.0, 1.2, 0.9, 1.1, 1.3, 0.8,
    1.4, 1.7, 1.5, 1.8, 1.6, 1.9
]
```

Modelo: OLS `ln_y ~ 1 + x`; covarianza `HC3`; contraste bilateral t con grados de libertad residuales; IC del 95 % usando la misma covarianza HC3 y la distribución t. El uso de la distribución t debe declararse explícitamente en la implementación de referencia.

### Valores de referencia candidatos

| Campo | Valor |
|---|---:|
| Intercepto | 1.05 |
| Coeficiente de `x` | 0.6000000000000003 |
| Error estándar HC3 de `x` | 0.11832159566199241 |
| Estadístico t | 5.070925528371099 |
| Grados de libertad residuales | 10 |
| `p_value` bilateral t | 0.0004841718332456544 |
| IC 95 % del coeficiente | [0.3363630556765045, 0.8636369443234961] |

Aserciones adicionales:
- El modelo condicional solo recibe `Y > 0`; los ceros, si existieran en el conjunto general, deben contabilizarse conforme al contrato pero no transformarse con `ln(0)`.
- No cambiar silenciosamente a errores estándar convencionales ni a contraste normal.
- Diagnósticos secundarios no cambian el método primario ni su resultado inferencial.
- La escala del coeficiente y del intervalo es la de `ln(Y)`; cualquier interpretación transformada debe estar explícitamente especificada.

## 4. D10 — Benjamini–Hochberg por familia

### Fixture

Una sola familia con `m=5` hipótesis en una única ventana, con valores p finitos:

```python
p_values = [0.001, 0.010, 0.030, 0.200, 1.000]
```

Orden ascendente ya indicado; no hay empates. El ajuste BH debe conservar los cinco miembros de la familia y aplicar la monotonía de los q ajustados desde el mayor rango hacia el menor.

### Valores q de referencia candidatos

| Hipótesis | p | q BH esperado |
|---|---:|---:|
| H1 | 0.001 | 0.005 |
| H2 | 0.010 | 0.025 |
| H3 | 0.030 | 0.050 |
| H4 | 0.200 | 0.250 |
| H5 | 1.000 | 1.000 |

Aserciones adicionales:
- La decisión en el límite contractual `q <= 0.05` incluye H3.
- No combinar ventanas A y B ni familias distintas.
- Un caso científicamente no estimable que deba aportar `p=1.0` al ajuste conserva su posición y pertenencia a `m`; ese valor es una convención de ajuste, no un p empírico.
- Agregar en una revisión posterior casos de valores p empatados, orden original distinto y verificación de monotonía. No están cubiertos por este fixture mínimo.

## 5. D08, D11 y D12 — diseño de fixtures de borde (candidato)

Los nuevos vectores viven en `tests/fixtures/pr_d_statistical_edge_fixtures_candidate.json` y sus aserciones en `tests/test_pr_d_statistical_edge_fixtures_candidate.py`. El workflow dedicado ejecuta estas pruebas junto con D07/D09/D10. Son fixtures de aceptación sintéticos; no son una implementación del motor ni una aprobación normativa.

### D08 — distinguir no estimabilidad científica de fallo estructural

Se definieron cuatro casos:
- Separación logística reconocida → `SCIENTIFIC_NON_ESTIMABLE`, `p=1.0` exclusivamente para BH, no aborta lote.
- No convergencia reconocida → misma clasificación y convención conservadora.
- Información insuficiente para estimar el modelo → misma clasificación y convención conservadora.
- Excepción inesperada de software/infraestructura → `STRUCTURAL_FAILURE`, sin p parcial y con aborto de lote.

**Límite:** las pruebas actuales validan el clasificador de frontera a partir de clases de resultado simuladas. No demuestran todavía que un estimador real de cada versión de biblioteca sea clasificado correctamente; esa integración pertenece a una fase posterior y sigue fuera del motor de producción.

### D11 — preservar la familia BH congelada

La familia sintética contiene cinco miembros, incluido un miembro no estimable que aporta `p=1.0` por convención contractual. La prueba verifica:
- `m=5` antes y después del ajuste;
- identidad y orden original conservados;
- q ajustados esperados `[0.05, 1.0, 0.1, 0.3333333333333333, 0.625]`;
- ningún miembro eliminado y ningún valor no finito.

Este fixture prueba una familia y una ventana de juguete; no certifica la implementación FDR completa del laboratorio ni todos los casos de empates.

### D12 — gates de efecto, dirección e intervalo: BLOQUEADO

La inspección de `docs/manifest.json` en `main` confirma que el manifiesto actual es explícitamente test-only y `execution_status: "fixture"`. Define familias, IDs de hipótesis, outcomes, contrastes, ventanas y `method_version`, pero no contiene parámetros por hipótesis suficientes para D12: efecto mínimo relevante, dirección esperada, regla/método de IC y `method_fingerprint`.

Por esa ausencia, el fixture D12 **no calcula ni decide** los gates de efecto/dirección/intervalo. Verifica que el estado siga siendo `BLOCKED_PREREGISTRATION_INCOMPLETE` y que no se infieran umbrales. No se inventó un efecto mínimo numérico, una dirección ni una regla de IC. Para desbloquearlo hará falta una preregistración sintética versionada, revisada y coherente con el contrato vigente, con esos valores explícitos antes de observar resultados. No modificar el manifiesto actual para simular una aprobación.

## 6. Criterios para aceptar la congelación

La revisión humana puede aprobar la congelación solo cuando:
1. El entorno aislado con Python 3.12 y versiones exactas se reproduce desde cero; **cumplido en CI run 40902480659**.
2. Los fixtures D07/D09/D10 coinciden dentro de las tolerancias documentadas; **cumplido en CI run 40902480659**.
3. El método, la distribución del contraste, el nivel del intervalo y la convención de ajuste están explícitos.
4. El CI registra los hashes de los fixtures y del archivo de dependencias; **cumplido en CI run 40902480659**.
5. El CI valida estos fixtures sintéticos sin invocar el motor científico ni acceder a Supabase de producción; **cumplido por alcance del workflow**.
6. D08, D11 y D12 siguen marcados como pendientes hasta que tengan datos, resultados y aserciones verificables.
7. No se cambia `execution_status: "fixture"` ni se habilita ejecución de hipótesis reales; el workflow confirmó que el manifiesto conserva ese estado.
8. La revisión humana aprueba explícitamente las referencias y tolerancias antes de considerarlas normativas.

## 7. No incluido

Este documento y la suite agregada no implementan los modelos en `labs/` ni conectan con Supabase. El workflow agregado solo ejecuta fixtures sintéticos y usa dependencias aisladas. No cambia el contrato v2, no aprueba E6–E11, no desbloquea T24c ni certifica la cobertura de toda la matriz T01–T32.


### D12 — preregistro sintético separado y pruebas positivas/negativas (candidato)

Se agregó `tests/fixtures/manifest_d12_test.json` como archivo independiente. **No reemplaza ni modifica `docs/manifest.json`**. Está marcado con `status: "candidate"`, `authority: "illustrative_not_normative"` y `execution_authorized: false`.

El preregistro sintético fija antes de evaluar los resultados de prueba:
- estimando/escala: odds ratio;
- efecto mínimo relevante ilustrativo: OR ≥ 1,5;
- dirección esperada ilustrativa: `greater` (OR > 1);
- IC del 95 % ilustrativo, Wald normal sobre log(OR), exponenciado, con regla de gate `ci_low > 1.0`;
- valor q BH ≤ 0,05 dentro de una familia/ventana sintética con m=1;
- mínimos operativos sintéticos: n_eff ≥ 30 y al menos 5 eventos por ventana;
- identificador de método placeholder, marcado explícitamente como **no hash criptográfico real**.

Los números y las reglas de este archivo sirven exclusivamente para ejercitar el código de prueba. No son valores normativos del contrato PR D v2 ni una aprobación de E6–E11. La prueba evalúa una función auxiliar aislada, no el motor científico.

Casos cubiertos:
- **D12-POSITIVE-OR-2:** OR=2,0; IC [1,6; 2,5]; q=0,005; mínimos operativos cumplidos → todos los gates sintéticos pasan y resultado esperado `PROMETE`.
- **D12-NEGATIVE-OR-1-2:** OR=1,2; IC [0,9; 1,4]; q=0,2; mínimos operativos cumplidos → falla el efecto mínimo, el límite inferior del IC y el gate FDR; resultado esperado `RECHAZA`.
- **D12 incompleto:** la prueba conserva el control negativo sobre el manifiesto oficial: como no tiene los parámetros por hipótesis, permanece `BLOCKED_PREREGISTRATION_INCOMPLETE`; no se infieren valores desde el fixture sintético.

El workflow registra también el hash del manifiesto sintético y ejecuta estas pruebas en el mismo entorno aislado. La comprobación final continúa verificando que `docs/manifest.json` conserve `execution_status: "fixture"`.

**Límite estadístico:** esta prueba verifica la lógica de comparación con resultados resumidos ya proporcionados; no demuestra que la estimación logística real produzca dichos valores ni que el método/criterio sea normativamente correcto. Esa validación sigue fuera del alcance del PR #98.
