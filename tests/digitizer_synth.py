"""Imágenes sintéticas con transformación píxel↔dato EXACTA (matplotlib), para pruebas.

Las imágenes se generan en memoria; no son datos experimentales.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def polarization(j):
    j = np.asarray(j, float)
    return 1.0 - 0.06 * np.log(j / 0.01 + 1) - 0.25 * j - 0.03 * np.exp(2.2 * (j - 1.2))


def render(kind: str = "line", *, xlog=False, axes=True, curve=True, color="#1f77b4", marker=None,
           y_scale=1.0, xlim=(0.0, 1.5), ylim=(0.4, 1.1), j=None, dpi=100, size=(9, 6)):
    """Devuelve (png_bytes, truth(j, v), pixel_of(x, y)) con la convención y hacia abajo."""
    j = np.linspace(0.05, 1.4, 60) if j is None else np.asarray(j, float)
    v = polarization(j) * y_scale
    fig, ax = plt.subplots(figsize=size, dpi=dpi)
    if curve:
        if marker:
            ax.plot(j, v, linestyle="none", marker=marker, color=color, markersize=6)
        else:
            ax.plot(j, v, color=color, lw=2.5)
    if xlog:
        ax.set_xscale("log")
    ax.set_xlim(*xlim)
    ax.set_ylim(ylim[0] * y_scale, ylim[1] * y_scale)
    if not axes:
        ax.axis("off")
    fig.canvas.draw()
    W, H = fig.canvas.get_width_height()
    trans = ax.transData

    def pixel_of(x, y):
        d = trans.transform(np.column_stack([np.atleast_1d(x), np.atleast_1d(y)]))
        return d[:, 0], H - d[:, 1]

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue(), (j, v), pixel_of
