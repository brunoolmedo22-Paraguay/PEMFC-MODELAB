# Verificación de PEMFC ModelLab v0.3.0

Estados posibles:
- **OK:** ejecutado y superado.
- **PARCIAL:** superado con la salvedad indicada.
- **NO:** no superado.
- **BLOQUEADO:** no ejecutable en este entorno.

Todas las cifras proceden de las ejecuciones finales (código final, versión 0.3.0).

## Entorno

- Python 3.12.3. Dependencias fijadas en `requirements.txt`: streamlit 1.66.1, numpy 2.4.4, pandas 3.0.2, scipy 1.17.1, plotly 7.1.0, matplotlib 3.10.8, pillow 12.1.1, opencv-python-headless 4.13.0.92, **onnxruntime 1.24.4** y **openpyxl 3.1.5**.
- Navegador real: Chromium headless (Playwright 1.56) contra `streamlit run app.py`, en escritorio (1440×1000), tablet (1024×768) y móvil (390×844).
- Scripts en `tools/e2e/e2e_v030_*.py`. Resultados en `docs/resultados_v0.3.0/e2e/`. Capturas (21) en `docs/capturas/v0.3.0/`.

## Pruebas automatizadas: `python -m pytest -q` → **200 aprobadas**

| Conjunto | Pruebas | Qué cubre |
|---|---:|---|
| Núcleo v0.1/v0.2 (`test_model`, `test_identification`, `test_datasets`, `test_profiles`, `test_units`; sin cambios) | 62 | Modelo, optimizador, perfiles, CSV, unidades |
| `test_app.py` (reescrito para el flujo por etapas) | 14 | Catálogo, creación, etapa 01, OTEKON completo, CSV de stack, CSV inválido, condiciones ausentes, stack sin geometría, recarga de perfil, resultado desactualizado, navegación sin pérdida, reapertura en sesión nueva, historial, perfil activo, nueva identificación a partir de una calibración |
| `test_digitizer_app.py` | 6 | Diálogo del Motor 1 con OCR, confirmación, cancelación sin efectos, errores, imagen corrupta, cambio de imagen |
| `test_digitizer.py` | 41 | Las 34 de v0.2.0 más 7 nuevas: reconocimiento automático, revisión y confirmación, corrección de etiquetas, anclas del usuario no pisadas, modo manual y curvas guardadas |
| `test_axis_ocr.py` | 59 | Interpretación de etiquetas, multiplicadores, unidades, ajuste geométrico, fixtures, punto o coma, negativos, log, multiplicador en X e Y, figura real OTEKON, OCR ausente, integridad del modelo |
| `test_digitizer_export.py` | 6 | Coherencia exacta CSV ↔ XLSX ↔ JSON, alcances, exclusiones, bloqueo sin confirmación, exportación en píxeles, unidades libres, PNG y ZIP, figura multipanel |
| `test_workspace.py` | 12 | Dispositivos, serialización exacta, calibraciones inmutables, estados, búsqueda, persistencia por registros, alteraciones, proyecto portátil, migración y **perfil real de v0.2.0** |

**Núcleo intacto:**
- `pemfc_core/model.py` conserva el SHA‑256 `00b0643a…dac`.
- `identification/` no tiene cambios.
- `tools/reproduce_otekon.py` da RMSE 0,001411370003308996 V con **Δ = 0,0 V**.
- La interfaz nueva genera el **mismo perfil** `pml-bffba1bcc9f39323`.

## Exactitud del digitalizador totalmente automático (sin escribir ningún valor)

Evaluador oficial del handoff (`tools/handoff/evaluar_extraccion.py`):

| Fixture | Ejes | Unidades leídas | RMSE / MAE | Cobertura |
|---|---|---|---|---|
| 01_curva_simple | X y Y confiables | A/cm², V | 0,688 / 0,677 mV | 100 % |
| 02_dos_curvas A / B | confiables | A/cm², V | 0,688 / 0,616 mV | 100 % |
| 03_marcadores_y_ruido | confiables | A/cm², V | 0,691 mV | 100 % |

