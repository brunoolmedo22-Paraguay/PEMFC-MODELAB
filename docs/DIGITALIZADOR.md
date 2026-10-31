# Digitalizador asistido de curvas de polarización (v0.2.0)

Convierte la imagen de una curva V–I publicada o escaneada en una curva del Motor 1. Toda la detección es local, sin
OCR ni servicios externos. Los valores físicos de los ejes los confirma siempre el usuario.

## 1. Uso

1. **1. Importar curva** → *Origen de los datos*: **Imagen de una curva** → **Abrir digitalizador**.
2. Suba un PNG, JPEG o WebP (máx. 10 MB y 25 MP) o elija una imagen de ejemplo. La detección automática se ejecuta
   al cargar, sin un segundo clic. Detecta paneles con ejes, ticks o gridlines, recuadros de leyenda y trazos por
   color. El trazo candidato aparece superpuesto con sus puntos.
3. **Estado `REQUIERE_CALIBRACION`.** Las anclas X1, X2, Y1 e Y2 se proponen en los ticks detectados, pero **su
   valor queda vacío**. Mientras no haya calibración, la tabla y el resumen muestran solo píxeles («coordenadas en
   píxeles / calibración pendiente») y **Confirmar** está bloqueado.
4. Escriba el valor rotulado junto a cada ancla (se admite coma decimal). Para mover un ancla tiene tres opciones:
   - pulsar su botón en el lienzo y hacer clic en la imagen (se ajusta al tick más cercano; Alt evita el ajuste);
   - arrastrar el ancla;
   - escribir su px o py.

   Elija también las unidades (A/cm², mA/cm², A, mA, A/m²; V o mV; por celda o de stack) y la escala de cada eje
   (lineal o logarítmica).
5. Revise y corrija el trazo:

   | Acción | Cómo |
   |---|---|
   | Mover un punto o un ancla | Arrastrarlo en modo **Mover** |
   | Añadir un punto manual | Modo **＋ Añadir** y clic |
   | Borrar un punto | Modo **✕ Borrar**, o seleccionarlo y pulsar Supr |
   | Excluir o incluir puntos | Modo **⊘ Excluir**: clic en un punto, o recuadro (Mayús para incluir) |
   | Nueva región de interés | Modo **▭ ROI** y arrastrar; después **Identificar automáticamente** |
   | Zoom | Rueda, botones +/−, Ajustar o 1:1 |
   | Desplazar la vista | Arrastrar el fondo, o modo **✥ Mano** |
   | Deshacer / rehacer | ↶ ↷ (o Ctrl+Z / Ctrl+Y) |

   La tabla está sincronizada con el lienzo. Editar px o py, o el valor físico (que se convierte a píxeles con la
   calibración vigente), mueve el punto. Desmarcar *incluir* lo excluye sin borrarlo. También se pueden añadir y
   borrar filas.
6. **Vista previa física**: curva con ejes en unidades físicas, rangos de ejes y puntos, resolución por píxel y
   avisos.
7. **Condiciones y metadatos**: identificador, rol, temperatura y presión (obligatorias), presión de referencia,
   p_H2, fracción de O₂, origen de las condiciones, fuente y σ_V. La calidad está **fija en «digitalizado»**.
   σ_V no tiene valor por defecto. Puede adoptarse la estimación de resolución de la imagen (±0,5 px), que queda
   registrada con ese origen.
8. **Confirmar y añadir curva**: valida con el pipeline existente y añade la curva sin borrar las demás. Invalida los
   resultados previos y cierra el diálogo. **Cancelar** descarta el borrador sin tocar curvas, ajuste ni perfil.
   Cerrar con ✕, Esc o un clic en el fondo conserva el borrador para seguir más tarde.

Para varias curvas de la misma figura, confirme una, reabra el digitalizador (se restauran la imagen y la
calibración), elija otro candidato y confírmelo con otro identificador.

## 2. Arquitectura

