# PEMFC ModelLab v0.3.0: arquitectura, persistencia y digitalizador inteligente

Este documento responde a los nueve puntos solicitados para la v0.3.0.

Principio general: el núcleo numérico **no cambia**.
- `pemfc_core/model.py` conserva su SHA‑256 `00b0643a…`.
- `identification/` está intacto.
- El baseline OTEKON da Δ RMSE = 0,0.

Todo lo nuevo se construye alrededor del núcleo.

## 1. Arquitectura de la gestión de dispositivos

```
app.py                      enrutado: catálogo · espacio del dispositivo · digitalizador · alcance
ui/shell.py                 identidad visual, barra superior, rutas en la URL (?view=&device=&draft=&step=)
ui/catalog_view.py          catálogo (componente propio), creación, copias de seguridad
ui/device_view.py           flujo guiado 01–06 + navegación inferior + historial
ui/draft_binding.py         enlace borrador persistente ↔ estado de sesión de las vistas científicas
ui/persistence.py           puente con IndexedDB (navegador) y estado de guardado
ui/history_view.py          calibraciones en solo lectura, perfil activo, comparación
workspace/model.py          objetos persistentes e invariantes (sin Streamlit)
workspace/serialization.py  serialización exacta de curvas, configuración y dispositivo
workspace/project_io.py     proyecto portátil .pmlproj.zip, migraciones, perfiles v0.2.0
ui/static/*.js|css          componentes propios: catálogo, indicador de etapas, barra superior,
                            lienzo del digitalizador, puente de almacenamiento (JS local, sin CDN)
```

Las vistas científicas de v0.2.0 (importación, configuración, calibración, resultados y exportación) se **reutilizan** dentro de las etapas 02–06. No se reescribieron.
- **Única modificación de presentación:** `import_view.render(with_device=False)` y un gancho opcional en las descargas, que sirve para registrar las exportaciones.
- **Enlace con el borrador** (`draft_binding`):
  - al abrir un borrador, rellena el estado de sesión que esas vistas ya usaban;
  - tras cada ejecución, vuelca los cambios al borrador;
  - cada ejecución del optimizador se registra como calibración nueva.

## 2. Dispositivo, experimento, borrador, calibración y perfil

| Objeto | Clave | Mutabilidad | Contenido |
|---|---|---|---|
| **Dispositivo** | `device:<id>` | Editable (rev++) | Identidad (id estable independiente del nombre), fabricante, modelo, tecnología, configuración, N_cells, A_active (con origen), datos nominales, datasheet, observaciones, procedencia, perfil activo |
| **Conjunto de datos** (experimento) | `dataset:<id>` | **Inmutable** | Curvas experimentales usadas en una calibración (serialización exacta) y referencias a los archivos originales |
| **Borrador de identificación** | `draft:<id>` | Editable | Trabajo en curso: curvas, configuración, etapa actual, geometría usada al importar, calibraciones producidas |
| **Calibración** | `calibration:<id>` | **Inmutable** | Una ejecución del optimizador: el **perfil completo** (formato v0.2.0, reimportable), huellas de datos y configuración, origen (ejecutada, migrada o importada) |
| **Exportación** | `export:<id>` | Inmutable | Registro de cada descarga de perfil (archivo, SHA‑256, fecha) |
| **Perfil activo** | campo del dispositivo | Editable | Selección **administrativa** de la calibración de referencia. No cambia su estado científico. Un perfil no utilizable no puede ser activo |
| Binarios | `blob:<sha256>` | Inmutable | Imágenes, CSV y auditorías, sin duplicar |

