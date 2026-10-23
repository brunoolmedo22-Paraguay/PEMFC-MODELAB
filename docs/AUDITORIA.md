# Auditoría de fuentes — PEMFC ModelLab, Hito 1

Fecha de auditoría: 2026-10-22. Auditoría de solo lectura: ningún repositorio original fue modificado
(se trabajó sobre clones locales y sobre una copia temporal para ejecutar el código original).

## 1. Material auditado

| Fuente | Identificación | Acceso |
|---|---|---|
| Paquete `PEMFC_ModelLab_Hito1_Claude_Handoff_v1.0.zip` | README_INICIO, PROMPT, 3 docs, propuesta INPI (DOCX), 3 scripts legados, 1 CSV de ejemplo | completo |
| `brunoolmedo22-Paraguay/PEM-FC` | commit `a533432711182271ee22cc1b5f17e8aed3d1127f` (2026-07-31), 96 commits | clon de lectura |
| `brunoolmedo22-Paraguay/EnergyMultimodelv1.5` | commit `761f032f8c486f3ebeb78536ed7ea1b1ac9818bc` (2026-10-05), 7 commits | clon de lectura |

SHA-256 de los archivos críticos de PEM-FC (HEAD auditado):

| Archivo | SHA-256 |
|---|---|
| `models/pemfc_model.py` | `84086b157e18304daaa16d3adf10978c2e147e068590939cd59283dd3da14857` |
| `pemfc_config/parameters.py` | `51cd27e646ca447d008e3922346d26e1d99b2127783c70bacbd3dc90a8712ad9` |
| `calibration/identify_parameters.py` | `7fbde69fb0e9a853b52f40bbf52f26176eb1627c5d11e17181944132f471f473` |
| `data/otekon_figure3/voltage_298K.csv` | `0852964e…ae3` |
| `data/otekon_figure3/voltage_373K.csv` | `dec10399…5d9b` |
| `data/otekon_figure3/pressure_1atm.csv` | `f8714c80…44f0` |
| `data/otekon_figure3/pressure_5atm.csv` | `3162b569…63b` |

## 2. Comparación entre los archivos legados del ZIP y GitHub

| Archivo legado | Comparación con PEM-FC HEAD | Conclusión |
|---|---|---|
| `legacy_reference/identify_parameters.py` | **Idéntico byte a byte** a `calibration/identify_parameters.py` | Reutilizable como referencia del algoritmo |
| `legacy_reference/pemfc_model.py` | **Diferente**: revisión anterior, densidad de corriente interna en mA/cm², importa módulos (`models.activation`, `models.ohmic`, `models.dynamics`, …) que no existen en HEAD; firma `cell_voltage(i_mA)` sin T ni p | **Incompatible** con el identificador; no se usa |
| `legacy_reference/parameters.py` | **Diferente**: coeficientes impresos del artículo (ξ1 = −0,9514 …), `alpha_H`, `N_cells = 1`, sin `R_mem_ref_ohm_cm2`, `fuel_utilization` ni `A_active_cm2` | **Incompatible** con el identificador; no se usa |

El identificador legado llama `model.cell_voltage(j, T, p)` y usa campos (`R_mem_ref_ohm_cm2`, `concentration_*`, `A_active_cm2`, `fuel_utilization`) que solo existen en HEAD. Esto confirma la advertencia de `FUENTES_Y_PROCEDENCIA.md`: los tres archivos no son un snapshot coherente. **Referencia de implementación adoptada: PEM-FC HEAD.**

## 3. Comparación PEM-FC ↔ EnergyMultimodelv1.5 (`h2_pemfc/`)

