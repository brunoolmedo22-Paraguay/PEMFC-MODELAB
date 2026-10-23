# Metodología de identificación — PEMFC ModelLab (Motor 1)

## 1. Modelo

Modelo semiempírico estacionario con la estructura reconstruida de Altıntaş & Ertan (OTEKON 2024), tal como
está implementado en `PEM-FC/models/pemfc_model.py` (commit a533432). `pemfc_core/model.py` lo reimplementa
ecuación por ecuación; la equivalencia numérica (|ΔV| < 10⁻¹² V) se prueba contra una tabla generada
ejecutando el código original (`tools/generate_reference_fixture.py`).

V_cell(j, T, P) = E_Nernst − V_act − V_ohm − V_conc; V_stack = N·V_cell; I = j·A.

Ecuaciones exactas: `pemfc_core.model.MODEL_EQUATIONS`. Unidades internas: j [A/cm²], V [V/celda], T [K],
presión absoluta de cátodo [atm]. La densidad en mA/cm² solo aparece dentro del logaritmo de activación.

### Hipótesis heredadas (documentadas, no corregidas, para no romper la reproducción OTEKON)

* Nernst: el término √P del denominador cancela la presión total; el efecto de presión entra por ξ4·T·ln C_O2.
* p_H2 = 1 atm, p_H2O = 0,5 atm, y_O2 = 0,21 son valores globales asumidos; cada curva puede declarar su p_H2 e y_O2.
* t_m y D_H no influyen en V–I (R_mem(T) = R_mem,ref·(T/T_ref)^n_R); se conservan solo por trazabilidad.
* Recortes `max(·,0)` y piso j_floor = 0,010 A/cm² en el logaritmo (regularización del código original).
* Concentración: V_conc = max(a(T),0)·exp(b·j), con b en cm²/A (coeficientes efectivos, no los impresos).

## 2. Datos

Curva V–I o V–j obligatoria. CSV con mapeo de columnas, unidades explícitas (A, mA, A/cm², mA/cm², A/m²;
V o mV, por celda o de stack), condiciones por curva (T en K o °C; presión absoluta o manométrica con presión
ambiente obligatoria) y metadatos (rol, calidad, fuente, procedencia, σ_V opcional). N_cells y A_active solo se
exigen cuando las unidades lo requieren; nunca se infieren. Se registran el SHA-256 del archivo original, cada
transformación, las filas excluidas y las celdas editadas.

Validación estricta: faltantes, no numéricos y no finitos son errores (no se rellenan con cero); corriente
negativa, tensión ≤ 0, V_cell > 1,3 V (probable stack), j > 5 A/cm² (probable mA/cm²), duplicados exactos,
menos de 3 puntos, temperatura y presión fuera de rango físico. Avisos: pocos puntos, j bajo el piso numérico,
tensión creciente, rango estrecho, condiciones fuera del dominio de referencia OTEKON.

## 3. Identificación

Generalización de `calibration/identify_parameters.py`:

* `scipy.optimize.least_squares(method="trf", jac="3-point", loss="linear")`, límites, `x_scale`, tolerancias 10⁻¹².
* Inicios: el inicial y mezclas `w·x0 + (1−w)·U(lb, ub)` con `w ~ U(0,25, 0,75)` y semilla fija (idéntico al
  original). Opcionalmente, un inicio informado por los datos: proyección lineal sobre ξ1–ξ4, R_mem,ref, a_ref y
  a_T (que entran linealmente en V para b y n_R dados), con rejilla en b.
* Objetivo: Σ_c Σ_k [w_c (V_mod − V_obs)/σ_c]² (+ Σ [(θ − μ)/σ_prior]² con priors). Solo tensiones: potencia y
  eficiencia derivan de V y no se cuentan dos veces. Mejor inicio = menor coste.
* σ_c se usa solo si todas las curvas de calibración la declaran; si no, pesos unitarios. **No se traslada la
  σ = 3 mV de OTEKON a otros datos.** Los priors exigen σ declarada.