Reglas:
- Una nueva identificación **nunca sobrescribe** otra: crea una calibración nueva, aunque repita datos y configuración.
- Una calibración existente se consulta en solo lectura. Para cambiarla se usa «Nueva identificación a partir de esta».
- El estado del catálogo es **administrativo**: Nuevo, Configuración incompleta, Calibración en progreso, Perfil ajustado o Perfil con validación. La **calidad científica**, es decir el estado del perfil activo, se muestra aparte.
- **Resultados desactualizados:** si cambian los datos o la configuración, la etapa 04 pasa a «Requiere atención». Las calibraciones anteriores **no se borran**.

## 3. Mecanismo de persistencia y garantías reales

En Streamlit Community Cloud el disco del servidor **no es duradero**, porque se pierde al reiniciar o redesplegar. Por eso la persistencia es local, en dos niveles.

**a) Automática, en el navegador (IndexedDB).** La gestiona el componente `ui/static/storage_bridge.js`.
- **Al iniciar cada sesión del servidor**, el navegador envía los registros guardados. Los binarios no se incluyen: se piden bajo demanda.
- **Al final de cada ejecución**, los registros modificados se envían en un lote. El lote se reenvía idéntico hasta recibir confirmación.
- **Escritura transaccional con control de revisión:** si otra pestaña guardó una revisión más nueva, o si un registro inmutable difiere, la escritura se **rechaza** y se avisa. Nunca se sobrescribe.
- **Indicador visible:** «Guardado en este navegador · hh:mm:ss», «Cambios sin guardar», «Guardando…», «Conflicto» o «Sin persistencia». Además existe el botón «Guardar borrador».

**Garantías reales:** los datos sobreviven a recargas, cierres y pérdida de sesión del servidor en **el mismo navegador y el mismo dominio**. **No** sobreviven a que el usuario borre los datos del sitio y **no** se sincronizan entre equipos ni navegadores. Si IndexedDB no está disponible (modo privado estricto o políticas del navegador), la aplicación funciona solo en memoria y lo indica.

**b) Proyecto portátil `.pmlproj.zip`**, independiente del servidor y del navegador.
- **Contenido:** `manifest.json` con la huella SHA‑256 de cada registro, `records/` y `blobs/`.
- **Al importar** se verifica cada huella y se rechazan rutas inseguras y versiones de esquema desconocidas. Importar **no sobrescribe**:
  - lo idéntico se omite;
  - un dispositivo o borrador con el mismo id y distinto contenido entra como **copia** con id nuevo, remapeando sus referencias;
  - un registro inmutable alterado se rechaza.

No se usan cuentas, bases de datos remotas ni servicios externos. Una sincronización entre equipos requeriría almacenamiento externo; queda fuera de esta versión y se documenta como tal.

## 4. Reconocimiento automático de ejes

Al cargar una imagen, `DigitizationDraft.from_image`:
1. Detecta los **paneles** (esquinas en «L») y descarta el marco exterior de una figura compuesta.
2. Delimita el **área del gráfico** y los **ejes**, con su posición sub‑píxel.
3. Localiza las posiciones de los **ticks**, o en su defecto de las gridlines.
4. Localiza el **texto** en bandas exteriores a cada eje mediante componentes conexos. Lo clasifica en etiquetas de tick, título del eje (incluida la columna girada del eje Y) y multiplicador (`1e3`, `×10³`, también sobre el eje Y).
5. **Reconoce el texto** con el OCR local (§6).
6. Calcula las **interpretaciones** de cada etiqueta: punto o coma decimal, miles, negativos, notación científica, «10-3» como 10⁻³ y porcentajes.
7. Aplica la **verificación geométrica** (§5), que elige la escala lineal o log10 y los valores.
8. Detecta la **unidad** en el título: A/cm², mA/cm², A/m², A, mA, V, mV, W, kW y %. Si no hay evidencia, la unidad queda **sin confirmar**.
9. Fija las **referencias** X1, X2, Y1 e Y2 en las dos etiquetas coherentes más alejadas de cada eje. Si hay multiplicador, los valores ya lo incluyen.