| Pieza | Archivo | Notas |
|---|---|---|
| Carga segura | `digitizer/imageio.py` | Formato por firma binaria; SVG y otros rechazados; límites de bytes y píxeles; EXIF y transparencia registrados; sin escritura en disco |
| Detección | `digitizer/detection.py` | OpenCV, NumPy y Pillow; trabaja solo en píxeles |
| Calibración | `digitizer/calibration.py` | Fórmulas del contrato; lineal y log10; validación de degeneración |
| Borrador | `digitizer/draft.py` | Fuente geométrica = píxeles; físicos derivados; deshacer/rehacer (200 niveles); auditoría |
| Confirmación | `digitizer/confirm.py` | `build_curve` + `check_curve_set`; artefactos para `originals` |
| Lienzo | `ui/static/digitizer_canvas.js`, `.css` | Componente bidireccional `st.components.v2` en JavaScript sin dependencias ni CDN ni compilación |
| Diálogo | `ui/digitizer_view.py` | `st.dialog(width="large")`; única mutación del conjunto: una llamada a `state.set_dataset` |

**El lienzo.** Imagen y superposición se dibujan con una sola transformación (escala + desplazamiento) en el espacio
de píxeles de la imagen original, de modo que no pueden desalinearse con zoom, desplazamiento ni cambios de tamaño.
El lienzo envía **eventos discretos** a Python (`setTriggerValue`), al soltar el ratón y nunca durante el
movimiento. Python aplica cada evento al borrador y devuelve el estado. Zoom y desplazamiento viven en el navegador.

`st.components.v1.html` no se usa porque no devuelve eventos a Python. El componente v2 acepta JS y CSS en línea
desde archivos locales, así que **no hay paso de compilación** ni artefactos que reconstruir.

**Convención de coordenadas.** Origen en la esquina superior izquierda, x hacia la derecha, **y hacia abajo**,
coordenadas continuas: el centro del píxel (c, f) está en (c + 0,5, f + 0,5).

## 3. Algoritmo automático

1. **Fondo y oscuridad.** El fondo es el color dominante. La oscuridad es D = luminancia del fondo − luminancia.
2. **Rectas.** Se integra D sobre 3 píxeles transversales y se aplica una apertura morfológica con un núcleo largo.
   Las líneas fuertes son ejes y marcos. Integrar evita confundir gridlines grises con ejes antialiasados: en la
   figura OTEKON ambos tienen un gris parecido, pero distinta tinta integrada.
3. **Paneles.** Son esquinas en «L» entre un eje Y y un eje X. Se descartan los paneles que contienen a otros, como
   el marco exterior de una figura compuesta. Con varios paneles, el usuario elige en **Panel**.
4. **Posiciones de anclas.** Primero se buscan picos de D en bandas pegadas a cada eje, conservando la progresión
   aritmética más larga. Si no la hay, se usan las gridlines (los bordes del panel solo entran si encajan en la
   progresión). En último caso, los bordes del marco, con aviso. **Los valores no se leen.**
5. **Trazos.**
   - Los colores se agrupan con un modelo de mezcla fondo → color: cada píxel tiene una cobertura α respecto del
     color del trazo.
   - El núcleo del trazo exige α ≥ 0,65 y poca distancia perpendicular a esa mezcla. Así se separan los marcadores
     semitransparentes del fixture 03 (α ≈ 0,40–0,61).
   - Los recuadros de leyenda se excluyen tras retirar las gridlines largas que los tocan.
   - En los trazos oscuros se retiran las rectas largas.
   - Los componentes alargados forman líneas y se encadenan a lo largo de x. Las manchas compactas y regulares
     forman series de **marcadores**.
6. **Línea → puntos.**
   - En cada columna se calcula el centroide ponderado por α. Si hay varios tramos, se sigue la continuidad.
   - Los extremos se recortan media anchura proyectada, por las terminaciones de línea.
   - Se remuestrea uniformemente en x (40 puntos por defecto) **sin interpolar dentro de huecos**.
7. **Confianza.** Combina cobertura en x, columnas ambiguas, extensión y regularidad del grosor; se penaliza un
   trazo hecho de rectas. Solo se selecciona automáticamente un candidato con confianza ≥ 0,5. Si no hay ninguno, se
   explica el motivo y se ofrece el trazado manual.

## 4. Datos y trazabilidad

Al confirmar se construye la curva con `identification.datasets.build_curve` y se valida el conjunto combinado con
`check_curve_set`.

