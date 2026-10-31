# Verificación — digitalizador v0.2.0

Todas las cifras proceden de ejecuciones reales del 2026-10-26 en este entorno. Estado por criterio: **OK** (ejecutado
y superado), **PARCIAL** (superado con la salvedad indicada), **NO** (no superado) o **BLOQUEADO** (no ejecutable
aquí).

## Entorno

- Python 3.12.3, con las versiones exactas de `requirements.txt`: streamlit 1.66.1, numpy 2.4.4, pandas 3.0.2,
  scipy 1.17.1, plotly 7.1.0, matplotlib 3.10.8, pillow 12.1.1, opencv-python-headless 4.13.0.92; pytest 9.1.1.
- Navegador real: Chromium headless (Playwright 1.56) contra `streamlit run app.py`, ventana de 1440 × 1000.
- Scripts reproducibles en `tools/e2e/`. Resultados en `docs/resultados_digitalizador/e2e/`. Capturas en
  `docs/capturas/digitalizador/`.

## Pruebas automatizadas

| Conjunto | Pruebas | Resultado |
|---|---:|---|
| Suite original v0.1.0 | 70 | 70 aprobadas. Se cambió una sola aserción: la que exigía el aviso «no está implementada» ahora exige el botón «Abrir digitalizador» |
| `tests/test_digitizer.py` (núcleo, sin Streamlit) | 34 | 34 aprobadas |
| `tests/test_digitizer_app.py` (`AppTest`) | 6 | 6 aprobadas |
| **Total `python -m pytest -q`** | **110** | **110 aprobadas** (≈ 45 s) |

Reproducción OTEKON con `python tools/reproduce_otekon.py`: RMSE 0,001411370003308996 V/celda, idéntico al
original (Δ = 0,0 V; la tolerancia de la prueba es 1 µV). `pemfc_core/model.py` conserva su SHA-256
`00b0643a…dac`, y `identification/` no cambia. En `pemfc_core/schemas.py` solo cambia `APP_VERSION` (0.2.0).

## Exactitud de la digitalización (error de imagen → datos; NO de ajuste)

Comando: `python tools/evaluate_digitizer.py`. Usa el evaluador oficial **sin modificar**
(`tools/handoff/evaluar_extraccion.py`): RMSE en la intersección de dominios X frente a `*_truth.csv`. Resultados
en `docs/resultados_digitalizador/`, con 40 puntos por curva.

Los dos modos son:
- **A, automático:** trazo y posiciones de las anclas automáticos; valores escritos como los leería una persona en
  los rótulos.
- **B, anclas corregidas:** posiciones de las anclas del manifiesto. Aísla el error del trazo del de colocación de
  las anclas.

| Fixture (sintético) | Curva | A: RMSE / MAE | B: RMSE / MAE | Cobertura X | Desviación de las anclas auto (px) X1, X2, Y1, Y2 | ¿Hubo que elegir candidato? |
|---|---|---|---|---|---|---|
| 01_curva_simple | A | 0,688 / 0,677 mV | 0,065 / 0,030 mV | 100 % | 0,5; 0,5; 1,0; 0,5 | no |
| 02_dos_curvas | A | 0,688 / 0,677 mV | 0,065 / 0,030 mV | 100 % | ídem | **sí** (se preselecciona la roja) |
| 02_dos_curvas | B | 0,616 / 0,604 mV | 0,066 / 0,030 mV | 100 % | ídem | no |
| 03_marcadores_y_ruido | A | 0,691 / 0,675 mV | 0,103 / 0,051 mV | 100 % | ídem | no |

Lectura: en estos gráficos 1 px ≈ 1,21 mV. El error del modo A procede casi por completo de que matplotlib ajusta
ejes y ticks al píxel; en el modo B el trazo es sub-píxel (≤ 0,1 px). Las pruebas imponen A < 1,5 mV, B < 0,3 mV
y cobertura > 97 %.

