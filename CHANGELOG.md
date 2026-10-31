# Changelog

## v0.2.0 — Digitalización asistida e interactiva de curvas de polarización (2026-10-26)

La opción «Imagen de una curva» de **1. Importar curva** deja de ser un aviso y pasa a ser un digitalizador visual
completo dentro de un popup (`st.dialog`). La curva confirmada entra en el mismo pipeline que un CSV. No cambian las
ecuaciones, el Motor 1, la metodología multistart ni el baseline OTEKON. No se implementa el Motor 2.

### Archivos nuevos

| Archivo | Función |
|---|---|
| `digitizer/__init__.py` | Versión (`1.0.0`) e identificador del algoritmo; convención de coordenadas |
| `digitizer/imageio.py` | Carga segura PNG/JPEG/WebP por firma binaria; límites de 10 MB y 25 MP; EXIF y transparencia registrados |
| `digitizer/calibration.py` | Anclas; calibración lineal y log10; validación de degeneración |
| `digitizer/detection.py` | Paneles, ticks y gridlines, leyendas, trazos por color, marcadores, remuestreo sin interpolar huecos |
| `digitizer/draft.py` | Borrador editable (píxeles como fuente), deshacer/rehacer, auditoría, tabla, CSV y JSON |
| `digitizer/confirm.py` | Confirmación vía `build_curve` + `check_curve_set`; artefactos de exportación; overlay PNG |
| `ui/digitizer_view.py` | Diálogo, panel de calibración, tabla sincronizada, vista previa, metadatos, confirmar y cancelar |
| `ui/static/digitizer_canvas.js`, `.css` | Lienzo bidireccional `st.components.v2` (JavaScript sin dependencias, sin CDN ni compilación) |
| `examples/digitizer/` | Dos fixtures sintéticos y la figura real OTEKON Fig. 3, con README de procedencia |
| `tests/test_digitizer.py`, `tests/test_digitizer_app.py`, `tests/digitizer_synth.py` | 40 pruebas nuevas e imágenes sintéticas con transformación exacta |
| `tests/fixtures/digitizer/` | Fixtures y truth del handoff, sin modificar |
| `tools/evaluate_digitizer.py` | Informe de exactitud reproducible (fixtures + OTEKON + Motor 1) |
| `tools/handoff/evaluar_extraccion.py` | Evaluador oficial del handoff, sin modificar |
| `tools/e2e/` | Pruebas Playwright en navegador real |
| `docs/DIGITALIZADOR.md`, `docs/VERIFICACION_DIGITALIZADOR.md` | Guía, algoritmo, limitaciones; verificación por criterio |
| `docs/resultados_digitalizador/`, `docs/capturas/digitalizador/`, `docs/ejemplo_exportacion_digitalizada/` | Evidencias |

### Archivos modificados

| Archivo | Cambio |
|---|---|
| `ui/import_view.py` | La rama «Imagen de una curva» llama a `digitizer_view.render_entry()`; las otras tres vías no cambian |
| `ui/about_view.py` | Texto de alcance actualizado |
| `pemfc_core/schemas.py` | `APP_VERSION = "0.2.0"` (única línea) |
| `requirements.txt` | Añadidos `pillow==12.1.1` y `opencv-python-headless==4.13.0.92` |
| `tests/test_app.py` | Una aserción: ya no espera «no está implementada» y exige el botón «Abrir digitalizador» |
| `README.md` | Alcance, uso del digitalizador, pruebas y despliegue |

Archivos **no** modificados: `pemfc_core/model.py` (SHA-256 `00b0643a…` sin cambios), `pemfc_core/units.py`,
`pemfc_core/parameters.py`, todo `identification/` y los datos de `examples/` existentes.

### Decisiones

- **Componente bidireccional `st.components.v2`** con JavaScript local en línea. `st.components.v1.html` no devuelve
  eventos a Python. v2 está incluido en `streamlit==1.66.1` y no necesita compilación, npm ni CDN.
- **Eventos discretos** al soltar el ratón; zoom y desplazamiento solo en el navegador; Python es la fuente de
  verdad.
- **Píxeles como fuente geométrica.** Los valores físicos se derivan siempre de las anclas vigentes: no hay doble
  conversión al editar anclas.
- **Sin OCR.** Los ticks aportan posiciones; los valores los escribe el usuario. Se admite coma decimal.
- **Calidad fija «digitalizado».** σ_V no tiene valor por defecto: se ofrece la estimación de resolución con su
  origen registrado.
- **Aislamiento.** Única mutación del conjunto: una llamada a `state.set_dataset` tras validar. Cancelar y los
  errores no tocan `curves`, `originals`, `fit_config`, `fit_result`, `profile` ni `dataset_label`.
- **Exportación** reutilizando `originals`, y por tanto el ZIP existente: imagen original intacta + JSON + CSV +
  overlay, sin incrustar la imagen en `profile.json`. No se sobrescriben nombres duplicados.
- **Ningún cambio en `identification/`.** La regla de validación existente ya impide `VALIDADO_EXPERIMENTALMENTE`
  con curvas de calibración solamente. Se añadió una advertencia en la interfaz sobre la independencia de curvas
  extraídas de la misma figura.

### Verificación (resumen; detalle en `docs/VERIFICACION_DIGITALIZADOR.md`)

- `pytest`: 110/110 (70 originales + 40 nuevas). OTEKON: Δ RMSE = 0,0 V.
- Digitalización de los fixtures: 0,62–0,69 mV en automático (efecto del ajuste de ticks al píxel) y 0,065–0,10 mV
  con anclas corregidas; cobertura del 100 %.
- OTEKON Fig. 3 real: desacuerdo de 1,45–1,57 mV (≈ 0,7 px) frente a la digitalización previa.
- Navegador real: flujo completo con 14 capturas; 6 errores encontrados y corregidos durante la verificación.

### Limitaciones

Ver `docs/DIGITALIZADOR.md` §6:
- sin corrección de rotación ni perspectiva;
- curvas del mismo color que se cruzan;
- solo escalas lineal y log10;
- anclas automáticas a ±0,5–1 px en gráficos con ticks ajustados al píxel;
- candidatos espurios de baja confianza cuando una leyenda toca el marco;
- foco de teclado gestionado por el modal (todas las acciones tienen botón).
