"""Digitalizador asistido de curvas de polarización (PEMFC ModelLab v0.2.0).

Paquete sin dependencias de Streamlit: carga segura de imágenes, detección
automática local (ejes, ticks, trazos), calibración píxel↔físico, borrador
editable con deshacer/rehacer y auditoría, y construcción de la curva a través
del pipeline existente (`identification.datasets.build_curve`).

Convención de coordenadas de imagen (todas las funciones): origen en la esquina
superior izquierda del píxel superior izquierdo, x hacia la derecha, y hacia
ABAJO, coordenadas continuas; el centro del píxel (col, fila) está en
(col + 0,5, fila + 0,5). Es la misma convención que usa el lienzo del editor.
"""
DIGITIZER_VERSION = "1.0.0"
ALGORITHM_ID = "pemfc-modellab/raster-trace-digitizer"
