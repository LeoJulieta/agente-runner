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

**Importante:** estas versiones describen el entorno de cálculo observado, no dependencias fijadas por el repositorio. El workflow actual de gates utiliza Python 3.12 e instala `pyyaml`; no demuestra que el entorno estadístico esté fijado. Por tanto, los valores siguientes son referencias candidatas, no aún una referencia normativa congelada. Antes de aprobarlos, ejecutar el mismo fixture en un entorno aislado con versiones exactas fijadas y comprobar compatibilidad con Python 3.12 o decidir documentalmente otra versión de referencia.

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

## 5. Casos aún no congelados: D08, D11 y D12

No se declaran completos en este documento.

- **D08 — no estimabilidad:** definir por separado fixtures de separación logística, no convergencia, modelo no estimable y excepción inesperada de software/infraestructura. Los tres primeros son resultados científicos; el último es fallo estructural. No equipararlos.
- **D11 — no estimable dentro de BH:** definir una familia fija con miembros estimables y no estimables, preservar `m`, orden y trazabilidad, y verificar que el miembro no estimable aporta `p=1.0` solo al ajuste, según contrato aplicable.
- **D12 — gates de efecto/dirección/intervalo:** tomar efecto mínimo, dirección y criterio de intervalo únicamente del contrato preregistrado de cada fixture. No inventar un nuevo umbral ni ajustar los parámetros después de observar resultados.

## 6. Criterios para aceptar la congelación

La revisión humana puede aprobar la congelación solo cuando:
1. Un entorno aislado instala versiones exactas y registra la versión de Python.
2. Los fixtures se ejecutan desde cero en ese entorno y los valores coinciden dentro de tolerancias documentadas.
3. El método, la distribución del contraste, el nivel del intervalo y la convención de ajuste están explícitos.
4. Se guardan hashes de los fixtures y del archivo de dependencias.
5. El CI valida estos fixtures sintéticos sin invocar el motor científico ni acceder a Supabase de producción.
6. D08, D11 y D12 siguen marcados como pendientes hasta que tengan datos, resultados y aserciones verificables.
7. No se cambia `execution_status: "fixture"` ni se habilita ejecución de hipótesis reales.

## 7. No incluido

Este documento no implementa los modelos en `labs/`, no agrega dependencias al workflow, no cambia el contrato v2, no aprueba E6–E11, no desbloquea T24c ni certifica la cobertura de toda la matriz T01–T32.
