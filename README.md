# PEMFC ModelLab v0.2.0 — Motor 1 de identificación paramétrica + digitalizador de curvas

Aplicación Python + Streamlit para identificar los parámetros de un modelo semiempírico de célula de combustible
PEM a partir de **curvas de polarización medidas o digitalizadas**, y obtener un **perfil PEMFC trazable y
reutilizable** (`profile.json`) y un ZIP de experimento con datos, resultados, figuras y reporte.

> **Alcance.** Solo Motor 1 (identificación). La curva V–I es obligatoria: no se crean perfiles a partir de un
> datasheet sin curva. Desde v0.2.0 la curva puede **digitalizarse desde una imagen** con un editor asistido; los
> valores de los ejes los confirma siempre el usuario (sin OCR) y la curva queda con calidad «digitalizado». El
> Motor 2 (simulación operacional, H₂, costes) no está implementado. Un buen ajuste no es una validación
> experimental independiente.

## Uso local

Requiere Python 3.11 o superior (verificado con 3.12.3).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Flujo: **1. Importar curva** (dispositivo, CSV, datos pegados o **imagen de una curva**, mapeo de columnas y unidades, condiciones,
revisión de puntos) → **2. Configurar identificación** (parámetros libres/fijos, límites, priors, multistart) →
**3. Calibrar** → **4. Resultados** (polarización, residuos, pérdidas, parámetros, identificabilidad,
validación) → **5. Exportar perfil** (JSON, ZIP; reimportar y verificar un perfil existente).

Para probar sin datos propios, use «Ejemplos documentados» en la primera pestaña: OTEKON Fig. 3 (4 curvas),
stack de 65 kW (Chen et al. 2024), muestra ilustrativa del handoff y un caso sintético.

### Formato CSV

Una fila de encabezado y, como mínimo, una columna de corriente y una de tensión. Separador `,`, `;` o
tabulador; decimal `.` o `,`. Líneas que empiezan con `#` se ignoran. Una columna opcional puede identificar
varias curvas en el mismo archivo. Unidades soportadas: A, mA, A/cm², mA/cm², A/m²; V o mV, por celda o de
stack. La temperatura y la presión de cada curva se introducen en la interfaz (obligatorias).

```csv
corriente_A;tension_stack_V
2.5;18.40
5;17.60
10;16.90
```

### Digitalizar una curva desde una imagen (v0.2.0)

**1. Importar curva → Imagen de una curva → Abrir digitalizador.** Suba un PNG, JPEG o WebP, o use una imagen de
ejemplo.

1. La detección local de ejes, ticks y trazo se ejecuta al cargar y dibuja los puntos sobre la imagen.
2. Escriba los valores de las cuatro referencias X1, X2, Y1 e Y2, propuestas sobre los ticks detectados. Revise
   las unidades.
3. Corrija el trazo con los modos del lienzo (mover, añadir, borrar, excluir, ROI, zoom, desplazar, deshacer) o en
   la tabla sincronizada.
4. Complete temperatura y presión y pulse **Confirmar y añadir curva**.

La imagen original, el JSON de auditoría, el CSV y el overlay se incluyen en el ZIP del experimento. Detalles,
algoritmo y limitaciones en `docs/DIGITALIZADOR.md`; verificación en `docs/VERIFICACION_DIGITALIZADOR.md`.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q                      # 110 pruebas (incluye digitalizador y flujos AppTest)
python tools/reproduce_otekon.py         # baseline OTEKON (RMSE 0,001411370003309 V/celda)
python tools/evaluate_digitizer.py       # exactitud del digitalizador frente a los truth sintéticos y la figura OTEKON
```

Las pruebas en navegador real (Playwright) están en `tools/e2e/` (ver su README). Resultados de la última ejecución:
`docs/VERIFICACION.md` (v0.1.0) y `docs/VERIFICACION_DIGITALIZADOR.md` (v0.2.0).

## Despliegue en Streamlit Community Cloud

1. Cree un repositorio en GitHub y suba el contenido de esta carpeta (incluidos `examples/`, `tests/fixtures/` y
   `.streamlit/config.toml`). No hay secretos ni servicios externos.
2. En <https://share.streamlit.io> elija **Create app → Deploy a public app from GitHub**, seleccione el
   repositorio y la rama, y como archivo principal `app.py`.
3. En **Advanced settings**, elija Python 3.12 (versión verificada). Streamlit Cloud instala `requirements.txt`.
4. Despliegue. La app no escribe en el servidor: los perfiles se descargan y se vuelven a cargar. Las imágenes del
   digitalizador se procesan en memoria en el propio servidor de la app; no se envían a terceros.

El lienzo del digitalizador es un componente `st.components.v2` con JavaScript y CSS locales
(`ui/static/`), sin paso de compilación: no hay `npm install` ni artefactos que construir. `opencv-python-headless`
no requiere paquetes del sistema (no hace falta `packages.txt`).

```bash
git init && git add . && git commit -m "PEMFC ModelLab — Hito 1"
git branch -M main
git remote add origin https://github.com/<organizacion>/PEMFC-ModelLab.git
git push -u origin main
```

## Estructura

```
app.py                     Entrada Streamlit (pestañas)
pemfc_core/                Núcleo físico sin Streamlit: model, parameters, units, schemas
identification/            Datos, optimizador, diagnósticos, perfiles, reporte, ejemplos
digitizer/                 Digitalizador sin Streamlit: imagen, detección, calibración, borrador, confirmación
ui/                        Vistas Streamlit (solo presentación y estado); ui/static/ = lienzo JS/CSS local
examples/                  Datos de ejemplo con procedencia
tests/                     pytest (+ fixtures generados con el código original)
tools/                     Fixtures, reproducción OTEKON, evaluación del digitalizador, e2e/ (Playwright)
docs/                      Auditoría, plan, metodología, contrato de perfil, verificación
```

## Procedencia, licencia y atribución

Modelo e identificador derivados de [PEM-FC](https://github.com/brunoolmedo22-Paraguay/PEM-FC) (commit
a533432), reconstrucción del modelo de Altıntaş & Ertan (OTEKON 2024). Concepto de perfil y datos del stack de
65 kW de [EnergyMultimodelv1.5](https://github.com/brunoolmedo22-Paraguay/EnergyMultimodelv1.5) (commit 761f032);
fuente experimental: Chen, H. et al., CIESC Journal 75(2), 637–646, 2024, DOI 10.11949/0438-1157.20230745.

Los repositorios de origen no declaran licencia. **La licencia y la titularidad de este proyecto deben ser
definidas por el equipo antes de publicarlo**; no se incluye archivo LICENSE para no presuponerlas.

## Capturas

Flujo verificado en navegador real (Chromium headless) contra `streamlit run app.py`.
Digitalizador (v0.2.0):

| | |
|---|---|
| ![Detección automática](docs/capturas/digitalizador/01_modal_al_cargar.png) | ![Anclas corregidas](docs/capturas/digitalizador/03_anclas_corregidas.png) |
| ![Edición](docs/capturas/digitalizador/04_edicion_de_curva.png) | ![Importación confirmada](docs/capturas/digitalizador/06_importacion_confirmada.png) |

Motor 1 (v0.1.0):

| | |
|---|---|
| ![Importar](docs/capturas/02_importado.png) | ![Resultados OTEKON](docs/capturas/03_resultados.png) |
| ![CSV subido](docs/capturas/05_csv_subido.png) | ![Resultados stack](docs/capturas/06_resultados_stack.png) |
