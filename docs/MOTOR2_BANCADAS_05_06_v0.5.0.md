# Motor 2: Bancadas 05 y 06 (PEMFC ModelLab v0.5.0)

Ninguna de las dos bancadas introduce ecuaciones. Ambas evalúan `pemfc_core.model` (Motor 1) con los parámetros del perfil calibrado, mediante el `StackModel` de la v0.4.0 (`simulation/scenarios.build_model`). Los óptimos se calculan con la función de la Bancada 04 (`benches.run_optimization`).

## 1. Qué variables admite el modelo

| Tipo | Variables | Cómo entran en las ecuaciones |
|---|---|---|
| **Operacionales** (cambios físicos realizables) | T [K] | Nernst (−0,85 mV/K·(T−T_ref) + RT/2F·ln…), activación (ξ₂T, ξ₃T·ln i, ξ₄T·ln c_O₂), R_mem(T) = R_ref·(T/T_ref)^n, coeficiente de concentración a(T) |
| | P de cátodo [atm abs] | **Solo a través de c_O₂ = y_O₂·P / H(T)** en la activación. En Nernst se cancela: ln[p_H₂·√(y_O₂·P)/(p_H₂O·√P)] = ln[p_H₂·√y_O₂/p_H₂O] |
| | p_H₂ [atm] | Nernst (RT/2F·ln p_H₂) |
| | y_O₂ [–] | Nernst (RT/4F·ln y_O₂) y activación (ξ₄T·ln c_O₂) |
| **Parámetros del modelo** (perturbación **matemática**) | ξ₁–ξ₄, R_mem,ref, n_R, a_ref, a_T, b, p_H₂O, piso de j | Coeficientes identificados o fijados. Perturbarlos estudia el modelo, **no** un cambio realizable del dispositivo |

**Respaldo de las variables.** Las curvas de calibración usan los valores globales de p_H₂ y de y_O₂ del perfil. Por eso cualquier otro valor de p_H₂ o y_O₂ es **extrapolación**: no hay ensayos que lo respalden.

## 2. Bancada 05: sensibilidad y comparación de escenarios

### 2.1 Comparación de escenarios
- **Definición.** Un escenario tiene nombre, estado activo, T, P, p_H₂ e y_O₂ opcionales y, opcionalmente, parámetros perturbados (marcados como análisis matemático).
- **Edición.** En una tabla editable se pueden crear, renombrar, eliminar, activar y desactivar escenarios. Hay botones para **duplicar** un escenario y para **generar un mapa** con él en la Bancada 06. Las configuraciones anteriores se recuperan desde el historial con «Duplicar configuración».
- **Dominio común.** Todos los escenarios se evalúan sobre el **mismo** j ∈ dominio calibrado. Si un escenario produce V ≤ 0, esa parte de su curva no se dibuja y se avisa.
- **Gráficos:** V–j, P–j, ΔV y ΔP respecto a la referencia (a igual j) y η–j. Pulsar la leyenda oculta o muestra escenarios.
- **Indicadores por escenario:**
  - P_máx con **su propio** j y su restricción;
  - V, P, H₂ y η en **j_ref común**;
  - variaciones porcentuales respecto a la referencia;
  - validez: «condición calibrada», «condiciones no ensayadas (interpolación)» o «extrapolado»;
  - indicador de perturbación matemática.

### 2.2 Sensibilidad (determinista)
- **Respuestas disponibles:** V_celda(j_eval), P(j_eval), η(j_eval), P_máx y j(P_máx).
- **Método.** Barrido **uno a uno** (OAT), con n puntos en el intervalo elegido para cada variable y las demás en su valor base.
- **Sensibilidad absoluta.** dR/dx por diferencias centrales con paso h = 10⁻⁴·(máx − mín), en el valor base.
- **Elasticidad.** (dR/dx)·x₀/R₀, que **no se calcula** en tres casos, siempre con un aviso:
  - x₀ ≈ 0;
  - R₀ ≈ 0;
  - x₀ fuera del intervalo.
- **Tornado.** Muestra R(mín) − R₀ y R(máx) − R₀ para cada variable. La variable dominante es la de mayor amplitud **en los intervalos elegidos**, así que el orden depende de esos intervalos.
- **Intervalos por defecto** (editables; son elecciones del análisis, no datos del dispositivo):
  - T ± 10 K;
  - P y p_H₂ ± 20 %;
  - y_O₂ ± 0,02;
  - parámetros ± 2σ si el perfil trae su error estándar, y si no ± 10 %.
- **Aviso de identificabilidad.** Los parámetros identificados de forma no robusta según los diagnósticos del perfil llevan un aviso.

### 2.3 Incertidumbre estadística (distinta de la sensibilidad)
- **Disponibilidad.** Solo existe si el perfil contiene `diagnostics.parameters[].std_error` finitos y positivos y `diagnostics.correlation`. **Si falta, no se ofrece**: se explica el motivo y se remite a la sensibilidad determinista. No se inventan incertidumbres.
- **Covarianza.** Σ = diag(σ)·R·diag(σ), solo para los parámetros **libres**, en la base estadística declarada por el perfil (`covariance_basis`).
- **Monte Carlo.** N muestras θ ~ N(θ̂, Σ) con una semilla, lo que hace el resultado reproducible. Se obtienen bandas de V y P entre los percentiles 2,5 % y 97,5 %, y la distribución de P_máx.
- **Limitaciones declaradas:**
  - es una aproximación lineal-gaussiana local;
  - los parámetros fijados se tratan como exactos;
  - no incluye incertidumbre de condiciones ni de geometría;
  - con residuos sistemáticos la covarianza **subestima** la incertidumbre real, y se avisa.