Otros casos sintéticos, generados en las pruebas con la transformación exacta de matplotlib:
- eje X logarítmico de punta a punta: RMSE < 1 mV y cobertura > 95 %;
- serie de marcadores negros: 7 de 7 marcadores visibles, con error < 1,2 px;
- ejes sin curva: «No se encontró un trazado fiable» y ningún punto inventado;
- curva sin ejes: trazo en píxeles, anclas vacías y conversión física bloqueada.

### Gráfica real no sintética: OTEKON Fig. 3 (4 paneles)

Figura de Altıntaş & Ertan (OTEKON 2024), tomada del repositorio PEM-FC @ a533432. La referencia son los CSV de
`examples/otekon_figure3/`, una digitalización **previa e independiente**. La diferencia mide el **desacuerdo
entre dos digitalizaciones**, no un error frente a la verdad.

| Curva | Panel | Anclas (origen) | Desacuerdo RMSE / MAE | Cobertura | Resolución |
|---|---|---|---|---|---|
| tensao_298K (azul) | 1 | X por ticks, Y por gridlines | 1,57 / 1,45 mV | 99,4 % | 2,12 mV/px |
| tensao_373K (rojo) | 1 | ídem | 1,54 / 1,45 mV | 99,4 % | 2,12 mV/px |
| pressao_1atm (azul) | 4 | X por gridlines, Y por ticks | 1,45 / 1,26 mV | 99,5 % | 2,16 mV/px |
| pressao_5atm (rojo) | 4 | ídem | 1,51 / 1,32 mV | 99,5 % | 2,16 mV/px |

El desacuerdo equivale a ≈ 0,7 px. Límites de esta prueba: no hay valores verdaderos; la figura es una imagen
rasterizada con ejes antialiasados de ~3 px; las leyendas del panel 4 generan candidatos espurios de baja confianza,
que no se seleccionan automáticamente.

**Ajuste electroquímico (otra magnitud).** El Motor 1 con preset OTEKON sobre las 4 curvas re-digitalizadas, con
las mismas condiciones y σ que el ejemplo de la app, da `AJUSTADO_A_CURVA` y un **RMSE de ajuste** de
1,059 mV/celda, frente a 1,411 con la digitalización previa. Mide la distancia del modelo a los datos, no la calidad
de la digitalización, y no es validación experimental.

## Matriz de criterios (`CRITERIOS_ACEPTACION.md`)

### 1 — Flujo visible real

| Criterio | Estado | Evidencia |
|---|---|---|
| «Imagen de una curva» abre un `st.dialog` real y amplio | OK | `width="large"`, ≈ 1280 px en navegador; capturas 00–05 |
| Subir PNG/JPG/WebP dibuja la imagen con superposición y lanza la detección sin segundo clic | **PARCIAL** | En navegador probado con PNG (fixtures y figura real). JPEG y WebP solo con pruebas unitarias (`test_image_formats_and_logged_transformations`). Detección automática: `test_upload_triggers_detection…` y captura 01 |
| «Identificar automáticamente» reintenta al cambiar ROI o color | OK | Navegador: ROI dibujado → reidentificar (pide confirmación por haber ediciones) → puntos solo dentro del ROI (px 602–955); `e2e_lienzo_borrar_pan_roi.json`, captura 13. Parámetros: `test_redetection_keeps_user_anchors…` |
| Elegir curva, ajustar ROI y calibrar con 4 referencias modificables en la imagen | OK | Selector de candidatos (`e2e_escenarios_extra.json`: dos curvas, sin mezcla); anclas por clic con ajuste a tick (Y2 → 90,5 px), por arrastre y por texto (X1 → 150); captura 03 |
| Mínimo y máximo de ejes y de puntos, con unidades; nada ficticio sin calibración | OK | Tabla resumen física o en píxeles; captura 02 (columnas físicas vacías y bloqueadas); `test_no_reliable_trace_and_no_axes` |
| Mover, añadir y quitar puntos en gráfico y tabla; superposición sincronizada; zoom y desplazamiento | OK | Navegador: arrastre, añadir, borrar (modo y Supr), tabla V = 0,9 → py 255,643 y V = 0,88 → py 272,157 (verificado en el estado del **servidor**); desplazamiento de 100 × 50 px de imagen; alineación tras zoom × 5,8 comprobada píxel a píxel sobre gridlines; capturas 04, 04b, 05 |
| Deshacer/rehacer coherentes en trazo y anclas | OK | Navegador: deshacer restaura exactamente el punto 32 sin tocar el 20 y rehacer lo reaplica; Ctrl+Z; prueba unitaria también para anclas |
| Vista previa de línea y puntos, tabla y avisos antes de confirmar | OK | Pestañas Tabla, Vista previa física, Condiciones y Auditoría; panel de avisos; captura 05b |
| Cancelar deja intactos dataset, resultados y calibración | OK | `AppTest`: mismos hashes de curvas, `fit_key`, `profile_id`, objeto `fit_result` y `dataset_label`. Navegador: perfil `pml-bffba1bc…` idéntico antes y después |
| Confirmar añade una curva «digitalizado» sin borrar otras y se calibra con el Motor 1 | OK | Navegador: 4 curvas OTEKON + 1 → Motor 1 → `AJUSTADO_A_CURVA` → ZIP; capturas 06–08 |