| Campo | Contenido |
|---|---|
| `quality` | `digitalizado` (siempre) |
| `source_file`, `source_sha256` | Imagen original (nombre único) y su SHA-256 |
| `mapping` | Unidades, base de tensión, escalas, las cuatro anclas (px, py, valor, origen, editada), fórmulas de calibración, algoritmo y versión, método, candidato, ROI, área de trazado, parámetros, resolución, nombres de los archivos derivados |
| `transformations` | Secuencia legible: imagen, decodificación, extracción, ediciones, calibración X e Y, conversión píxel → físico, exclusiones; después, las conversiones de unidades del pipeline |
| `raw` | Puntos incluidos con px, py, valores en unidades del gráfico, método y número de ediciones |
| `meta.provenance` | «Digitalización asistida de <archivo>; confirmado por el usuario» |

En `originals`, y por tanto en `data/original/` del ZIP del experimento, se añaden cuatro archivos: la imagen
original intacta, `<imagen>__<curva>__digitalizacion.json`, `…__digitalizacion.csv` y `…__overlay.png`.

- El **JSON** contiene la auditoría completa: SHA-256, convención de píxeles, parámetros y resumen de la detección,
  candidatos, ROI, anclas, calibración, unidades, todos los puntos (incluidos los excluidos), los borrados, el
  recuento de ediciones, la resolución, los avisos y los eventos con marca de tiempo.
- El **CSV** tiene píxeles, valores físicos, `include`, `method` y `modified`. Las columnas normalizadas
  `current_density_A_cm2` y `voltage_V` solo aparecen si no hace falta geometría para calcularlas.
- `profile.json` **no** incrusta la imagen: en la prueba ocupa unos 90 kB.

Hay un ejemplo real en `docs/ejemplo_exportacion_digitalizada/`. Las dos desviaciones visibles en su overlay son
ediciones deliberadas del recorrido de prueba (un punto llevado a 0,9 V desde la tabla y otro arrastrado).

## 5. Garantías científicas

- No se convierten píxeles a unidades físicas sin las cuatro referencias con posición y valor. No hay OCR.
- No se infieren `N_cells` ni `A_active`: con A o mA, o con tensión de stack, el pipeline exige la geometría del
  dispositivo.
- σ_V no tiene valor por defecto. La estimación de resolución se ofrece explícitamente y se registra su origen.
- Nada entra en el optimizador sin **Confirmar**. Cancelar y los errores no modifican el conjunto ni los resultados.
- Una curva digitalizada no activa `VALIDADO_EXPERIMENTALMENTE` por sí misma. Como curva de **validación**, la regla
  existente solo la acepta en una condición no calibrada. La ayuda del campo *Rol* advierte que una curva de la
  misma figura que las de calibración no es independiente.
- Privacidad: el proceso es local y en memoria; sin conexiones externas ni CDN; sin escritura en disco; el borrador
  se libera al cancelar.

## 6. Limitaciones conocidas

- **Precisión de las anclas.** matplotlib y otros trazadores ajustan ejes y ticks al píxel. Por eso las anclas
  automáticas pueden quedar a 0,5–1 px de la posición matemática. En los fixtures, eso explica casi todo el error
  automático (≈0,6–0,7 mV, con 1 px ≈ 1,2 mV). El trazo en sí es sub-píxel.
- **Curvas solapadas o del mismo color.** Se separan por color. Dos curvas del mismo color que se cruzan pueden
  intercambiarse en el cruce (se avisa con «columnas con varios tramos»).
- **Grosor y antialias.** El centroide ponderado por α es simétrico. Las terminaciones se recortan con una
  heurística de media anchura.
- **Escalas.** Lineal y log10 en cada eje. Otras escalas (recíproca, rotas, mixtas) no están soportadas.
- **Geometría.** No hay corrección de rotación ni de perspectiva. Una foto inclinada no produce ejes en «L»: se
  avisa y se exige calibración manual, que tampoco corrige la inclinación.
- **Huecos y oclusiones.** No se interpola dentro de un hueco; se avisa.
- **Leyendas pegadas al marco** (panel 4 de OTEKON) pueden generar candidatos espurios. Tienen confianza baja y no
  se seleccionan automáticamente.
- **Imágenes problemáticas:** fondo oscuro (aviso), curvas blancas o de bajo contraste, baja resolución (aviso por
  debajo de 300 px) y JPEG muy comprimido (aviso).
- **Curvas no funcionales en x** (por ejemplo histéresis con ida y vuelta) se ordenan por x.
- **Foco del teclado en el modal.** Tras cada actualización, Streamlit mueve el foco al botón ✕. El lienzo lo
  recupera si se estaba usando en los últimos 8 s. Todas las acciones tienen además botones visibles.