## 3. Bancada 06: mapas operacionales

- **Ejes admitidos:** j × T, j × P, j × p_H₂, j × y_O₂ y T × P. En el mapa T × P, las magnitudes puntuales se evalúan a una j fija declarada; además se calcula P_máx sobre j.
- **Condiciones fijas.** Las variables que no están en los ejes se muestran y editan explícitamente.
- **Magnitudes:** V_celda, V_stack, P, η, consumo de H₂, consumo específico (SFC) y margen a restricciones (este solo si hay límites documentados).
- **Categorías de cada celda:**
  - **0, no calculable:** V_celda ≤ 0 tras el recorte, o resultado no finito. Se deja vacía.
  - **1, inadmisible:** calculable, pero viola I_máx, P_máx o V_mín documentados. No se rellena.
  - **2, extrapolada:** calculable y admisible, pero fuera del rango calibrado de j, T o P, o con p_H₂ o y_O₂ distintos de los de calibración.
  - **3, dominio calibrado:** dentro de los rangos de calibración. Es **interpolación** entre condiciones ensayadas; las condiciones realmente ensayadas se superponen en el mapa.
- **Resolución.** El usuario la elige y se muestra una estimación de coste antes de calcular. Los máximos son 40 000 celdas en mapas con j y 4900 en T × P. Una malla de 120 × 40 se calcula en unos 0,2 s.
- **Exploración de puntos.** Al pulsar un punto del mapa, o al introducir sus coordenadas, se evalúa **exactamente** ese punto (sin interpolar): condiciones, I, V, P, η, H₂, SFC, límites violados y categoría. Desde ahí se puede:
  - **enviarlo a la Bancada 04** como condiciones más potencia objetivo, que llega prellenada y lista para ejecutar;
  - **guardarlo como escenario** de la Bancada 05.

## 4. Coherencia con la Bancada 04

- **Mapas con j.** El óptimo de cada fila es `run_optimization`, es decir, el mismo código de la Bancada 04, de modo que es exacto en j. El óptimo global elige la mejor fila y refina la otra variable con una búsqueda acotada entre filas vecinas. La prueba `test_map_masks_extrapolation_and_bench04_consistency` verifica que la Bancada 04, en la condición del óptimo, da **la misma** P y la misma j (igualdad exacta).
- **Mapa T × P.** El óptimo es **aproximado a la resolución de la malla** en T y P, y se declara así con ΔT y ΔP. Es exacto en j, porque se calcula con la Bancada 04 en esa celda.
- **Óptimos en el borde.** Si el óptimo queda en el borde del intervalo explorado, se advierte que **no es un máximo del dispositivo**.
- **Diagnóstico en el mapa.** El último experimento de la Bancada 04 del mismo perfil se superpone en los mapas con j.

## 5. Experimentos, estudio y exportación

- **Experimentos.** Ambas bancadas generan experimentos inmutables y sellados, igual que las bancadas 01–04. Cada experimento guarda la configuración exacta, que permite duplicarlo, más ejes, rangos, resolución, condiciones fijas, matrices, máscaras, óptimos, hipótesis y advertencias.
- **Estudio completo.** Admite las seis bancadas. Las que no están configuradas se omiten con su motivo.
- **Exportación:**
  - **CSV:** escenarios en formato ancho; sensibilidad en formato largo; mapas con una fila por celda (x, y, categoría y magnitudes).
  - **Excel:** indicadores, tablas y **una hoja por matriz** (`Matriz P`, `Matriz category`…).
  - **Figuras:** escenarios, tornado, respuesta, bandas, P_máx, mapa y categorías, en PNG y SVG.
  - **PDF:** informe con escenarios, variaciones, sensibilidades e interpretación; o definición del espacio operacional, mapas, categorías, restricciones y puntos destacados.
  - **ZIP:** todo lo anterior más `experimento.json` (datos para reconstruir los gráficos) y `perfil.json`.

## 6. Limitaciones

- La sensibilidad OAT no captura interacciones entre variables. Un análisis global (Sobol, Morris) no está implementado.
- Las incertidumbres son lineales-gaussianas y solo cubren los parámetros. Una región calculable o de interpolación no está «validada».
- La presión de cátodo influye poco en este modelo, porque solo actúa vía c_O₂: es una propiedad del modelo implementado, no necesariamente del dispositivo real.
- La selección de puntos sobre el mapa usa una capa de puntos superpuesta, submuestreada a unos 3000 puntos en mallas grandes. Las coordenadas también se pueden introducir a mano.

## 7. Actualización desde v0.4.0

1. Sustituya el repositorio por el contenido del ZIP. **No hay dependencias nuevas.**
2. Los experimentos v0.4.0 se conservan sin cambios: el tipo `experiment` es el mismo y las nuevas bancadas solo añaden valores de `bench`.
3. `runner.model_for` admite ahora p_H₂ e y_O₂ en `cond`, delegando en `scenarios.build_model`. Sin esas claves, el comportamiento es idéntico a v0.4.0.