El error es idéntico al de la v0.2.0 con valores tecleados, porque proviene del ajuste de ticks al píxel en matplotlib.

**Figura publicada OTEKON Fig. 3:** paneles 1 y 4 con ejes confiables (RMS 0,07 y 0,31 px), unidades «A/cm2» y «Volts» leídas de los títulos reales.

**Banco OCR de 16 ejes:** punto o coma, serif, negativos, log 10ⁿ, multiplicador en X y en Y, OTEKON. Todos quedan bien clasificados. Los ejes con multiplicador quedan siempre en revisión.

## Matriz de requisitos (PARTE VIII)

### Gestión de dispositivos

| Requisito | Estado | Evidencia |
|---|---|---|
| Crear un dispositivo | OK | Navegador: tarjeta «+ Agregar dispositivo» → diálogo (solo nombre obligatorio) → espacio del dispositivo; `test_create_device_dialog_requires_only_name` |
| Editar sus metadatos | OK | Navegador: etapa 01 (N = 41, A = 232) guardada; `test_step1_edits_device_and_keeps_stable_id` (id estable) |
| Abrirlo desde el catálogo | OK | Navegador: clic en la tarjeta tras recargar → reapertura del flujo |
| Crear varias calibraciones | OK | Cada ejecución crea una calibración nueva; la anterior se conserva intacta (huella) |
| Guardar y recuperar borradores | OK | Navegador: recarga dura → catálogo, configuración OTEKON y calibración registrada recuperados (3 ejecuciones idénticas); `test_reopening_draft_in_new_session…` |
| Regresar entre etapas sin perder datos | OK | `test_navigation_back_and_forth…`; navegador: etapas 01–05 completas tras ir y volver |
| Evitar sobrescrituras accidentales | OK | Conflicto entre pestañas rechazado y avisado (navegador); importación sin sobrescribir; calibraciones y conjuntos de datos inmutables |

### Digitalizador

| Requisito | Estado | Evidencia |
|---|---|---|
| Detectar ejes y valores automáticamente | OK | Fixtures y OTEKON sin escribir valores (tabla anterior); navegador: modo autónomo y diálogo del Motor 1 |
| Leer números con punto y coma decimal | OK | `test_synthetic_axes_reliable[comma…]`, OTEKON («0,2»…«1,2») |
| Reconocer escalas lineales y logarítmicas | OK | `[log-X-logarítmica…]`, «10-3»… → 10⁻³ |
| Detectar errores de OCR | OK | Etiqueta atípica («7,0», «9») detectada como incoherente; multiplicadores y exponentes no interpretables fuerzan la revisión |
| Corregir valores manualmente | OK | Corrección y exclusión por etiqueta (`test_individual_label_correction…`); referencias manuales intactas |
| Trabajar con varios paneles | OK | Navegador: panel 1 → panel 4 → panel 1 con las curvas conservadas; exportación de dos paneles con calibraciones distintas |
| Exportar X–Y correctamente | OK | Navegador: los cinco formatos descargados; valores iguales a la calibración del borrador (prueba) |
| Coherencia entre CSV, XLSX y JSON | OK | Exacta valor a valor, en pruebas y en los archivos **descargados** en el navegador (80 filas, 2 curvas) |
| Las unidades no se inventan | OK | Sin evidencia en el título quedan sin confirmar y bloquean; la exportación en píxeles no incluye unidades |

### Integración