### 2 — Exactitud y software científico

| Criterio | Estado | Evidencia |
|---|---|---|
| Transformación píxel ↔ físico sin error de inversión (mínimo, máximo, punto medio) | OK | `test_linear_transform_with_y_inversion_min_max_mid` y round-trip |
| Anclas degeneradas, unidades imposibles, curva vacía, NaN o Inf → errores visibles | OK | Seis casos parametrizados; geometría ausente; punto fuera de la imagen; `test_confirm_errors_do_not_mutate_inputs`. Matiz: mA/cm² con mV produce valores minúsculos que el pipeline acepta (tensión > 0); queda registrado y visible en la vista previa |
| La detección no inventa unidades ni límites sin ticks conocidos | OK | Valores de las anclas siempre vacíos hasta que el usuario los escribe; captura 02 |
| Se registran fuente, SHA-256, ROI, anclas, trazo en píxeles, cambios manuales, método, puntos físicos y unidades | OK | `mapping`, `transformations` y JSON de auditoría (`docs/ejemplo_exportacion_digitalizada/`) |
| Los paquetes exportados incluyen la imagen original y los datos derivados; el perfil sigue importable | OK | ZIP del navegador: imagen, JSON, CSV y overlay en `data/original/`; `load_profile` reproduce el perfil (`test_profile_with_digitized_curve…`) |
| Caso simple, varias curvas, ruido y sin trazado fiable documentados | OK | Tablas anteriores y pruebas |
| Error de digitalización frente a truth, separado del RMSE de ajuste | OK | Sección de exactitud |
| Digitalizado no activa VALIDADO por defecto | OK | Rol por defecto: calibración; prueba y navegador: `SIN_VALIDACION_INDEPENDIENTE` |

### 3 — No regresiones

| Criterio | Estado | Evidencia |
|---|---|---|
| `pytest -q` completo con versiones anotadas | OK | 110/110 |
| `tools/reproduce_otekon.py` mantiene el baseline | OK | Δ = 0,0 V |
| CSV, datos pegados, ejemplos, calibración, resultados y exportación siguen funcionando | OK | Suite original completa aprobada; flujo OTEKON en navegador |
| La interfaz arranca en el navegador; 6 etapas reales capturadas | OK | Capturas 01–06 (más 00, 04b, 05b, 07–13) |
| Sin enlaces externos ni APIs para procesar imágenes | OK | Proceso local; JS sin `fetch`, sin CDN ni importaciones remotas |
| El ZIP corre con instrucciones claras, sin dependencias ni artefactos ausentes | OK | Instalación limpia (sección siguiente); el componente no necesita compilación |

