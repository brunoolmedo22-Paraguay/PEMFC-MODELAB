"""Detección automática LOCAL de paneles/ejes, marcas de escala y trazos candidatos.

Todo opera en coordenadas de píxel (ver convención en ``digitizer/__init__``).
No hay OCR: las POSICIONES de ticks/gridlines se proponen como anclas, pero sus
VALORES físicos quedan vacíos hasta que el usuario los escribe.

Pasos:
1. Fondo = color dominante; «oscuridad» D = luminancia del fondo − luminancia.
2. Líneas rectas: D integrada en 3 píxeles transversales + apertura morfológica
   con un núcleo largo. Ejes = líneas fuertes; gridlines = líneas débiles largas.
3. Paneles = esquinas en «L» (eje Y + eje X); se descartan los que contienen otros.
4. Ticks: picos de D en bandas pegadas a cada eje; se conserva la progresión
   regular más larga. Alternativas: gridlines, bordes del marco.
5. Trazos: colores agrupados (modelo de mezcla fondo→color, cobertura α);
   máscara por color dentro del ROI, exclusión de leyendas (rectángulos) y rectas
   largas; componentes conexas → trazos de línea (centroide ponderado por α en
   cada columna) o series de marcadores (centroides de manchas compactas).
6. Remuestreo uniforme en x SIN interpolar a través de huecos.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from . import ALGORITHM_ID, DIGITIZER_VERSION

MAX_ANALYSIS_PIXELS = 8_000_000


# ---------------------------------------------------------------------------
# Estructuras
# ---------------------------------------------------------------------------
@dataclass
class DetectionParams:
    n_points: int = 40                 # puntos remuestreados por trazo
    alpha_min: float = 0.65            # cobertura mínima del color para pertenecer al núcleo del trazo
    color_tolerance: float = 45.0      # distancia RGB perpendicular a la mezcla fondo→color
    min_span_fraction: float = 0.08    # extensión x mínima de un trazo (fracción del ROI)
    trim_caps: bool = True             # recortar extremos por la mitad del grosor (terminaciones de línea)
    exclude_legends: bool = True
    roi: tuple[float, float, float, float] | None = None   # (x0, y0, x1, y1) definido por el usuario
    panel_index: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["roi"] = list(self.roi) if self.roi else None
        return d


@dataclass
class LineSeg:
    orientation: str      # "h" | "v"
    pos: float            # coordenada continua del centro (y para h, x para v)
    start: float
    end: float
    thickness: float
    strength: float       # D integrada media (0-255·grosor)

    @property
    def length(self) -> float:
        return self.end - self.start


@dataclass
class Panel:
    x0: float
    y0: float
    x1: float
    y1: float
    x_axis: LineSeg
    y_axis: LineSeg
    has_top: bool = False
    has_right: bool = False

    @property
    def box(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def contains(self, other: "Panel", tol: float = 3.0) -> bool:
        return (self.x0 - tol <= other.x0 and other.x1 <= self.x1 + tol and self.y0 - tol <= other.y0
                and other.y1 <= self.y1 + tol and self.area > other.area * 1.2)


@dataclass
class TickSet:
    axis: str                     # "X" | "Y"
    positions: list[float]
    kind: str                     # "tick" | "gridline" | "marco"
    regular: bool
    spacing: float | None = None


@dataclass
class TraceCandidate:
    id: str
    kind: str                     # "línea" | "marcadores"
    color_rgb: tuple[int, int, int]
    color_name: str
    dense: np.ndarray             # (n, 2) puntos densos en píxeles (x, y)
    points: np.ndarray            # (m, 2) puntos remuestreados
    confidence: float
    x_range: tuple[float, float]
    coverage: float
    ambiguous_columns: int
    gaps: list[tuple[float, float]]
    thickness: float
    warnings: list[str] = field(default_factory=list)

    @property
    def color_hex(self) -> str:
        return "#%02x%02x%02x" % tuple(int(c) for c in self.color_rgb)

    @property
    def confidence_label(self) -> str:
        return "alta" if self.confidence >= 0.8 else ("media" if self.confidence >= 0.5 else "baja")

    @property
    def label(self) -> str:
        return (f"{self.id}: {self.kind} {self.color_name} ({self.color_hex}) · {len(self.points)} pts · "
                f"confianza {self.confidence_label} ({self.confidence:.2f})")

    def summary(self) -> dict:
        return {"id": self.id, "kind": self.kind, "color": self.color_hex, "color_name": self.color_name,
                "confidence": round(float(self.confidence), 4), "confidence_label": self.confidence_label,
                "x_range_px": [round(float(v), 3) for v in self.x_range], "coverage": round(float(self.coverage), 4),
                "ambiguous_columns": int(self.ambiguous_columns), "thickness_px": round(float(self.thickness), 3),
                "gaps_px": [[round(a, 1), round(b, 1)] for a, b in self.gaps], "n_points": int(len(self.points)),
                "n_dense": int(len(self.dense)), "warnings": list(self.warnings)}


@dataclass
class DetectionResult:
    params: DetectionParams
    image_size: tuple[int, int]
    panels: list[Panel]
    panel_index: int | None
    plot_box: tuple[float, float, float, float] | None
    roi: tuple[float, float, float, float]
    ticks: dict[str, TickSet | None]
    candidates: list[TraceCandidate]
    excluded_regions: list[tuple[float, float, float, float]]
    background_rgb: tuple[int, int, int]
    warnings: list[str]
    notes: list[str]
    elapsed_s: float
    analysis_scale: float = 1.0

    @property
    def best_candidate(self) -> TraceCandidate | None:
        good = [c for c in self.candidates if c.confidence >= 0.5]
        return good[0] if good else None

    def summary(self) -> dict:
        return {
            "algorithm": ALGORITHM_ID, "version": DIGITIZER_VERSION, "params": self.params.to_dict(),
            "image_size_px": list(self.image_size), "analysis_scale": self.analysis_scale,
            "panels_px": [[round(v, 2) for v in p.box] for p in self.panels], "panel_index": self.panel_index,
            "plot_box_px": [round(v, 2) for v in self.plot_box] if self.plot_box else None,
            "roi_px": [round(v, 2) for v in self.roi],
            "ticks_px": {k: (None if t is None else {"positions": [round(p, 2) for p in t.positions], "kind": t.kind,
                                                     "regular": t.regular, "spacing": t.spacing})
                         for k, t in self.ticks.items()},
            "excluded_regions_px": [[round(v, 1) for v in r] for r in self.excluded_regions],
            "background_rgb": list(self.background_rgb), "candidates": [c.summary() for c in self.candidates],
            "warnings": list(self.warnings), "notes": list(self.notes), "elapsed_s": round(self.elapsed_s, 3),
        }


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
_COLOR_NAMES = [
    ("rojo", 0), ("naranja", 28), ("amarillo", 55), ("verde", 120), ("cian", 185), ("azul", 220),
    ("morado", 275), ("magenta", 310), ("rojo", 360),
]


def color_name(rgb) -> str:
    r, g, b = (float(c) / 255.0 for c in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 0.12:
        return "negro" if mx < 0.35 else "gris"
    if mx - mn < 0.35 and mx < 0.55 and r >= g >= b:
        return "marrón"
    h = 0.0
    if mx == r:
        h = (60 * ((g - b) / (mx - mn)) + 360) % 360
    elif mx == g:
        h = 60 * ((b - r) / (mx - mn)) + 120
    else:
        h = 60 * ((r - g) / (mx - mn)) + 240
    return min(_COLOR_NAMES, key=lambda t: abs(t[1] - h))[0]


def _luma(rgb: np.ndarray) -> np.ndarray:
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def _background(rgb: np.ndarray) -> np.ndarray:
    q = (rgb[::3, ::3] // 8).reshape(-1, 3)
    vals, counts = np.unique(q, axis=0, return_counts=True)
    top = vals[np.argmax(counts)]
    sel = (rgb[::3, ::3] // 8 == top).all(-1)
    return np.median(rgb[::3, ::3][sel], axis=0)


def _runs(mask_1d: np.ndarray) -> list[tuple[int, int]]:
    """Tramos [a, b) de valores True."""
    m = np.concatenate([[False], mask_1d.astype(bool), [False]])
    d = np.flatnonzero(np.diff(m.astype(np.int8)))
    return list(zip(d[::2].tolist(), d[1::2].tolist()))


# ---------------------------------------------------------------------------
# Líneas rectas, paneles y ticks
# ---------------------------------------------------------------------------
def _line_segments(D: np.ndarray, orientation: str, min_len: int, lo: float, hi: float | None) -> list[LineSeg]:
    """Segmentos rectos con D integrada (3 px transversales) en [lo, hi)."""
    k = np.ones((3, 1) if orientation == "h" else (1, 3), np.float32)
    S = cv2.filter2D(D.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
    mask = (S >= lo) if hi is None else ((S >= lo) & (S < hi))
    # Los píxeles de un trazo fuerte no deben contar como línea débil (franja vecina a una línea fuerte).
    kern = cv2.getStructuringElement(cv2.MORPH_RECT, (min_len, 1) if orientation == "h" else (1, min_len))
    opened = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kern)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    segs = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if orientation == "h":
            if w < min_len or h > 8:
                continue
            rows = np.arange(y, y + h)
            prof = D[y:y + h, x:x + w].mean(axis=1).clip(min=0)
            pos = float((prof * (rows + 0.5)).sum() / max(prof.sum(), 1e-9))
            # ampliar a filas vecinas con tinta (antialias) para el centro
            lo_r, hi_r = max(0, y - 1), min(D.shape[0], y + h + 1)
            prof2 = D[lo_r:hi_r, x:x + w].mean(axis=1).clip(min=0)
            pos = float((prof2 * (np.arange(lo_r, hi_r) + 0.5)).sum() / max(prof2.sum(), 1e-9))
            segs.append(LineSeg("h", pos, float(x), float(x + w), float(h), float(prof2.sum())))
        else:
            if h < min_len or w > 8:
                continue
            lo_c, hi_c = max(0, x - 1), min(D.shape[1], x + w + 1)
            prof2 = D[y:y + h, lo_c:hi_c].mean(axis=0).clip(min=0)
            pos = float((prof2 * (np.arange(lo_c, hi_c) + 0.5)).sum() / max(prof2.sum(), 1e-9))
            segs.append(LineSeg("v", pos, float(y), float(y + h), float(w), float(prof2.sum())))
    return segs


def _find_panels(H: list[LineSeg], V: list[LineSeg], W: int, Hh: int) -> list[Panel]:
    panels = []
    for v in V:
        for h in H:
            tol = max(4.0, 2.5 * max(v.thickness, h.thickness))
            # Esquina inferior izquierda: el eje Y termina en el eje X; el eje X empieza en el eje Y.
            if abs(h.start - v.pos) > tol + 2 or abs(v.end - h.pos) > tol + 2:
                continue
            x0, y1 = v.pos, h.pos
            x1, y0 = h.end, v.start
            if (x1 - x0) < 0.18 * W or (y1 - y0) < 0.15 * Hh:
                continue
            top = any(abs(o.pos - y0) <= tol + 2 and o.start <= x0 + tol + 2 and o.end >= x1 - tol - 2 for o in H)
            right = any(abs(o.pos - x1) <= tol + 2 and o.start <= y0 + tol + 2 and o.end >= y1 - tol - 2 for o in V)
            panels.append(Panel(x0, y0, x1, y1, h, v, top, right))
    # deduplicar y quitar contenedores (marco exterior de una figura compuesta)
    uniq: list[Panel] = []
    for p in sorted(panels, key=lambda p: -p.area):
        if any(abs(p.x0 - q.x0) < 4 and abs(p.y1 - q.y1) < 4 for q in uniq):
            continue
        uniq.append(p)
    inner = [p for p in uniq if not any(p.contains(q) for q in uniq if q is not p)]
    # orden de lectura: filas (por y0) y luego columnas
    inner.sort(key=lambda p: (round(p.y0 / max(Hh * 0.2, 1)), p.x0))
    return inner


def _regular_subset(pos: list[float], min_count: int = 3) -> tuple[list[float], float | None]:
    """Progresión aritmética más larga (tolerancia 1,5 px) dentro de las posiciones."""
    pos = sorted(pos)
    best: list[float] = []
    best_d = None
    n = len(pos)
    for i in range(n):
        for j in range(i + 1, n):
            d = pos[j] - pos[i]
            if d < 6:
                continue
            seq = [pos[i]]
            k = pos[i] + d
            tol = max(1.5, 0.02 * d)
            while True:
                near = [p for p in pos if abs(p - k) <= tol]
                if not near:
                    break
                p = min(near, key=lambda p: abs(p - k))
                seq.append(p)
                k = p + d
            if len(seq) > len(best) or (len(seq) == len(best) and best_d is not None and d > best_d):
                best, best_d = seq, d
    if len(best) < min_count:
        return [], None
    # espaciado refinado por mínimos cuadrados
    idx = np.arange(len(best))
    d = float(np.polyfit(idx, best, 1)[0])
    return best, d


def _ticks_near_axis(D: np.ndarray, axis: LineSeg, axis_name: str) -> TickSet | None:
    """Ticks como picos de D en bandas exteriores/interiores pegadas al eje."""
    half = axis.thickness / 2 + 1.0
    best = None
    for side in (+1, -1):
        if axis_name == "X":
            r0 = int(round(axis.pos + half)) if side > 0 else int(round(axis.pos - half - 7))
            r1 = r0 + 7
            c0, c1 = max(0, int(axis.start) - 3), min(D.shape[1], int(math.ceil(axis.end)) + 3)
            if r0 < 0 or r1 > D.shape[0]:
                continue
            band = D[r0:r1, c0:c1]
            prof = band.sum(axis=0)
        else:
            c0 = int(round(axis.pos + half)) if side > 0 else int(round(axis.pos - half - 7))
            c1 = c0 + 7
            r0, r1 = max(0, int(axis.start) - 3), min(D.shape[0], int(math.ceil(axis.end)) + 3)
            if c0 < 0 or c1 > D.shape[1]:
                continue
            band = D[r0:r1, c0:c1]
            prof = band.sum(axis=1)
        if prof.size < 10:
            continue
        prof = np.clip(prof - np.median(prof), 0, None)   # quitar el sangrado constante del propio eje
        sm = np.convolve(prof, np.ones(3), mode="same")
        thr = max(250.0, 0.35 * float(sm.max()))
        peaks = []
        i = 0
        while i < sm.size:
            if sm[i] >= thr:
                j = i
                while j < sm.size and sm[j] >= thr:
                    j += 1
                if j - i <= 6:  # un tick es estrecho
                    a, b = max(0, i - 1), min(prof.size, j + 1)
                    w = prof[a:b].astype(float)
                    c = float((w * (np.arange(a, b) + 0.5)).sum() / max(w.sum(), 1e-9))
                    peaks.append(c + (c0 if axis_name == "X" else r0))
                i = j
            else:
                i += 1
        reg, d = _regular_subset(peaks)
        if reg and (best is None or len(reg) > len(best.positions)):
            best = TickSet(axis_name, reg, "tick", True, d)
    return best


def _gridlines(D: np.ndarray, box, axis_name: str) -> TickSet | None:
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    sub = D[max(0, y0):y1, max(0, x0):x1]
    if sub.size == 0:
        return None
    if axis_name == "X":   # gridlines verticales
        segs = _line_segments(sub, "v", max(20, int(0.7 * sub.shape[0])), 8.0, None)
        pos = [s.pos + max(0, x0) for s in segs]
    else:
        segs = _line_segments(sub, "h", max(20, int(0.7 * sub.shape[1])), 8.0, None)
        pos = [s.pos + max(0, y0) for s in segs]
    margin = 4
    lo, hi = (box[0], box[2]) if axis_name == "X" else (box[1], box[3])
    pos = [p for p in pos if lo + margin < p < hi - margin]
    if len(pos) < 1:
        return None
    # los bordes del panel pueden coincidir con valores rotulados: se aceptan solo si encajan en la progresión
    reg, d = _regular_subset(pos + [float(lo), float(hi)])
    if not reg or sum(1 for p in reg if lo + margin < p < hi - margin) < 1:
        return None
    return TickSet(axis_name, reg, "gridline", True, d)


# ---------------------------------------------------------------------------
# Trazos
# ---------------------------------------------------------------------------
def _alpha_map(rgb: np.ndarray, bg: np.ndarray, color: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cobertura α del color sobre el fondo y distancia perpendicular a la mezcla."""
    v = (bg - color).astype(np.float32)
    nv = float(v @ v)
    if nv < 1e-6:
        return np.zeros(rgb.shape[:2], np.float32), np.full(rgb.shape[:2], 1e9, np.float32)
    d = (bg[None, None, :] - rgb.astype(np.float32))
    alpha = (d @ v) / nv
    perp = np.linalg.norm(d - alpha[..., None] * v[None, None, :], axis=-1)
    return alpha.astype(np.float32), perp.astype(np.float32)