| Requisito | Estado | Evidencia |
|---|---|---|
| Importar curvas desde imagen y CSV | OK | Navegador: diálogo con OCR → curva «auto_ocr» añadida; CSV en `test_app` |
| Ejecutar identificación paramétrica | OK | Navegador: `AJUSTADO_A_CURVA`, RMSE 1,411 mV |
| Visualizar resultados | OK | Captura 07; historial en solo lectura (captura 11) |
| Generar perfil | OK | Descarga `pml-bffba1bcc9f39323_profile.json` registrada |
| Reimportar perfil | OK | `test_synthetic_example…profile_reload`; migración de perfiles |
| Reproducir resultados | OK | Configuración serializada → RMSE idéntico al bit; OTEKON Δ = 0 |
| Los borradores no alteran perfiles finalizados | OK | La calibración conserva su huella tras nuevas ejecuciones y bifurcaciones; cancelar el digitalizador no toca el borrador |

### No regresiones e interfaz real

| Requisito | Estado | Evidencia |
|---|---|---|
| Suite completa | OK | 200/200 |
| Baseline OTEKON | OK | Δ = 0,0 V |
| Pruebas en navegador | OK | Flujo del Motor 1, recarga, digitalizador autónomo, diálogo OCR, persistencia y conflictos: 0 excepciones, 0 errores de JS |
| Pruebas visuales en escritorio y tablet | OK | Capturas 13–14 (1024×768) y 15 (390×844) |
| Despliegue en Streamlit Community Cloud | **BLOQUEADO** | Requiere una cuenta y autorización. Dependencias solo de pip, sin paquetes del sistema |

## Fallos encontrados por la verificación (todos corregidos)

Están detallados en `CHANGELOG.md`:
- configuración sobrescrita al reabrir;
- identidad del perfil tomada del ejemplo;
- ejecuciones repetidas sin registrar;
- multiplicador «1e3» no detectado (error ×1000);
- XLSX truncado a 16 cifras;
- tipos `numpy` que dejaban el lienzo en blanco;
- ajuste del lienzo con tamaño 0;
- deshacer el borrado de una curva guardada.

**Una observación sin causa demostrada:** una vez, tras recargar, la etapa 04 apareció como «desactualizada». No se reprodujo en ejecuciones posteriores con diagnóstico (`PML_DEBUG=1`); las huellas coincidían. Se observó antes de dos correcciones del enlace de borrador y se deja documentada.

## Limitaciones conocidas

- **Persistencia:** limitada al navegador y dominio de uso. Se pierde al borrar los datos del sitio y no se sincroniza entre equipos. El proyecto `.pmlproj.zip` es la copia independiente. Las sesiones del digitalizador autónomo **no** se guardan en IndexedDB; se conservan exportándolas.
- **Reconocimiento:** ver `docs/ARQUITECTURA_v0.3.0.md` §7.
  - superíndices aplanados;
  - multiplicadores en posiciones atípicas;
  - unidades poco habituales;
  - fotos rotadas;
  - fuentes de menos de 7 px.
- **Rendimiento:** el OCR ocupa unos 100 MB de RAM y tarda unos 1–3 s por panel en 1 CPU; la primera carga del modelo añade 1–2 s.
- **Foco del modal:** tras cada actualización, Streamlit lleva el foco al botón ✕; el lienzo lo recupera si estaba en uso. Todas las acciones tienen además un botón visible.
- **Plataforma:** no se implementa el Motor 2.

## Instalación limpia (desde cero)

- **Instalación:** copia del proyecto sin cachés y entorno virtual nuevo (`uv venv -p 3.12`), solo con `requirements.txt` y `requirements-dev.txt`. Instala correctamente: streamlit 1.66.1, onnxruntime 1.24.4, openpyxl 3.1.5 y opencv-python-headless 4.13.0.92. No hay `opencv-python` con interfaz gráfica, ni RapidOCR, ni Tesseract: el OCR usa el reconocedor propio y el modelo incluido.
- **Pruebas en ese entorno:** **200 aprobadas**; `reproduce_otekon.py` da Δ = 0,0 V.
- **Navegador:** `streamlit run app.py` desde la copia limpia y `tools/e2e/e2e_v030_digitalizador_autonomo.py` (con `PML_URL`). Reconocimiento automático, dos paneles, CSV = XLSX = JSON y 0 errores.
