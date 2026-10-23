# Verificación — PEMFC ModelLab v0.1.0 (Hito 1)

Todas las cifras de este documento proceden de ejecuciones reales realizadas el 2026-10-23. Ninguna se ha copiado
de la documentación histórica.

## Entorno

Python 3.12.3; streamlit 1.66.1, numpy 2.4.4, pandas 3.0.2, scipy 1.17.1, plotly 7.1.0, matplotlib 3.10.8,
pytest 9.1.1 (exactamente las versiones fijadas en `requirements.txt`).

Comprobaciones de despliegue:

* Copia limpia del proyecto (sin cachés) + **venv nuevo** instalado solo desde `requirements.txt` y
  `requirements-dev.txt`: instalación correcta; `pytest` → **70 aprobadas**.
* Servidor real `streamlit run app.py --server.headless true`: `/_stcore/health` → `ok`; sin trazas de error en el log.
* Navegador real (Chromium headless, Playwright) contra ese servidor, con **0 excepciones en pantalla**, en dos flujos:
  1. ejemplo OTEKON → preset OTEKON → calibrar → resultados → exportar;
  2. dispositivo nuevo (20 celdas, 50 cm²) → **subida real de un CSV** de stack (A; V de stack; separador `;`) →
     condiciones → validar → calibrar → resultados.
  Capturas en `docs/capturas/`.
* **No verificado:** versiones de dependencias anteriores a las fijadas (la red del entorno bloqueó la descarga de
  versiones antiguas de pandas y NumPy) y el despliegue efectivo en Streamlit Community Cloud (requiere su
  autorización y una cuenta). Por eso `requirements.txt` fija versiones exactas.

## Suite automatizada: 70 pruebas, 70 aprobadas (13,9 s)

| Archivo | Pruebas | Contenido |
|---|---:|---|
| `test_model.py` | 12 | Equivalencia con el modelo original, propiedades estructurales, stack, condiciones inválidas |
| `test_units.py` | 5 | Corriente, tensión, temperatura, presión (abs./manométrica), área |
| `test_datasets.py` | 18 | CSV `;` y coma decimal, V–j, stack, mA/mV, 9 tipos de datos inválidos, geometría/condiciones faltantes, exclusiones, multicurva |
| `test_identification.py` | 18 | OTEKON, sintético, reglas estructurales, priors, 65 kW, insuficiente, no convergido, validación, determinismo |
| `test_profiles.py` | 9 | Contenido, ida y vuelta, alteración detectada, esquema, sin curva → sin perfil, ZIP, extrapolación |
| `test_app.py` | 8 | Flujos de la interfaz con `streamlit.testing.v1.AppTest` |

## Resultados de referencia

### Equivalencia del núcleo (A05)

Tabla generada ejecutando `PEM-FC/models/pemfc_model.py` @ a533432 (`tools/generate_reference_fixture.py`):
7 vectores de parámetros (referencia + 6 aleatorios dentro de los límites OTEKON) × 5 condiciones × 73
densidades = 2555 puntos. Diferencia máxima: **7,4·10⁻¹⁶ V**. Tolerancia de la prueba: 10⁻¹² V.

### Reproducción OTEKON (A05)

Preset OTEKON (9 libres, 16 inicios, semilla 20260720), comparado con la ejecución del identificador original
realizada en esta auditoría (`tests/fixtures/otekon_baseline/`):

| Magnitud | Original | ModelLab | Diferencia |
|---|---|---|---|
| RMSE conjunto 4 curvas | 0,001411370003308996 V | 0,001411370003308996 V | 0,0 V |
| Condición del Jacobiano escalado | 2185,93 | 2185,93 | < 0,01 % |
| Parámetros (9) | — | — | Δrel máx. 4,1·10⁻¹⁴ |
| Evaluaciones por inicio | — | — | idénticas en los 16 inicios |

Tolerancias de las pruebas: |ΔRMSE| ≤ 1 µV y |ΔV| ≤ 10 µV en cada punto. Justificación: mismo modelo y mismo
algoritmo, por lo que solo cabe ruido de redondeo; 1 µV es 3000 veces menor que la incertidumbre de digitalización
OTEKON (3 mV) y el 0,07 % del RMSE. Tiempo: 0,9 s.

Diagnóstico nuevo sobre OTEKON: a_ref y b se clasifican `DÉBIL` (|ρ| = 0,995). El test de rachas detecta
residuos con estructura sistemática en las 4 curvas (z entre −4,5 y −8,3), aunque el RMSE sea de 1,4 mV.