Cada eje recibe un **estado basado en evidencias**:
- **Confiable:** al menos 3 etiquetas coherentes, residuo máximo ≤ 1,5 px, confianza OCR ≥ 0,85 (o entre 0,6 y 0,85 si la geometría lo corrobora con ≥ 4 etiquetas y residuo ≤ 1 px), sin atípicas, sin ambigüedades, sin multiplicador y con orientación habitual.
- **Pendiente de revisión:** pasa a este estado cualquier eje que incumpla alguna de esas condiciones. Las razones se muestran, por ejemplo «multiplicador ×1000 detectado» o «"7,0" incoherente con la geometría».
- **Insuficiente:** menos de 2 etiquetas coherentes. Queda la calibración manual.

En la interfaz, cada número reconocido se enmarca **sobre la imagen**: verde si es coherente, rojo si es atípico, gris si está excluido y azul si es un título. La tabla de etiquetas permite **corregir o excluir** cada una, con recálculo inmediato. Un eje en revisión exige pulsar «Confirmar eje». Escribir un valor a mano cuenta como calibración manual de ese eje.

**Regla innegociable:** sin dos referencias completas y confirmadas, y sin unidades confirmadas, no hay valores físicos definitivos. No se puede confirmar hacia el Motor 1 ni exportar valores físicos; la exportación en píxeles es explícita y lleva la marca «SIN CALIBRAR».

## 5. Algoritmo de calibración geométrica

Para un eje con etiquetas en posiciones p_k (centro del tick más cercano, o centro del texto) e interpretaciones {v_k^(i)}:

1. **Hipótesis por pares.** Para cada par de etiquetas (k, l), cada combinación de sus interpretaciones y cada escala, con t = v en lineal o t = log10 v en logarítmica, se obtiene la recta t = a + b·p.
2. **Consenso.** Para cada etiqueta se elige la interpretación cuyo pixel predicho, (t − a)/b, cae dentro de la tolerancia, que es la mayor entre 2 px y el 4 % del espaciado de ticks. Una etiqueta así es «coherente».
3. **Selección.** Gana el modelo con más etiquetas coherentes. En caso de empate, el de menor penalización de interpretación (la lectura literal se prefiere a «miles» o «potencia»). Después, el de menor residuo.
4. **Refinamiento.** Mínimos cuadrados sobre las etiquetas coherentes.
5. **Ambigüedad.** Si otro modelo distinto obtiene el mismo número de coherentes, el eje queda en revisión.

Este procedimiento detecta:
- lecturas erróneas, que quedan como atípicas;
- interpretaciones ambiguas («1,000» como 1,0 o 1000);
- confusiones con leyendas, que no encajan en la progresión;
- la escala log, porque 10⁻³…10⁰ equiespaciados solo encajan en log10.

La transformación final es la de v0.2.0, `digitizer/calibration.py`: lineal o log10 por eje, sin doble inversión de Y.

## 6. Estrategia OCR seleccionada

Se compararon tres opciones sobre etiquetas reales:

| Opción | Resultado | Decisión |
|---|---|---|
| Tesseract 5.3 | Errores en etiquetas («15» por 1,5, «11» por 1,1, «10-+»); requiere un paquete del sistema | Descartada |
| Paquete `rapidocr-onnxruntime` | Buenas lecturas, pero exige `opencv-python` con interfaz gráfica, que falla en Community Cloud por falta de `libGL` | Descartado como paquete |
| **Modelo de reconocimiento PP‑OCRv4 en ONNX, ejecutado con `onnxruntime`, más localización de texto propia** | Mismas lecturas, sin dependencias de sistema, sin modelo de detección | **Elegida** |

- **Licencia:** el modelo (10,9 MB, Apache‑2.0) va en `digitizer/models/` con su licencia y procedencia, y su SHA‑256 se verifica al cargar.
- **Recursos:** unos 100 MB de RAM y aproximadamente 1–3 s por panel en 1 CPU.
- **Sin OCR:** si el OCR no está disponible, los ejes quedan «insuficientes» y la calibración manual sigue completa.