### 4 — Pruebas manuales mínimas (ejecutadas con Playwright)

| # | Prueba | Estado |
|---|---|---|
| 1 | Superposición automática antes de calibrar | OK (capturas 01, 02) |
| 2 | Referencias 0 / 1,5 A/cm² y 0,4 / 1,1 V; mínimos y máximos correctos | OK (ejes 0,0000–1,5024 A/cm² y 0,4000–1,0994 V; ver la limitación de ajuste al píxel) |
| 3 | Arrastrar 3 puntos, deshacer, rehacer, zoom y alineación | OK |
| 4 | Corregir en la tabla y ver el cambio inmediato en el gráfico | OK |
| 5 | Cancelar sin perder datos ni el último ajuste | OK |
| 6 | Reabrir, confirmar, etiqueta «digitalizado» y nuevo hash | OK (SHA-256 normalizado nuevo; resultados invalidados) |
| 7 | Identificación, gráfico observado frente a modelo y perfil con procedencia | OK (captura 07; `provenance` en el perfil) |
| 8 | Imagen sin ejes: conversión bloqueada | OK (captura 12) |
| 9 | Varias curvas: elegir una sin mezcla | OK (captura 10) |
| 10 | Imagen corrupta o muy grande: recuperación | OK. Corrupta en navegador (captura 11); > 25 MP y > 10 MB en prueba unitaria (el uploader de Streamlit ya rechaza más de 10 MB) |

## Errores encontrados y corregidos durante la verificación

1. Escribir el estado de un widget ya creado tras confirmar dejaba el diálogo abierto con una excepción (navegador).
2. `st.rerun(scope="fragment")` fallaba cuando el diálogo se ejecutaba dentro de una ejecución completa (`AppTest`).
3. Tras «Conservar el borrador», volver a subir la misma imagen se ignoraba (revisión y prueba nueva).
4. Etiquetas de ancla que cambiaban según su origen (accesibilidad).
5. **Foco:** tras cada actualización, el modal movía el foco al botón ✕, de modo que Supr y Ctrl+Z dejaban de
   llegar al lienzo y Espacio o Intro podían cerrar el diálogo. El lienzo ahora recupera el foco.
6. **Remontaje:** la primera edición tras subir una imagen remontaba el lienzo, que perdía zoom y foco, porque el
   diálogo cambiaba de estructura. Ahora la estructura es estable: primer evento → reinvocación en 200 ms, misma
   instancia, zoom y foco conservados (teclado y ratón).

## Instalación limpia y despliegue

- Copia del proyecto sin cachés y entorno virtual **nuevo** (`uv venv -p 3.12`), instalado solo con
  `requirements.txt` y `requirements-dev.txt`. Instalación correcta: Python 3.12.3, streamlit 1.66.1,
  opencv-python-headless 4.13.0.92, pillow 12.1.1, numpy 2.4.4, pandas 3.0.2, scipy 1.17.1.
- En ese entorno: `pytest` → **110 aprobadas**; `reproduce_otekon.py` → Δ = 0,0 V.
- `streamlit run app.py` desde la copia limpia: `/_stcore/health` responde `ok`. Prueba de humo en navegador:
  digitalizador abierto, ejemplo OTEKON cargado, 40 puntos detectados, 0 errores de consola, 0 excepciones.
- Nota del entorno de verificación: `python -m venv` se creó sin `pip` porque falta `ensurepip` en el sistema
  base. Se usó `uv`, que instala desde PyPI exactamente las versiones fijadas. En una instalación normal funcionan
  `python -m venv` y `pip install -r requirements.txt`.
- **Streamlit Community Cloud: BLOQUEADO.** El despliegue efectivo requiere una cuenta y autorización que no están
  disponibles aquí. No hay pasos de compilación ni paquetes del sistema necesarios.