### Caso sintético (A06) — no es validación experimental

Modelo con parámetros OTEKON, 343,15 K, 1,5 atm, 30 puntos en 0,02–1,2 A/cm², ruido gaussiano σ = 2 mV (semilla 7).
Preset recomendado (ξ1, ξ3, R_mem,ref, a_ref, b): RMSE **1,513 mV**; desviación máxima frente a la curva verdadera
sin ruido **1,94 mV**; condición 615. a_ref y b se marcan `DÉBIL` (|ρ| = 0,998), además del aviso de «una sola
curva». Con los 9 parámetros libres, el ajuste se bloquea antes de optimizar (ξ2, ξ4, n_R, a_T no identificables).

### Stack 65 kW (A03)

Chen et al. 2024: 210 celdas, 300 cm²; conversión verificada j = I/300, V_cell = V_stack/210. Condiciones = hipótesis
de la ETAPA 3 (353,15 K; 120/140 kPag). Con 4 puntos solo caben 3 libres; la selección automática eligió
{ξ1, R_mem,ref, b}: **3,78 mV/celda (0,794 V de stack), error máx. 5,97 mV/celda**. R_mem,ref queda en el límite
inferior (0,005 Ω·cm²) y se clasifica `DÉBIL`: estos datos no determinan la resistencia. No es comparable con el
perfil de la ETAPA 3, que usó además un punto Horizon y un prior cuyo script no está en el repositorio.

### Validación independiente

* OTEKON, reservando `pressao_1atm` (condición ausente en la calibración): `VALIDADO_EXPERIMENTALMENTE`, RMSE de
  validación 1,27 mV. **Solo verifica el mecanismo**: ξ4, fijado, toma el valor de referencia identificado con las
  4 curvas, incluida la reservada.
* OTEKON, reservando `pressao_5atm` (misma condición y misma curva publicada que `tensao_373K`):
  `VALIDACION_SOLO_MISMA_CONDICION` → el estado queda en `AJUSTADO_A_CURVA`. Esta regla se añadió tras detectar
  que la versión anterior otorgaba erróneamente `VALIDADO_EXPERIMENTALMENTE` en este caso.
* Validación con curvas sintéticas → `VALIDACION_CON_DATOS_NO_EXPERIMENTALES`, sin validar.

## Matriz de aceptación

| ID | Resultado | Evidencia |
|---|---|---|
| A01 CSV V–I nuevo | Cumple | `test_app::test_new_stack_csv_without_code_changes`; subida real en navegador |
| A02 CSV V–j | Cumple | `test_datasets::test_vj_handoff_sample_conversion`, `test_mA_cm2_and_mV_units` |
| A03 Stack | Cumple | `test_datasets::test_65kw_stack_conversion`, `test_units` |
| A04 Calibración | Cumple | estados y métricas en `test_identification` |
| A05 OTEKON | Cumple | tabla anterior; `test_otekon_reproduces_original_execution` |
| A06 Sintético | Cumple | `test_synthetic_known_parameters`, `test_single_curve_cannot_free_all_nine` |
| A07 Curva inválida | Cumple | 9 casos parametrizados + geometría/condiciones; `test_invalid_csv_shows_error_and_creates_nothing` |
| A08 Perfil JSON | Cumple | `test_profile_contents`; `docs/CONTRATO_PERFIL.md` |
| A09 Reimportar | Cumple | error de reproducción 0,0 V; alteración detectada |
| A10 ZIP | Cumple | `test_experiment_zip` (13 archivos obligatorios, PNG válido) |
| A11 UI | Cumple | 8 pruebas AppTest + 2 flujos en navegador real |
| A12 Seguridad científica | Cumple | sin ruta datasheet → perfil; datasheet nunca en la función objetivo; estados separados |
| A13 Deploy | Cumple parcialmente | venv limpio, servidor real y navegador verificados; el despliegue en Streamlit Cloud no se ejecutó (requiere su autorización) |

## Limitaciones conocidas

* La aplicación no puede verificar la independencia real de los datos declarados como validación respecto de los
  valores de referencia con que se fijan parámetros.
* La selección automática de subconjunto usa los mismos datos de calibración: es una recomendación editable.
* Los umbrales de diagnóstico (`identification/diagnostics.py`) y el criterio por defecto de 10 mV/celda son
  decisiones de proyecto, no estándares.
* La suite original de PEM-FC tiene una prueba de visualización que falla en su propio repositorio (sin relación
  con ModelLab).