* Ponderación por punto (como OTEKON) o por curva (cada curva pesa lo mismo).

### Reglas estructurales (antes de optimizar)

| Parámetro | Requisito (si no tiene prior) |
|---|---|
| ξ2, n_R, a_T | ≥ 2 temperaturas distintas en calibración |
| ξ4 | ≥ 2 presiones parciales de O2 distintas |
| todos | puntos + priors > parámetros libres |

E0, t_m, D_H, R, F, T_ref y j_floor nunca son libres (colineales o sin efecto).

### Presets

* **OTEKON**: 9 libres, límites y escalas del original, 16 inicios, semilla 20260720, sin inicio informado.
* **Recomendado**: libres ξ1, R_mem,ref, a_ref, ξ3, b; + ξ2, n_R, a_T con ≥ 2 temperaturas; + ξ4 con ≥ 2 presiones.
  Fijados en valores de referencia OTEKON con origen `ASUMIDO`. Si los puntos no alcanzan, se evalúan los
  subconjuntos de tamaño (puntos − 1) que contienen ξ1 con un ajuste rápido y se elige el de menor RMSE,
  prefiriendo los que no quedan en límites; todo el ranking queda registrado en las notas del perfil. Esta
  selección usa los mismos datos: es una recomendación editable, no una validación.

## 4. Diagnóstico

* Métricas de tensión por celda (RMSE, MAE, máximo, sesgo; error relativo solo si |V| ≥ 0,05 V), por curva y
  global; equivalente de stack si N es conocido; χ² reducido si σ está declarada.
* Test de rachas (Wald–Wolfowitz) sobre los residuos ordenados por j: aviso si z < −2,5 (estructura sistemática).
* Identificabilidad local: SVD del Jacobiano de datos escalado (condición, rango, dirección peor condicionada),
  covarianza local (σ declarada o SSR/(n−p)), correlaciones, proximidad a límites, dispersión entre inicios de
  coste equivalente (≤ 1,01 × mejor), dominancia del prior. Clasificación por parámetro:
  `IDENTIFICADO_LOCALMENTE`, `DÉBIL`, `NO_IDENTIFICABLE` (umbrales en `identification/diagnostics.py`).
* Recortes activos (activación o tensión en 0, a(T) < 0) generan aviso.

## 5. Estados

| Estado | Condición |
|---|---|
| `NO_CONVERGIDO` | el mejor inicio no converge (o ninguno es finito) |
| `AJUSTE_INSUFICIENTE` | RMSE de calibración > criterio declarado (por defecto 10 mV/celda, editable) |
| `AJUSTADO_A_CURVA` | convergido y RMSE ≤ criterio |
| `VALIDADO_EXPERIMENTALMENTE` | además, curvas de rol «validación» (no usadas en el ajuste, hash distinto, calidad medida o digitalizada, al menos una en condición no presente en la calibración) con RMSE ≤ criterio de validación |

Una validación solo en las mismas condiciones de calibración se reporta como `VALIDACION_SOLO_MISMA_CONDICION`
(repetibilidad) y no otorga el estado. Datos sintéticos o ilustrativos nunca lo otorgan. La capacidad predictiva
se declara `NO DEMOSTRADA` salvo validación superada, y aun así solo en las condiciones validadas.

Limitación conocida: la aplicación no puede verificar que una curva declarada «medida» sea realmente independiente
de los datos con que se obtuvieron los valores de referencia de los parámetros fijados; esa responsabilidad es del
usuario y queda registrada en la procedencia.

## 6. Qué no hace

No crea perfiles desde datasheet sin curva; los datos de datasheet nunca entran en la función objetivo (a
diferencia de la ETAPA 3 de EnergyMultimodel, que incluyó un punto nominal Horizon). No digitaliza imágenes.
No implementa el Motor 2.