def _color_clusters(rgb: np.ndarray, bg: np.ndarray, region_mask: np.ndarray, max_clusters: int = 8) -> list[np.ndarray]:
    px = rgb[region_mask].astype(np.int32)
    if px.size == 0:
        return []
    chroma = px.max(1) - px.min(1)
    luma = px @ np.array([0.299, 0.587, 0.114])
    bg_l = float(bg @ np.array([0.299, 0.587, 0.114]))
    chromatic = px[chroma >= 50]
    dark = px[(chroma < 50) & (luma < bg_l - 150)]
    min_count = max(25, int(0.0004 * region_mask.sum()))
    colors = []
    rest = chromatic
    while rest.shape[0] >= min_count and len(colors) < max_clusters:
        q = rest // 24
        vals, inv, counts = np.unique(q, axis=0, return_inverse=True, return_counts=True)
        k = int(np.argmax(counts))
        if counts[k] < min_count:
            break
        members = rest[inv.ravel() == k]
        u, c = np.unique(members, axis=0, return_counts=True)
        rep = u[np.argmax(c)].astype(float)
        # mezcla fondo→rep: retirar del resto los colores cercanos (antialias del mismo trazo)
        v = bg - rep
        d = bg[None, :] - rest
        a = (d @ v) / max(float(v @ v), 1e-9)
        perp = np.linalg.norm(d - a[:, None] * v[None, :], axis=1)
        same = (perp < 45) & (a > 0.15)
        if same.sum() < min_count:
            rest = rest[inv.ravel() != k]
            continue
        colors.append(rep)
        rest = rest[~same]
    if dark.shape[0] >= min_count:
        u, c = np.unique(dark // 16, axis=0, return_counts=True)
        darkest = dark[(dark // 16 == u[np.argmax(c)]).all(1)]
        colors.append(np.median(darkest, axis=0).astype(float))
    return colors


def _legend_boxes(D: np.ndarray, roi_mask: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Rectángulos cerrados (marcos de leyenda) dentro del ROI."""
    ink = ((D > 30) & roi_mask).astype(np.uint8)
    ys, xs = np.nonzero(roi_mask)
    if xs.size == 0:
        return []
    rw, rh = xs.max() - xs.min(), ys.max() - ys.min()
    hk = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (15, 1)))
    vk = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 12)))
    # Las gridlines (rectas que cruzan casi todo el ROI) se retiran antes: si tocan el marco de la
    # leyenda lo fusionarían con la retícula.
    hl = cv2.morphologyEx(hk, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(16, int(0.6 * rw)), 1)))
    vl = cv2.morphologyEx(vk, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(13, int(0.6 * rh)))))
    long_lines = cv2.dilate(hl | vl, np.ones((3, 3), np.uint8))
    lines = cv2.dilate((hk | vk) & (1 - long_lines), np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w < 20 or h < 12 or w > 0.6 * rw or h > 0.6 * rh:
            continue
        comp = lab[y:y + h, x:x + w] == i
        sides = [comp[:4, :].any(0).mean(), comp[-4:, :].any(0).mean(), comp[:, :4].any(1).mean(),
                 comp[:, -4:].any(1).mean()]
        interior = comp[5:-5, 5:-5].mean() if w > 12 and h > 12 else 1.0
        if min(sides) >= 0.75 and interior < 0.3:
            boxes.append((x, y, x + w, y + h))
    return boxes


def _column_trace(alpha: np.ndarray, core: np.ndarray, x0: int, x1: int) -> tuple[dict[int, float], list[int], list[int]]:
    """Centroide α-ponderado por columna con seguimiento de continuidad."""
    ys: dict[int, float] = {}
    lengths: list[int] = []
    ambiguous: list[int] = []
    hist: list[tuple[int, float]] = []
    for x in range(x0, x1):
        runs = _runs(core[:, x])
        if not runs:
            continue
        if len(runs) > 1:
            ambiguous.append(x)
            if len(hist) >= 2:
                (xa, ya), (xb, yb) = hist[-min(len(hist), 6)], hist[-1]
                pred = yb + (yb - ya) / max(xb - xa, 1) * (x - xb)
            elif hist:
                pred = hist[-1][1]
            else:
                pred = None
            if pred is None:
                a, b = max(runs, key=lambda r: r[1] - r[0])
            else:
                a, b = min(runs, key=lambda r: abs((r[0] + r[1]) / 2 - pred))
        else:
            a, b = runs[0]
        lo, hi = max(0, a - 1), min(core.shape[0], b + 1)
        w = np.clip(alpha[lo:hi, x], 0.0, 1.0).astype(float)
        # el antialias exterior cuenta; píxeles ajenos al trazo (fuera de ±1) no
        y = float((w * (np.arange(lo, hi) + 0.5)).sum() / max(w.sum(), 1e-9))
        ys[x] = y
        lengths.append(b - a)
        hist.append((x, y))
    return ys, lengths, ambiguous


def _trim_and_sample(ys: dict[int, float], thickness: float, params: DetectionParams,
                     gap_min: float) -> tuple[np.ndarray, np.ndarray, list[tuple[float, float]], tuple[float, float]]:
    cols = np.array(sorted(ys))
    xc = cols + 0.5
    yc = np.array([ys[c] for c in cols])
    # huecos
    gaps = []
    for a, b in zip(cols[:-1], cols[1:]):
        if b - a - 1 >= gap_min:
            gaps.append((float(a + 1), float(b)))
    lo, hi = float(cols[0]), float(cols[-1] + 1)
    if params.trim_caps and len(cols) > 6:
        # terminaciones: medio grosor proyectado sobre x, con la pendiente local en cada extremo
        def ext(sl):
            th = math.atan(abs(sl))
            w_perp = thickness * math.cos(th)
            return 0.5 * w_perp * math.cos(th)
        k = min(8, len(cols) - 1)
        sl0 = (yc[k] - yc[0]) / max(xc[k] - xc[0], 1)
        sl1 = (yc[-1] - yc[-1 - k]) / max(xc[-1] - xc[-1 - k], 1)
        lo, hi = lo + ext(sl0), hi - ext(sl1)
    dense_mask = (xc >= lo) & (xc <= hi)
    dense = np.column_stack([xc[dense_mask], yc[dense_mask]])
    if dense.shape[0] == 0:
        return dense, dense, gaps, (lo, hi)
    xs = np.linspace(max(lo, dense[0, 0]), min(hi, dense[-1, 0]), max(2, int(params.n_points)))
    pts = []
    for x in xs:
        if any(a - 0.5 <= x <= b + 0.5 for a, b in gaps):
            continue                       # no se inventan puntos en huecos
        pts.append((float(x), float(np.interp(x, dense[:, 0], dense[:, 1]))))
    return dense, np.array(pts, float).reshape(-1, 2), gaps, (lo, hi)


def detect(rgb: np.ndarray, params: DetectionParams | None = None) -> DetectionResult:
    """Detección automática completa (en píxeles; nunca produce valores físicos)."""
    t0 = time.perf_counter()
    params = params or DetectionParams()
    warnings: list[str] = []
    notes: list[str] = []
    H0, W0 = rgb.shape[:2]
    scale = 1.0
    if H0 * W0 > MAX_ANALYSIS_PIXELS:
        scale = math.sqrt(MAX_ANALYSIS_PIXELS / (H0 * W0))
        rgb = cv2.resize(rgb, (int(W0 * scale), int(H0 * scale)), interpolation=cv2.INTER_AREA)
        notes.append(f"Imagen grande: análisis a escala {scale:.3f}; coordenadas reescaladas al original.")
    Hh, W = rgb.shape[:2]
    s = lambda v: v * scale          # noqa: E731  original → análisis
    inv = lambda v: v / scale        # noqa: E731  análisis → original

    bg = _background(rgb).astype(float)
    if float(bg @ np.array([0.299, 0.587, 0.114])) < 140:
        warnings.append("Fondo oscuro detectado: la detección está pensada para gráficos sobre fondo claro; "
                        "revise el resultado o trace manualmente.")
    D = np.clip(float(bg @ np.array([0.299, 0.587, 0.114])) - _luma(rgb.astype(np.float32)), 0, 255)

    # ---- región de búsqueda (ROI de usuario ampliado o imagen completa)
    if params.roi:
        rx0, ry0, rx1, ry1 = (s(v) for v in params.roi)
        rx0, rx1 = sorted((rx0, rx1))
        ry0, ry1 = sorted((ry0, ry1))
        mx, my = 0.06 * (rx1 - rx0) + 12, 0.06 * (ry1 - ry0) + 12
        sx0, sy0 = int(max(0, rx0 - mx)), int(max(0, ry0 - my))
        sx1, sy1 = int(min(W, rx1 + mx)), int(min(Hh, ry1 + my))
    else:
        sx0, sy0, sx1, sy1 = 0, 0, W, Hh
    Ds = D[sy0:sy1, sx0:sx1]
    sw, sh = sx1 - sx0, sy1 - sy0
    min_len = max(40, int(0.12 * min(sw, sh)))
    Hs = [LineSeg("h", l.pos + sy0, l.start + sx0, l.end + sx0, l.thickness, l.strength)
          for l in _line_segments(Ds, "h", min_len, 150.0, None)]
    Vs = [LineSeg("v", l.pos + sx0, l.start + sy0, l.end + sy0, l.thickness, l.strength)
          for l in _line_segments(Ds, "v", min_len, 150.0, None)]
    panels = _find_panels(Hs, Vs, sw, sh)
    panel_index = None
    plot_box = None
    if panels:
        if params.panel_index is not None and 0 <= params.panel_index < len(panels):
            panel_index = params.panel_index
        else:
            panel_index = 0
            if params.roi:  # el panel que más se solapa con el ROI
                def ov(p):
                    ix = max(0.0, min(p.x1, rx1) - max(p.x0, rx0))
                    iy = max(0.0, min(p.y1, ry1) - max(p.y0, ry0))
                    return ix * iy
                panel_index = int(np.argmax([ov(p) for p in panels]))
        plot_box = panels[panel_index].box
        if len(panels) > 1:
            warnings.append(f"Se detectaron {len(panels)} paneles con ejes. Se usa el panel {panel_index + 1}; "
                            "elija otro en «Panel» o delimite el ROI del gráfico deseado.")
        p = panels[panel_index]
        if not (p.has_top and p.has_right):
            notes.append("Panel con ejes en L (sin marco completo).")
    else:
        warnings.append("No se detectaron ejes rectos (dos líneas oscuras en «L»). La imagen puede estar rotada, "
                        "en perspectiva, recortada o sin ejes: fije manualmente las cuatro referencias.")

    # ---- ticks / gridlines / marco → posiciones propuestas para las anclas
    ticks: dict[str, TickSet | None] = {"X": None, "Y": None}
    if panel_index is not None:
        p = panels[panel_index]
        for name, ax in (("X", p.x_axis), ("Y", p.y_axis)):
            t = _ticks_near_axis(D, ax, name)
            if t is None:
                t = _gridlines(D, p.box, name)
            if t is None:
                lo, hi = (p.x0, p.x1) if name == "X" else (p.y1, p.y0)
                t = TickSet(name, [lo, hi] if name == "X" else [hi, lo], "marco", False, None)
                warnings.append(f"Eje {name}: sin ticks ni gridlines regulares; las anclas propuestas son los bordes "
                                "del marco. Confirme que coinciden con valores rotulados.")
            ticks[name] = t

    # ---- ROI de trazos
    if params.roi:
        roi = (rx0, ry0, rx1, ry1)
    elif plot_box is not None:
        p = panels[panel_index]
        mg_x = p.y_axis.thickness / 2 + 2.5
        mg_y = p.x_axis.thickness / 2 + 2.5
        roi = (p.x0 + mg_x, p.y0 + (mg_y if p.has_top else 0), p.x1 - (mg_x if p.has_right else 0), p.y1 - mg_y)
    else:
        roi = (0.0, 0.0, float(W), float(Hh))
    ix0, iy0 = max(0, int(math.ceil(roi[0]))), max(0, int(math.ceil(roi[1])))
    ix1, iy1 = min(W, int(math.floor(roi[2]))), min(Hh, int(math.floor(roi[3])))
    roi_mask = np.zeros((Hh, W), bool)
    roi_mask[iy0:iy1, ix0:ix1] = True
    # excluir rectas largas (ejes/gridlines/marcos que invadan el ROI)
    excluded_regions: list[tuple[float, float, float, float]] = []
    if params.exclude_legends:
        for (x0b, y0b, x1b, y1b) in _legend_boxes(D, roi_mask):
            roi_mask[max(0, y0b - 2):y1b + 2, max(0, x0b - 2):x1b + 2] = False
            excluded_regions.append((float(x0b), float(y0b), float(x1b), float(y1b)))
        if excluded_regions:
            notes.append(f"{len(excluded_regions)} recuadro(s) tipo leyenda excluidos del análisis de trazos.")
    roi_w = max(1, ix1 - ix0)

    # ---- trazos candidatos por color
    candidates: list[TraceCandidate] = []
    colors = _color_clusters(rgb, bg, roi_mask)
    if not colors:
        warnings.append("No hay píxeles de trazo distinguibles del fondo dentro del ROI.")
    for color in colors:
        alpha, perp = _alpha_map(rgb, bg, color)
        is_dark = (color.max() - color.min()) < 50
        core = (alpha >= params.alpha_min) & (perp <= params.color_tolerance) & roi_mask
        if is_dark:
            # quitar rectas largas oscuras (gridlines oscuras, ejes interiores)
            for kern in ((max(25, roi_w // 3), 1), (1, max(25, (iy1 - iy0) // 3))):
                straight = cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_OPEN,
                                            cv2.getStructuringElement(cv2.MORPH_RECT, kern))
                core &= ~cv2.dilate(straight, np.ones((3, 3), np.uint8)).astype(bool)
        straight_any = (cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1)))
                        | cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25)))).astype(bool)
        core_u8 = cv2.morphologyEx(core.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)) & roi_mask
        n, lab, stats, cents = cv2.connectedComponentsWithStats(core_u8.astype(np.uint8), connectivity=8)
        cname = color_name(color)
        line_comps, blobs = [], []
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if w >= max(15, params.min_span_fraction * roi_w):
                line_comps.append(i)
            elif 2 <= w <= 30 and 2 <= h <= 30 and area >= 4 and 0.4 <= w / h <= 2.5 and area / (w * h) >= 0.35:
                blobs.append(i)
        # agrupar componentes de línea en trazos (encadenando a lo largo de x)
        traces: list[list[int]] = []
        for i in sorted(line_comps, key=lambda i: stats[i][0]):
            x, y, w, h, _ = stats[i]
            placed = False
            for tr in traces:
                last = tr[-1]
                lx, ly, lw, lh, _ = stats[last]
                if x >= lx + lw - 3 and x - (lx + lw) <= max(40, 0.05 * roi_w):
                    ys_last = np.nonzero(lab[:, lx + lw - 1] == last)[0]
                    ys_new = np.nonzero(lab[:, x] == i)[0]
                    if ys_last.size and ys_new.size and abs(ys_last.mean() - ys_new.mean()) <= max(25, 0.08 * (iy1 - iy0)):
                        tr.append(i)
                        placed = True
                        break
            if not placed:
                traces.append([i])
        for tr in traces:
            m = np.isin(lab, tr)
            xs_ = np.nonzero(m.any(0))[0]
            x0c, x1c = int(xs_.min()), int(xs_.max()) + 1
            ys, lengths, amb = _column_trace(np.where(m | (cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0),
                                                      alpha, 0), m, x0c, x1c)
            if len(ys) < 3:
                continue
            thick = float(np.median(lengths)) if lengths else 1.0
            gap_min = max(3.0, 2.0 * thick)
            dense, pts, gaps, (lo, hi) = _trim_and_sample(ys, thick, params, gap_min)
            if pts.shape[0] < 2:
                continue
            span = hi - lo
            gap_len = sum(b - a for a, b in gaps)
            coverage = max(0.0, 1.0 - gap_len / max(span, 1))
            amb_frac = len(amb) / max(len(ys), 1)
            lens = np.asarray(lengths, float)
            thick_cv = float(np.std(lens) / max(np.mean(lens), 1e-9)) if lens.size else 1.0
            conf = coverage * (1 - min(amb_frac, 1.0)) * min(1.0, span / (0.4 * roi_w)) * (1.0 / (1.0 + 0.5 * max(0.0, thick_cv - 0.5)))
            w_ = []
            straight_frac = float(straight_any[m].mean()) if m.any() else 0.0
            if straight_frac > 0.5:
                conf *= 0.2
                w_.append(f"El {100 * straight_frac:.0f} % del trazo son rectas horizontales/verticales: probablemente es "
                          "un marco, una gridline o una línea de referencia, no una curva de datos.")
            if gaps:
                w_.append(f"{len(gaps)} hueco(s) sin trazo ({', '.join(f'x≈{inv(a):.0f}–{inv(b):.0f} px' for a, b in gaps[:4])}): "
                          "no se interpolan puntos dentro de ellos.")
            if amb:
                w_.append(f"{len(amb)} columna(s) con varios tramos del mismo color (cruces, marcadores u oclusión): "
                          "se siguió la continuidad; revise esa zona.")
            if thick_cv > 1.0:
                w_.append("Grosor muy irregular: posible superposición con marcadores, texto u otra curva.")
            candidates.append(TraceCandidate(
                id="", kind="línea", color_rgb=tuple(int(round(c)) for c in color), color_name=cname,
                dense=inv(dense), points=inv(pts), confidence=float(conf), x_range=(inv(lo), inv(hi)),
                coverage=coverage, ambiguous_columns=len(amb), gaps=[(inv(a), inv(b)) for a, b in gaps],
                thickness=inv(thick), warnings=w_))
        if len(blobs) >= 4:
            areas = np.array([stats[i][4] for i in blobs], float)
            med = np.median(areas)
            keep = [i for i, a in zip(blobs, areas) if 0.3 * med <= a <= 3.0 * med]
            if len(keep) >= 4:
                pts = []
                for i in keep:
                    x, y, w, h, _ = stats[i]
                    sub = np.clip(alpha[y:y + h, x:x + w], 0, 1) * (lab[y:y + h, x:x + w] == i)
                    yy, xx = np.mgrid[y:y + h, x:x + w]
                    tot = max(float(sub.sum()), 1e-9)
                    pts.append(((sub * (xx + 0.5)).sum() / tot, (sub * (yy + 0.5)).sum() / tot))
                pts = np.array(sorted(pts), float)
                span = float(pts[-1, 0] - pts[0, 0])
                conf = min(1.0, span / (0.4 * roi_w)) * min(1.0, len(keep) / 6) * 0.9
                candidates.append(TraceCandidate(
                    id="", kind="marcadores", color_rgb=tuple(int(round(c)) for c in color), color_name=cname,
                    dense=inv(pts), points=inv(pts), confidence=float(conf), x_range=(inv(pts[0, 0]), inv(pts[-1, 0])),
                    coverage=1.0, ambiguous_columns=0, gaps=[], thickness=float(inv(math.sqrt(med))),
                    warnings=["Serie de marcadores: cada punto es el centroide de un símbolo. Si los marcadores son "
                              "los datos medidos y la línea un ajuste/modelo, digitalice los marcadores."]))
    candidates.sort(key=lambda c: (-c.confidence * (c.x_range[1] - c.x_range[0]),))
    for k, c in enumerate(candidates):
        c.id = f"C{k + 1}"
    lines = [c for c in candidates if c.kind == "línea"]
    marks = [c for c in candidates if c.kind == "marcadores"]
    if lines and marks:
        warnings.append("Hay trazos continuos y series de marcadores: en publicaciones, los marcadores suelen ser los "
                        "datos medidos y las líneas un modelo o guía visual. Elija el candidato que corresponde.")
    if len(lines) > 1:
        warnings.append(f"Se detectaron {len(lines)} trazos continuos distintos: elija uno (no se mezclan puntos).")
    if not any(c.confidence >= 0.5 for c in candidates):
        if candidates:
            warnings.append("Ningún candidato alcanza confianza suficiente (≥ 0,5): no se selecciona ninguno "
                            "automáticamente. Elija uno revisándolo o trace la curva manualmente.")
        else:
            warnings.append("No se encontró un trazado fiable (sin componentes alargadas ni series de marcadores). "
                            "Use el modo «Añadir» para trazar la curva manualmente.")
    # devolver coordenadas al tamaño original
    def sc_box(b):
        return None if b is None else tuple(float(inv(v)) for v in b)
    panels_o = [Panel(inv(p.x0), inv(p.y0), inv(p.x1), inv(p.y1),
                      LineSeg("h", inv(p.x_axis.pos), inv(p.x_axis.start), inv(p.x_axis.end), inv(p.x_axis.thickness), p.x_axis.strength),
                      LineSeg("v", inv(p.y_axis.pos), inv(p.y_axis.start), inv(p.y_axis.end), inv(p.y_axis.thickness), p.y_axis.strength),
                      p.has_top, p.has_right) for p in panels]
    ticks_o = {k: (None if t is None else TickSet(t.axis, [float(inv(v)) for v in t.positions], t.kind, t.regular,
                                                  None if t.spacing is None else float(inv(t.spacing))))
               for k, t in ticks.items()}
    return DetectionResult(params=params, image_size=(W0, H0), panels=panels_o, panel_index=panel_index,
                           plot_box=sc_box(plot_box), roi=sc_box(roi), ticks=ticks_o, candidates=candidates,
                           excluded_regions=[sc_box(r) for r in excluded_regions],
                           background_rgb=tuple(int(round(c)) for c in bg), warnings=warnings, notes=notes,
                           elapsed_s=time.perf_counter() - t0, analysis_scale=scale)
