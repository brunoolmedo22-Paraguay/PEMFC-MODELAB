# PEMFC ModelLab — Hito 1: Motor de identificación paramétrica

Aplicación Python + Streamlit para identificar los parámetros de un modelo semiempírico de célula de combustible
PEM a partir de **curvas de polarización medidas o digitalizadas**, y obtener un **perfil PEMFC trazable y
reutilizable** (`profile.json`) y un ZIP de experimento con datos, resultados, figuras y reporte.

> **Alcance.** Solo Motor 1 (identificación). La curva V–I es obligatoria: no se crean perfiles a partir de un
> datasheet sin curva. La digitalización desde imagen y el Motor 2 (simulación operacional, H₂, costes) no están
> implementados. Un buen ajuste no es una validación experimental independiente.

## Uso local

Requiere Python 3.11 o superior (verificado con 3.12.3).

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Flujo: **1. Importar curva** (dispositivo, CSV o datos pegados, mapeo de columnas y unidades, condiciones,
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

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

La suite cubre la equivalencia con el modelo original, la reproducción OTEKON, casos sintéticos, conversión de
stack, datos inválidos, estados de ajuste y validación, perfiles (ida y vuelta, alteraciones, esquema), ZIP y
flujos completos de la interfaz con `streamlit.testing`. Resultados de la última ejecución: `docs/VERIFICACION.md`.

Reproducir OTEKON desde la línea de comandos:

```bash
python tools/reproduce_otekon.py
```

## Despliegue en Streamlit Community Cloud

1. Cree un repositorio en GitHub y suba el contenido de esta carpeta (incluidos `examples/`, `tests/fixtures/` y
   `.streamlit/config.toml`). No hay secretos ni servicios externos.
2. En <https://share.streamlit.io> elija **Create app → Deploy a public app from GitHub**, seleccione el
   repositorio y la rama, y como archivo principal `app.py`.
3. En **Advanced settings**, elija Python 3.12 (versión verificada). Streamlit Cloud instala `requirements.txt`.
4. Despliegue. La app no escribe en el servidor: los perfiles se descargan y se vuelven a cargar.

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
ui/                        Vistas Streamlit (solo presentación y estado)
examples/                  Datos de ejemplo con procedencia
tests/                     pytest (+ fixtures generados con el código original)
tools/                     Generación de fixtures y reproducción OTEKON por CLI
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

Flujo verificado en navegador real (Chromium headless) contra `streamlit run app.py`:

| | |
|---|---|
| ![Importar](docs/capturas/02_importado.png) | ![Resultados OTEKON](docs/capturas/03_resultados.png) |
| ![CSV subido](docs/capturas/05_csv_subido.png) | ![Resultados stack](docs/capturas/06_resultados_stack.png) |
