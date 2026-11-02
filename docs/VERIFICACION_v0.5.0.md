# Verificación de PEMFC ModelLab v0.5.0 (Bancadas 05 y 06)

Estados posibles:
- **OK:** ejecutado y superado.
- **PARCIAL:** superado con la salvedad indicada.
- **NO VERIFICADO:** no ejecutado.

Todas las cifras proceden de ejecuciones reales sobre el código final.

## Pruebas automatizadas

`python -m pytest -q` → **238 aprobadas** (también sobre el ZIP en un entorno limpio; ver la última sección).

| Archivo | Pruebas | Contenido |
|---|---:|---|
| `test_exploration.py` (nuevo) | 8 | Verificación analítica de sensibilidades, salvaguardas, escenarios, incertidumbre, máscaras de mapas, coherencia con la Bancada 04, mapa T×P, exportaciones y persistencia, estilo de matplotlib |
| `test_motor2_app.py` | 7 | Seis bancadas en la interfaz (AppTest); escenarios → mapa → Bancada 05 y 04; modos sensibilidad e incertidumbre; estudio completo con omisiones |
| Resto (v0.1–v0.4.0) | 223 | Sin regresiones. Se actualizaron dos expectativas: el número de bancadas (6) y las bancadas omitidas en el estudio |

**Integridad del núcleo:**
- `pemfc_core/model.py` conserva el SHA‑256 `00b0643a…`.
- `identification/` no cambia respecto a v0.4.0.
- OTEKON da **Δ RMSE = 0,0 V**.

## Verificaciones numéricas y analíticas (`tests/test_exploration.py`)

| Verificación | Resultado |
|---|---|
| ∂V/∂ξ₁ = 1 (activación no recortada) | 0,99999999997 (abs. 1e‑8) |
| ∂V/∂R_mem,ref = −j·(T/T_ref)^n | coincidencia relativa 1e‑8 |
| ∂V/∂y_O₂ = RT/(4F·y) + ξ₄T/y | coincidencia relativa 1e‑7 |
| Elasticidad de ξ₁ = ξ₁/V₀ | rel. 1e‑7 |
| Valor base fuera del intervalo | elasticidad no calculada, con nota |
| Parámetro débilmente identificado | se advierte |
| Escenario de referencia | ΔV = 0; P_máx = capacidad del modelo = Bancada 04 (rel. 1e‑9) |
| y_O₂ distinto del de calibración | marcado EXTRAPOLADO |
| Perturbación de R_mem,ref | ΔV(j_ref) = −j·ΔR·(T/T_ref)^n exacto; marcada como perturbación matemática |
| Incertidumbre | reproducible con semilla; la nominal queda dentro de la banda del 95 %; aviso de residuos sistemáticos; **sin correlación en el perfil → no se ofrece** (remite a la sensibilidad) |
| Mapa j×T con I_máx = 250 A | celdas con I > 250 A → inadmisibles; j o T fuera de rango → nunca «calibrado»; celdas no calculables sin valor |
| **Óptimo del mapa frente a la Bancada 04** | P y j **idénticas** (igualdad exacta); restricción activa: corriente máxima |
| Punto del mapa | evaluación exacta = `StackModel.power(j)` (rel. 1e‑12) |
| Mapa T×P | óptimo declarado APROXIMADO a la malla; resolución excesiva → error; par de ejes inválido → error |
| Exportación | Excel con `Matriz P` y `Matriz category`; CSV con una fila por celda; ZIP con figuras e informe; experimento sellado recargado exacto |
| Estilo de matplotlib | el Motor 2 no modifica la configuración global (prueba de regresión) |

## Navegador real (Chromium, Playwright)

Scripts en `tools/e2e/` y resultados en `docs/resultados_v0.5.0/`.

| Prueba | Escritorio 1440×1000 | Tablet táctil 1024×768 |
|---|---|---|
| Seis bancadas visibles y abribles | OK | OK |
| Bancada 05: escenarios ejecutados con gráficos | OK | OK |
| Escenario → «Generar mapa con él» → Bancada 06 ejecutada | OK | OK |
| **Clic sobre el mapa selecciona el punto** | **OK** (0,7206 → 0,9575 A/cm²) | **NO**: el toque emulado no genera la selección; las coordenadas se pueden introducir a mano (verificado con AppTest) |
| Punto → «Enviar a la Bancada 04» → ejecución | OK | OK |
| Excepciones / errores de JS | 0 / 0 | 0 / 0 |
| Regresión de las bancadas 01–04 (`e2e_v040_motor2_laboratorio.py`) | OK: carga, ZIP (417 KB), PDF válido, reproducción consistente | — |

## Fallos encontrados por la verificación (corregidos)

1. **Estilo global de matplotlib.** `simulation/report.py` (desde v0.4.0) modificaba ese estilo al importarse. Las figuras generadas después en el mismo proceso, incluidas las del Motor 1, heredaban rejilla y tamaño de fuente. Se detectó porque una prueba de OCR falló según el orden de ejecución. Ahora se usa `plt.rc_context` local, con una prueba de regresión.
2. **Selección de puntos del mapa.** La capa de selección tenía `hoverinfo="skip"`, que en Plotly anula también el clic. Ahora usa `hoverinfo="none"` y marcadores dimensionados a la malla.
3. **Validez de escenarios.** Un escenario en condición calibrada aparecía como «no ensayado» por avisos ajenos a las condiciones.
4. **Mapa T×P.** Fallaba la asignación de celdas individuales.

## No verificado o parcial

- **Selección táctil en tablet:** NO verificada. En Safari de un iPad real podría comportarse distinto que en la emulación; la alternativa por coordenadas sí funciona.
- **Despliegue en Streamlit Community Cloud:** NO verificado, porque requiere la cuenta del usuario. No hay dependencias nuevas.
- **Rendimiento con resoluciones máximas** (40 000 celdas en j×T; 4900 en T×P): solo estimado (≈ 10 s y ≈ 2 s). En la prueba, una malla de 120×40 tardó 0,18 s y una de 30×20 en T×P, 0,25 s.

## Ejecución final sobre el paquete

- **ZIP descomprimido** en un entorno limpio (Python 3.12; dependencias de `requirements.txt`, sin cambios respecto a v0.4.0): **238 pruebas aprobadas**; `reproduce_otekon.py` da Δ = 0,0 V.
- **Árbol de trabajo final:** 238 aprobadas antes de empaquetar.
