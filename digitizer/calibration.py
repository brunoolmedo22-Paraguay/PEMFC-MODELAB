"""Calibración de ejes píxel ↔ valor físico (escala lineal o logarítmica).

Para referencias X1=(px1, x1), X2=(px2, x2), Y1=(py1, y1), Y2=(py2, y2), con la
coordenada vertical de imagen creciendo hacia ABAJO:

    lineal:       x = x1 + (px − px1)·(x2 − x1)/(px2 − px1)
                  y = y1 + (py − py1)·(y2 − y1)/(py2 − py1)
    logarítmica:  log10 x = log10 x1 + (px − px1)·(log10 x2 − log10 x1)/(px2 − px1)

La inversión vertical está contenida en los propios anclajes (habitualmente
py2 < py1 cuando y2 > y1): no se aplica ninguna inversión adicional. Las X solo
usan la abscisa de sus anclas y las Y solo la ordenada, de modo que las anclas
pueden estar a distintas alturas/abscisas. No se admite rotación de la imagen.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

SCALE_LINEAR = "lineal"
SCALE_LOG = "logarítmica"
AXIS_SCALES = (SCALE_LINEAR, SCALE_LOG)
ANCHOR_NAMES = ("X1", "X2", "Y1", "Y2")
MIN_ANCHOR_SEPARATION_PX = 1.0       # por debajo: degenerado (error)
RECOMMENDED_SEPARATION_FRACTION = 0.25  # de la dimensión del área de trazado (aviso)


@dataclass
class Anchor:
    name: str                    # X1, X2, Y1, Y2
    px: float | None = None
    py: float | None = None
    value: float | None = None   # valor físico en la unidad del eje; None = pendiente (no se inventa)
    source: str = "usuario"      # auto-tick | auto-grid | auto-marco | usuario
    edited: bool = False

    @property
    def axis(self) -> str:
        return self.name[0]

    @property
    def position(self) -> float | None:
        """Coordenada que usa la calibración: px para X, py para Y."""
        return self.px if self.axis == "X" else self.py

    def to_dict(self) -> dict:
        return asdict(self)


def _finite(x) -> bool:
    return x is not None and isinstance(x, (int, float, np.floating, np.integer)) and math.isfinite(float(x))


@dataclass(frozen=True)
class AxisCalibration:
    axis: str
    p1: float
    v1: float
    p2: float
    v2: float
    scale: str = SCALE_LINEAR

    def _t(self, v):
        v = np.asarray(v, dtype=float)
        return np.log10(v) if self.scale == SCALE_LOG else v

    def _inv(self, t):
        return np.power(10.0, t) if self.scale == SCALE_LOG else t

    @property
    def slope(self) -> float:
        """d(t)/d(pixel), con t = valor (lineal) o log10(valor)."""
        return float((self._t(self.v2) - self._t(self.v1)) / (self.p2 - self.p1))

    def to_value(self, p):
        p = np.asarray(p, dtype=float)
        return self._inv(self._t(self.v1) + (p - self.p1) * self.slope)

    def to_pixel(self, v):
        v = np.asarray(v, dtype=float)
        if self.scale == SCALE_LOG and np.any(v <= 0):
            raise ValueError("En escala logarítmica los valores deben ser positivos.")
        return self.p1 + (self._t(v) - self._t(self.v1)) / self.slope

    def value_per_pixel(self, at_value: float) -> float:
        """|d valor / d píxel| en el punto indicado (resolución de digitalización)."""
        if self.scale == SCALE_LOG:
            return abs(float(at_value) * math.log(10) * self.slope)
        return abs(self.slope)

    def to_dict(self) -> dict:
        return {"axis": self.axis, "pixel_1": self.p1, "value_1": self.v1, "pixel_2": self.p2, "value_2": self.v2,
                "scale": self.scale, "pixel_coordinate": "px" if self.axis == "X" else "py (hacia abajo)",
                "formula": (f"{'log10 ' if self.scale == SCALE_LOG else ''}{self.axis.lower()} = "
                            f"{'log10 ' if self.scale == SCALE_LOG else ''}{self.v1!r} + "
                            f"({'px' if self.axis == 'X' else 'py'} − {self.p1!r})·"
                            f"({'log10 ' if self.scale == SCALE_LOG else ''}{self.v2!r} − "
                            f"{'log10 ' if self.scale == SCALE_LOG else ''}{self.v1!r})/({self.p2!r} − {self.p1!r})")}


def build_axis(a1: Anchor, a2: Anchor, scale: str = SCALE_LINEAR,
               span_px: float | None = None) -> tuple[AxisCalibration | None, list[str], list[str]]:
    """Valida dos anclas de un eje y devuelve (calibración|None, errores, avisos)."""
    axis = a1.axis
    errors: list[str] = []
    warns: list[str] = []
    if scale not in AXIS_SCALES:
        errors.append(f"Escala desconocida para el eje {axis}: {scale!r}.")
        return None, errors, warns
    for a in (a1, a2):
        if a.position is None:
            errors.append(f"{a.name}: falta la posición en la imagen.")
        elif not _finite(a.position):
            errors.append(f"{a.name}: posición no finita.")
        if a.value is None:
            errors.append(f"{a.name}: falta el valor físico (escríbalo; no se infiere de la imagen).")
        elif not _finite(a.value):
            errors.append(f"{a.name}: el valor físico debe ser un número finito.")
    if errors:
        return None, errors, warns
    p1, p2, v1, v2 = float(a1.position), float(a2.position), float(a1.value), float(a2.value)
    if abs(p2 - p1) < MIN_ANCHOR_SEPARATION_PX:
        errors.append(f"Eje {axis}: {a1.name} y {a2.name} están en la misma posición de píxel "
                      f"({p1:.2f} vs {p2:.2f}); la calibración sería degenerada (división por cero).")
    if v1 == v2:
        errors.append(f"Eje {axis}: {a1.name} y {a2.name} tienen el mismo valor físico ({v1:g}).")
    if scale == SCALE_LOG and (v1 <= 0 or v2 <= 0):
        errors.append(f"Eje {axis} logarítmico: los valores de referencia deben ser positivos.")
    if errors:
        return None, errors, warns
    if span_px and abs(p2 - p1) < RECOMMENDED_SEPARATION_FRACTION * span_px:
        warns.append(f"Eje {axis}: las referencias están separadas solo {abs(p2 - p1):.0f} px "
                     f"({100 * abs(p2 - p1) / span_px:.0f} % del área de trazado). Sepárelas más para reducir el "
                     "error de escala.")
    if axis == "Y" and (v2 - v1) * (p1 - p2) < 0:
        warns.append("Eje Y: el valor crece hacia ABAJO en la imagen según las referencias. Es inusual; "
                     "compruebe que Y1/Y2 no estén intercambiados.")
    if axis == "X" and (v2 - v1) * (p2 - p1) < 0:
        warns.append("Eje X: el valor crece hacia la IZQUIERDA según las referencias. Es inusual; "
                     "compruebe que X1/X2 no estén intercambiados.")
    return AxisCalibration(axis, p1, v1, p2, v2, scale), errors, warns


@dataclass(frozen=True)
class Calibration:
    x: AxisCalibration
    y: AxisCalibration

    def to_physical(self, px, py) -> tuple[np.ndarray, np.ndarray]:
        return self.x.to_value(px), self.y.to_value(py)

    def to_pixels(self, xv, yv) -> tuple[np.ndarray, np.ndarray]:
        return self.x.to_pixel(xv), self.y.to_pixel(yv)

    def to_dict(self) -> dict:
        return {"x": self.x.to_dict(), "y": self.y.to_dict()}
