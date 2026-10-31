# Imágenes de ejemplo del digitalizador

| Archivo | Naturaleza | Procedencia |
|---|---|---|
| `01_curva_simple.png` | **SINTÉTICA** (curva generada matemáticamente; no es un ensayo) | Paquete de handoff v0.2.0, `handoff/fixtures/` (sin modificar). Valores verdaderos en `tests/fixtures/digitizer/01_curva_simple_truth.csv`. |
| `02_dos_curvas.png` | **SINTÉTICA** (dos curvas) | Ídem, `02_dos_curvas_truth.csv`. |
| `otekon_figure3_source.png` | **Figura publicada real** (4 paneles: tensión–T, potencia, eficiencia, tensión–presión) | Repositorio PEM-FC @ a533432, `data/otekon_figure3/figure3_source.png`; figura de Altıntaş & Ertan, OTEKON 2024. SHA-256 `e21595c4…f17ef1`. |

Los CSV de `examples/otekon_figure3/` son una digitalización previa e independiente de esa misma figura, realizada con otra herramienta. Sirven para contrastar resultados. Una diferencia entre ambas mide el **desacuerdo entre dos digitalizaciones**, no un error frente a valores verdaderos.

Ninguna de estas imágenes constituye una validación experimental de un dispositivo nuevo.