* `h2_pemfc/models/pemfc_model.py` difiere de PEM-FC **solo en la línea de import** (`from h2_pemfc.pemfc_config import …`). Ecuaciones idénticas.
* `h2_pemfc/pemfc_config/parameters.py` reorganiza los mismos valores en `ElectrochemicalParameters` + `StackGeometry` y conserva la vista plana `PEMFCParameters`. Valores numéricos por defecto idénticos.
* `h2_pemfc/data/otekon_figure3/` es idéntico (diff recursivo vacío) a `PEM-FC/data/otekon_figure3/`.
* `h2_pemfc/pemfc_config/profiles.py` introduce el concepto de **perfil** (metadatos + parámetros + trazabilidad por parámetro). Se reutiliza la idea, no el código.
* El perfil `EQUIVALENT_65KW_HORIZON_CONSTRAINED` fue calibrado en una “ETAPA 3” cuyo **script no está en el repositorio**; solo quedan los valores finales y la descripción metodológica (`docs/METODOLOGIA_MODELO_HORIZON_APROX.md`). No es posible reproducir esa calibración exactamente (pesos y σ del prior no publicados).
* Esa ETAPA 3 incluyó el punto nominal Horizon (450 A, 145 V) como bloque de residuos. **PEMFC ModelLab no lo replica**: por decisión de alcance, los datos de datasheet no entran en la función objetivo (ver §7).

## 4. Línea base OTEKON ejecutada (no copiada)

El script original se ejecutó en una copia temporal (`python calibration/identify_parameters.py --starts 16`) con Python 3.12.3, NumPy 2.4.4, SciPy 1.17.1, pandas 3.0.2:

* RMSE conjunto de las 4 curvas de tensión: **0,0014113700033089956 V** (coincide con el valor documental 0,0014113700033 V);
* 16/16 inicios con RMSE dentro del 1 % del mejor; condición del Jacobiano escalado 2185,9; tiempo ≈ 3 s.

Suite de tests original: **13 aprobados, 1 fallo** (`test_percentage_error.py`: espera 3 ejes en una figura de zoom y obtiene 1). Es un fallo de visualización, sin efecto en el núcleo matemático. No se corrige en el repositorio original.

## 5. Ecuaciones del modelo HEAD (a preservar)

Densidad de corriente j en A/cm²; i = 1000·max(j, j_floor) en mA/cm² solo dentro del logaritmo de activación.

| Término | Expresión en HEAD |
|---|---|
| Nernst (Eq. 3) | E = E0 − 0,85·10⁻³(T − 298,15) + (RT/2F)·ln[p_H2·√(y_O2·P) / (p_H2O·√P)] |
| C_O2 (Eq. 5) | C_O2 = y_O2·P / (5,08·10⁶·exp(−498/T)) |
| Activación (Eq. 4/6) | V_act = max(−[ξ1 + ξ2T + ξ3T·ln(i) + ξ4T·ln C_O2], 0) |
| Óhmica (Eq. 9–12) | V_ohm = j·R_mem(T), R_mem = t_m/σ, σ = F²D_H·C_H(T)/(RT), C_H = C_H,ref (T/T_ref)^(1−n_R), C_H,ref derivada de R_mem,ref |
| Concentración (Eq. 13) | V_conc = max(a_ref + a_T(T − T_ref), 0)·exp(b·j), b en cm²/A |
| Celda / stack | V_cell = max(E − V_act − V_ohm − V_conc, 0); V_stack = N·V_cell; I = j·A |

Constantes fijas en el código HEAD (no son parámetros): 0,85·10⁻³ V/K, 5,08·10⁶ atm·cm³/mol, 498 K.

## 6. Hallazgos estructurales verificados numéricamente