## 7. Limitaciones de reconocimiento

- **Superíndices:** el texto se aplana («10-3»). Se resuelve geométricamente, pero un eje con solo 2 etiquetas queda en revisión.
- **Multiplicadores:** fuera de las zonas típicas (derecha bajo el eje X, encima del eje Y) pueden no detectarse. Cualquier texto con aspecto de exponente no interpretable fuerza la revisión.
- **Unidades:** se reconocen las habituales en PEMFC. Unidades compuestas raras o en otro idioma quedan sin confirmar.
- **Geometría:** no hay rotación ni perspectiva. Una foto inclinada no produce ejes en «L».
- **Leyendas:** si tocan el marco, pueden generar candidatos de trazo de baja confianza, que no se seleccionan automáticamente.
- **Tipografía y resolución:** fuentes muy pequeñas (menos de 7 px) o JPEG muy comprimido reducen la confianza OCR. El resultado quedará en revisión o será insuficiente, nunca «confiable» sin evidencia.
- **Ejes no lineales:** solo se admiten escala lineal y log10.
- **Exactitud:** en los fixtures sintéticos de matplotlib, la digitalización totalmente automática tiene un RMSE de 0,62–0,69 mV. Es el mismo valor que con referencias tecleadas, porque matplotlib ajusta los ticks al píxel.

## 8. Formatos de exportación (digitalizador autónomo)

Una única recolección (`digitizer/export.collect`) genera todos los formatos, que contienen **exactamente los mismos valores**. Los floats se escriben con `repr`; en XLSX se fuerza la escritura exacta porque `openpyxl` trunca a 16 cifras. Las pruebas comparan bit a bit.

| Formato | Contenido |
|---|---|
| CSV | `curve_id, panel, point, x, y, x_unit, y_unit, origin, px, py` (en píxeles: `px, py, status=SIN CALIBRAR`) |
| XLSX | Hoja «Datos» (todas), una hoja por curva con unidades en la cabecera, «Metadatos» (imagen, SHA‑256, calibraciones, reconocimiento, confirmaciones) |
| JSON | `pemfc-modellab/xy-export` 1.0.0: imagen, paneles (calibración, anclas, reconocimiento con cada etiqueta, unidades y su fuente), curvas con puntos en píxeles y físicos |
| PNG | Imagen original con las curvas exportadas superpuestas y su leyenda |
| ZIP científico | Los cuatro anteriores, la imagen original, la auditoría completa de cada panel y un LEEME |

**Alcances:** la curva actual, una curva guardada, todas las del panel o todas las de la imagen. Los identificadores se forman con el panel y el nombre (`P1_A`), y cada panel conserva sus unidades y su calibración. La tabla interactiva permite copiar los valores y ofrece además un bloque de texto tabulado con botón de copia.

## 9. Compatibilidad con versiones anteriores

- **Perfiles v0.1/v0.2:** se siguen cargando con `load_profile` (reproducción verificada). Además se pueden **migrar**, en la pantalla inicial, a un dispositivo con su conjunto de datos y una calibración «migrada»; el perfil se conserva **intacto** dentro de la calibración. Lo prueba un perfil real exportado por v0.2.0 (`tests/fixtures/compat/profile_v020.json`).
- **Esquema del espacio de trabajo:** `pemfc-modellab/workspace` 1.0.0 tiene un punto único de migración explícita. Una versión desconocida se rechaza sin importar nada.
- **Digitalizador:** el modo manual de v0.2.0 sigue disponible, ya sea sin OCR o con anclas escritas a mano. Las curvas digitalizadas mantienen la calidad «digitalizado» y la misma trazabilidad, ahora con el reconocimiento de ejes incluido en `mapping`.
- **Exportaciones:** el ZIP del experimento y `profile.json` mantienen su formato.