1. **t_m y D_H no afectan a V–I.** La cadena Eq. 10–12 se reduce algebraicamente a R_mem(T) = R_mem,ref·(T/T_ref)^n_R. Cambiar t_m y D_H produce ΔV = 0,0 exacto. Se conservan solo por trazabilidad; **no son identificables y no se exponen como libres.**
2. **El Nernst HEAD no depende de la presión total.** √P se cancela entre numerador y denominador (E(353 K, 1 atm) = E(353 K, 5 atm) = 1,18105 V). El efecto de presión entra únicamente por ξ4·T·ln C_O2. Se preserva (necesario para reproducir OTEKON) y se documenta como hipótesis del modelo.
3. **E0 y ξ1 son colineales** (ambos desplazamientos constantes). E0 queda fijo; ξ1 absorbe el intercepto.
4. **ξ2 es colineal con el término RT/2F·ln(…) y con ξ1** en una sola temperatura; **ξ4 es colineal con ξ1/ξ2** si no hay al menos dos presiones distintas (ln C_O2 = ln(y_O2·P) + 498/T − ln 5,08·10⁶).
5. **n_R y a_T solo son identificables con ≥ 2 temperaturas.**
6. Recortes no suaves: `max(·,0)` en V_act, en a(T) y en V_cell; piso de 0,010 A/cm² en el logaritmo. Si se activan en los datos, el Jacobiano tiene columnas nulas. El nuevo motor lo detecta y avisa.
7. **OTEKON tiene 3 condiciones distintas, no 4:** `voltage_373K.csv` y `pressure_5atm.csv` son dos digitalizaciones de la misma condición (373,15 K, 5 atm); diferencia media −0,4 mV, RMS 1,2 mV. La identificabilidad de los 9 parámetros descansa en 2 temperaturas y 2 presiones.
8. En el repositorio original, `outputs/validation_metrics.csv` reporta como “validación” métricas sobre los **mismos** puntos usados en el ajuste. ModelLab separa explícitamente ajuste y validación independiente.

## 7. Caso 65 kW (EnergyMultimodel)

Cuatro puntos de stack (180 A, 150 V), (300 A, 147 V), (420 A, 140 V), (540 A, 133 V); 210 celdas; 300 cm²; fuente Chen et al. (2024), CIESC Journal 75(2), DOI 10.11949/0438-1157.20230745. **No es una curva Horizon.** El artículo no da temperatura ni presiones en los metadatos del repositorio: la ETAPA 3 adoptó 353,15 K y presiones nominales Horizon como **hipótesis**. En ModelLab el ejemplo se etiqueta igual (condiciones `ASUMIDO`). Con 4 puntos, a lo sumo 3 parámetros pueden ajustarse con grados de libertad positivos.

## 8. Reutilización decidida

| Elemento | Decisión |
|---|---|
| Ecuaciones de `PEM-FC/models/pemfc_model.py` | Reimplementadas en `pemfc_core/model.py` como funciones puras con condiciones explícitas; equivalencia verificada contra una tabla de referencia generada con el código original (`tests/fixtures/`) |
| Valores de `PEM-FC/pemfc_config/parameters.py` | Reutilizados como perfil de referencia OTEKON y valores iniciales |
| Algoritmo de `identify_parameters.py` | Generalizado (subconjunto libre, priors, ponderación por curva, diagnósticos); el preset OTEKON reproduce exactamente especificaciones, semilla y generación de inicios |
| Datos OTEKON Fig. 3 (4 curvas de tensión) | Copiados a `examples/otekon_figure3/` con hash y procedencia |
| Curvas de potencia/eficiencia OTEKON | **No** se usan en el ajuste (derivadas de V) |
| Inferencia de U_f y N×A | Fuera del Hito 1 (no se ajustan observables derivados) |
| Datos 65 kW | Copiados como ejemplo de stack con procedencia |
| Datos Horizon | No se usan para calibrar |
| Dinámica, BOP, EMS, H₂ | Excluidos (Motor 2) |

## 9. Licencia y atribución

Ninguno de los dos repositorios contiene archivo de licencia. No se presupone licencia abierta ni titularidad exclusiva. ModelLab conserva atribución explícita a los repositorios de origen, a Altıntaş & Ertan (OTEKON 2024) y a Chen et al. (2024). La titularidad y licencia del nuevo proyecto deben ser decididas por el equipo antes de publicarlo.

## 10. Faltantes declarados

* Script de calibración ETAPA 3 (65 kW): ausente; no se inventa.
* Metadatos bibliográficos completos de OTEKON 2024: no verificados en esta auditoría.
* Incertidumbre de medición del caso 65 kW: no declarada en la fuente.
