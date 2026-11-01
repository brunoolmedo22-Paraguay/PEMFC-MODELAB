"""Reconocimiento automático de los valores de los ejes: OCR + verificación geométrica.

Para cada eje:
1. Se localizan las cajas de texto en la banda exterior del eje (debajo de X, a la izquierda de Y).
2. Se clasifican en etiquetas de tick, título del eje y multiplicador (``1e3``, ``×10³``).
3. Cada etiqueta produce una o varias INTERPRETACIONES numéricas (coma o punto decimal, miles,
   exponente aplanado «10-3» → 10⁻³, notación científica…). No se elige ninguna a priori.
4. Verificación geométrica: un ajuste robusto (pares de etiquetas → consenso) busca la escala
   (lineal o log10) y la combinación de interpretaciones para la que las posiciones de los ticks son
   coherentes con sus valores. Las etiquetas incoherentes se marcan como atípicas.
5. Estado: CONFIABLE / REVISION / INSUFICIENTE, con razones observables (número de etiquetas
   coherentes, residuo en píxeles, confianza OCR, ambigüedades, multiplicadores, orientación).

Nunca se inventan valores: sin etiquetas coherentes no hay calibración automática.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from itertools import product

import numpy as np

from .detection import LineSeg, Panel, TickSet
from .ocr import OCRUnavailable, TextBox, find_text_boxes, recognize_boxes

ST_RELIABLE = "CONFIABLE"
ST_REVIEW = "REVISION"
ST_INSUFFICIENT = "INSUFICIENTE"
STATUS_TEXT = {ST_RELIABLE: "Reconocimiento confiable", ST_REVIEW: "Reconocimiento pendiente de revisión",
               ST_INSUFFICIENT: "Reconocimiento insuficiente"}

_MINUS = str.maketrans({"−": "-", "–": "-", "—": "-", "‒": "-", "﹣": "-", "－": "-"})
_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8"})
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


@dataclass
class Interp:
    value: float
    kind: str          # decimal | decimal_coma | miles | entero | potencia10 | cientifica | porcentaje
    penalty: float     # preferencia (0 = interpretación literal)


def parse_label(text: str) -> list[Interp]:
    """Interpretaciones numéricas posibles de una etiqueta OCR (lista vacía si no es un número)."""
    t = (text or "").strip().translate(_MINUS).translate(_SUP).replace(" ", "").replace("\u00a0", "")
    t = t.strip("()[]{}'\"`")
    t = re.sub(r"[-.,]+$", "", t) if re.search(r"\d[-.,]+$", t) and not re.fullmatch(r"[-+]?\d+[.,]", t) else t
    if not t:
        return []
    if re.fullmatch(r"[-+0-9OoDlI|SB.,eE×x·*^%]+", t) and re.search(r"\d", t):
        core = re.sub(r"(?<=[0-9.,])[OoD](?=[0-9.,]|$)|^[OoD](?=[.,])", "0", t)
        core = re.sub(r"(?<=[0-9])[lI|](?=[0-9]|$)|^[lI|](?=[0-9.,])", "1", core)
        t = core
    out: list[Interp] = []
    pct = t.endswith("%")
    if pct:
        t = t[:-1]
    m = re.fullmatch(r"([-+]?)(\d+)", t)
    if m:
        out.append(Interp(float(t), "entero", 0.0))
        s, d = m.groups()
        if d.startswith("10") and len(d) in (3, 4) and not pct and s != "-":   # 10³ aplanado → «103»
            out.append(Interp(10.0 ** int(d[2:]), "potencia10", 1.0))
    m = re.fullmatch(r"([-+]?)(\d+),(\d+)", t)
    if m and not out:
        s, a, b = m.groups()
        out.append(Interp(float(f"{s}{a}.{b}"), "decimal_coma", 0.0))
        if len(b) == 3 and len(a) <= 3:
            out.append(Interp(float(f"{s}{a}{b}"), "miles", 0.8))
    m = re.fullmatch(r"([-+]?)(\d*)\.(\d+)", t)
    if m and not out:
        s, a, b = m.groups()
        out.append(Interp(float(f"{s}{a or '0'}.{b}"), "decimal", 0.0))
        if len(b) == 3 and 1 <= len(a) <= 3:
            out.append(Interp(float(f"{s}{a}{b}"), "miles", 0.8))
    m = re.fullmatch(r"([-+]?)10\^?([-+])(\d{1,3})", t)          # «10-3», «10^-3»
    if m and not out:
        s, e_s, e = m.groups()
        v = 10.0 ** (int(e) * (-1 if e_s == "-" else 1))
        out.append(Interp(-v if s == "-" else v, "potencia10", 0.3))
    m = re.fullmatch(r"([-+]?\d+(?:[.,]\d+)?)[eE]([-+]?\d{1,3})", t)
    if m and not out:
        out.append(Interp(float(m.group(1).replace(",", ".")) * 10.0 ** int(m.group(2)), "cientifica", 0.0))
    m = re.fullmatch(r"([-+]?\d+(?:[.,]\d+)?)[×x·*]10\^?([-+]?\d{1,3})", t)
    if m and not out:
        out.append(Interp(float(m.group(1).replace(",", ".")) * 10.0 ** int(m.group(2)), "cientifica", 0.2))
    if pct:
        out = [Interp(i.value, "porcentaje", i.penalty) for i in out]
    return [i for i in out if math.isfinite(i.value)]


_SUSPECT = re.compile(r"(?:^|[^a-zA-Z])[lI|1]?[eE][-+−]?\d|[×x*]\s*10|10\^")


def looks_like_multiplier(text: str) -> bool:
    """Texto con aspecto de exponente/multiplicador (aunque no se pueda interpretar)."""
    return bool(_SUSPECT.search((text or "").translate(_MINUS)))


def parse_multiplier(text: str) -> float | None:
    """Texto de desplazamiento/multiplicador de eje (``1e3``, ``×10³``, ``x10-3``, ``1e−3``)."""
    t = (text or "").strip().translate(_MINUS).translate(_SUP).replace(" ", "")
    t = re.sub(r"^[lI|](?=[eE.,])", "1", t)
    t = re.sub(r"(?<=[eE][-+])[OoD]|(?<=[eE])[OoD]", "0", t)
    m = re.fullmatch(r"(?:[×x*]?1)?[eE]([-+]?\d{1,3})", t)
    if m:
        return 10.0 ** int(m.group(1))
    m = re.fullmatch(r"[×x*]10\^?([-+]?\d{1,3})", t)
    if m:
        return 10.0 ** int(m.group(1))
    return None


# --------------------------------------------------------------------------- unidades
_UNIT_PATTERNS = [
    # (regex sobre el texto normalizado, magnitud, unidad canónica)
    (r"ma\s*/?\s*cm\s*(?:2|²|\^2|-2|⁻²)|ma\s*cm\s*-?2", "corriente", "mA/cm²"),
    (r"(?<![m])a\s*/?\s*cm\s*(?:2|²|\^2|-2|⁻²)|(?<![m])a\s*cm\s*-?2", "corriente", "A/cm²"),
    (r"(?<![m])a\s*/?\s*m\s*(?:2|²|\^2|-2)", "corriente", "A/m²"),
    (r"(?:^|[\s(\[/])ma(?:$|[\s)\]])", "corriente", "mA"),
    (r"(?:^|[\s(\[/])a(?:$|[\s)\]])|amp(?:ere|s)?\b", "corriente", "A"),
    (r"(?:^|[\s(\[/])mv(?:$|[\s)\]])|millivolt", "tensión", "mV"),
    (r"(?:^|[\s(\[/])v(?:$|[\s)\]])|volt", "tensión", "V"),
    (r"(?:^|[\s(\[/])kw(?:$|[\s)\]])", "potencia", "kW"),
    (r"(?:^|[\s(\[/])w(?:$|[\s)\]])|watt", "potencia", "W"),
    (r"%", "porcentaje", "%"),
]


def detect_unit(title: str) -> tuple[str | None, str | None, str]:
    """(magnitud, unidad, fragmento) a partir del título del eje; (None, None, '') si no se reconoce.

    Solo se buscan unidades entre paréntesis/corchetes o tras «/», o palabras de unidad explícitas.
    """
    if not title:
        return None, None, ""
    t = title.translate(_MINUS).replace("²", "2").replace("$", "").replace("{", "").replace("}", "")
    frags = re.findall(r"[\(\[]([^\)\]]{1,20})[\)\]]", t)
    cands = frags + ([t.split("/")[-1]] if "/" in t and not frags else []) + [t]
    for frag in cands:
        f = " " + frag.lower().strip() + " "
        for rx, q, u in _UNIT_PATTERNS:
            if re.search(rx, f):
                return q, u, frag.strip()
    return None, None, ""


# --------------------------------------------------------------------------- estructuras
@dataclass
class LabelEvidence:
    text: str
    ocr_conf: float
    bbox_px: list[float]
    position_px: float           # posición usada en el ajuste (tick ajustado o centro del texto)
    snapped_to_tick: bool
    candidates: list[dict]
    value: float | None = None
    kind: str | None = None
    inlier: bool = False
    residual_px: float | None = None
    user_value: float | None = None       # corrección manual individual
    excluded_by_user: bool = False

    @property
    def effective_value(self) -> float | None:
        return self.user_value if self.user_value is not None else self.value


@dataclass
class AxisRecognition:
    axis: str
    status: str
    reasons: list[str]
    scale: str | None = None                 # "lineal" | "logarítmica"
    labels: list[LabelEvidence] = field(default_factory=list)
    slope: float | None = None               # d(t)/d(px), t = valor o log10(valor)
    intercept: float | None = None
    rms_px: float | None = None
    max_residual_px: float | None = None
    n_inliers: int = 0
    multiplier: float | None = None
    multiplier_text: str | None = None
    title: dict | None = None                # {"text","ocr_conf","bbox_px","quantity","unit","fragment"}
    anchors: list[tuple[float, float]] = field(default_factory=list)   # [(posición, valor)] × 2
    ambiguous_alternatives: int = 0
    unparsed_multipliers: list[str] = field(default_factory=list)
    engine: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status_text"] = STATUS_TEXT.get(self.status, self.status)
        return d


# --------------------------------------------------------------------------- ajuste
def _t(v: float, log: bool) -> float | None:
    if log:
        return math.log10(v) if v > 0 else None
    return v


def fit_axis(pos: list[float], interps: list[list[Interp]], spacing: float | None) -> dict | None:
    """Consenso robusto: mejor (escala, interpretación por etiqueta) con posiciones coherentes."""
    n = len(pos)
    if n < 2:
        return None
    sp = spacing or (np.median(np.diff(sorted(pos))) if n > 1 else 50.0)
    tol = max(2.0, 0.04 * float(sp))
    best = None
    alts = []
    for log in (False, True):
        for i in range(n):
            for j in range(i + 1, n):
                if abs(pos[j] - pos[i]) < 3:
                    continue
                for a, b in product(interps[i], interps[j]):
                    ta, tb = _t(a.value, log), _t(b.value, log)
                    if ta is None or tb is None or ta == tb:
                        continue
                    slope = (tb - ta) / (pos[j] - pos[i])
                    icpt = ta - slope * pos[i]
                    chosen, res, pen = [], [], a.penalty + b.penalty
                    for k in range(n):
                        bestk = None
                        for c in interps[k]:
                            tc = _t(c.value, log)
                            if tc is None:
                                continue
                            r = abs((tc - icpt) / slope - pos[k])
                            if bestk is None or (r, c.penalty) < (bestk[0], bestk[1].penalty):
                                bestk = (r, c)
                        if bestk and bestk[0] <= tol:
                            chosen.append((k, bestk[1]))
                            res.append(bestk[0])
                    if len(chosen) < 2:
                        continue
                    pen = sum(c.penalty for _, c in chosen)
                    key = (len(chosen), -round(pen, 3), -float(np.sqrt(np.mean(np.square(res)))))
                    cand = {"log": log, "chosen": chosen, "key": key}
                    if best is None or key > best["key"]:
                        best = cand
                    alts.append(cand)
    if best is None:
        return None
    # refinamiento por mínimos cuadrados sobre las etiquetas coherentes
    ks = [k for k, _ in best["chosen"]]
    ts = np.array([_t(c.value, best["log"]) for _, c in best["chosen"]])
    ps = np.array([pos[k] for k in ks])
    if len(ks) >= 2 and np.ptp(ps) > 0:
        slope, icpt = np.polyfit(ps, ts, 1)
    res = np.abs((ts - icpt) / slope - ps)
    # alternativas genuinamente distintas con el mismo número de etiquetas coherentes
    distinct = set()
    for c in alts:
        if c["key"][0] == best["key"][0] and abs(c["key"][1] - best["key"][1]) < 1e-9:
            sig = (c["log"], tuple((k, round(i.value, 12)) for k, i in c["chosen"]))
            distinct.add(sig)
    return {"log": best["log"], "chosen": best["chosen"], "slope": float(slope), "intercept": float(icpt),
            "residuals": res.tolist(), "tol": tol, "n_alternatives": max(0, len(distinct) - 1)}


# --------------------------------------------------------------------------- bandas
def _bands(panel: Panel, shape) -> dict[str, tuple[int, int, int, int]]:
    H, W = shape[:2]
    x0, y0, x1, y1 = panel.box
    w, h = x1 - x0, y1 - y0
    xa = panel.x_axis
    ya = panel.y_axis
    xb = (int(max(0, x0 - 0.12 * w)), int(min(H - 1, xa.pos + xa.thickness / 2 + 1)),
          int(min(W, x1 + 0.12 * w)), int(min(H, xa.pos + max(70, 0.22 * h))))
    yb = (int(max(0, x0 - max(110, 0.30 * w))), int(max(0, y0 - max(28, 0.07 * h))),
          int(max(1, ya.pos - ya.thickness / 2 - 1)), int(min(H, y1 + 0.06 * h)))
    return {"X": xb, "Y": yb}


def _offset_band(panel: Panel, shape) -> tuple[int, int, int, int]:
    """Zona sobre el extremo superior del eje Y donde suele ir el multiplicador del eje Y."""
    H, W = shape[:2]
    x0, y0, x1, y1 = panel.box
    return (int(max(0, x0 - 60)), int(max(0, y0 - 34)), int(min(W, x0 + 0.25 * (x1 - x0))), int(max(1, y0 - 1)))


def _join(boxes: list[TextBox], order: str) -> TextBox:
    """Une palabras de un mismo título (fila o columna) en una caja con el texto en orden de lectura."""
    if order == "x":
        bs = sorted(boxes, key=lambda b: b.x0)
    else:   # texto girado 90° en sentido antihorario: se lee de abajo arriba
        bs = sorted(boxes, key=lambda b: -b.y1)
    t = TextBox(min(b.x0 for b in bs), min(b.y0 for b in bs), max(b.x1 for b in bs), max(b.y1 for b in bs),
                rotated=order != "x", text=" ".join(b.text for b in bs if b.text),
                conf=float(np.mean([b.conf for b in bs])))
    return t


def _classify(axis: str, boxes: list[TextBox], panel: Panel, band) -> tuple[list[TextBox], list[TextBox], list[TextBox]]:
    """(etiquetas de tick, título del eje, multiplicadores)."""
    if not boxes:
        return [], [], []
    x0, y0, x1, y1 = panel.box
    bx0, by0, bx1, by1 = band
    keep = []
    for b in boxes:
        if axis == "X" and (b.y0 <= by0 + 0.5 or b.cy <= panel.x_axis.pos + 2):
            continue          # toca el eje: tick o etiqueta Y recortada en la esquina
        if axis == "Y" and (b.x1 >= bx1 - 0.5 or b.cx >= panel.y_axis.pos - 2 or b.cy > y1 + 0.5 * max(b.h, 6)):
            continue          # toca el eje o es una etiqueta X de la esquina
        keep.append(b)
    mult = [b for b in keep if parse_multiplier(b.text) is not None]
    numeric = [b for b in keep if parse_label(b.text) and not b.rotated and b not in mult]
    if numeric:
        hmed = float(np.median([b.h for b in numeric]))
        numeric = [b for b in numeric if b.h >= 0.55 * hmed]
    rest = [b for b in keep if b not in numeric and b not in mult]
    ticks: list[TextBox] = []
    if axis == "X":
        if numeric:
            top = min(b.y0 for b in numeric)
            hmed = float(np.median([b.h for b in numeric]))
            ticks = [b for b in numeric if b.y0 <= top + 0.8 * hmed and x0 - 0.1 * (x1 - x0) <= b.cx <= x1 + 0.1 * (x1 - x0)]
            rest += [b for b in numeric if b not in ticks]
        cand = [b for b in rest if not b.rotated and (not ticks or b.y0 > max(t.y1 for t in ticks) - 1)]
        titles = [_join(cand, "x")] if cand else []
    else:
        if numeric:
            right = max(b.x1 for b in numeric)
            wmed = float(np.median([b.w for b in numeric]))
            ticks = [b for b in numeric if b.x1 >= right - max(0.6 * wmed, 6) and y0 - 0.05 * (y1 - y0) <= b.cy <= y1 + 0.05 * (y1 - y0)]
            rest += [b for b in numeric if b not in ticks]
        left = min((t.x0 for t in ticks), default=bx1)
        cand = [b for b in rest if b.x1 < left - 1 and y0 - 0.1 * (y1 - y0) <= b.cy <= y1 + 0.1 * (y1 - y0)]
        if cand:                                        # columna del título girado (todas sus palabras)
            main = max(cand, key=lambda b: b.h)
            col = [b for b in cand if min(main.x1, b.x1) - max(main.x0, b.x0) > 0.3 * min(main.w, b.w)]
            titles = [_join(col, "y")]
        else:
            titles = []
        titles += [b for b in rest if not b.rotated and b.w > 1.5 * b.h and len(b.text) >= 2
                   and (not ticks or b.y1 < min(t.y0 for t in ticks))]   # título horizontal encima del eje
    return ticks, titles, mult


OCR_MAX_SIDE_PX = 2200      # por encima, el OCR trabaja sobre una copia reducida (texto a escala de lectura)


def recognize_axes(rgb: np.ndarray, panel: Panel, ticks: dict[str, TickSet | None],
                   background_rgb=(255, 255, 255)) -> dict[str, AxisRecognition]:
    """Reconoce valores, escala, multiplicador y unidad de los ejes X e Y del panel.

    En imágenes grandes (fotos o capturas de tablet de 3000–4000 px) el texto de los ejes es mucho mayor que
    aquello para lo que están calibradas las bandas y umbrales: se reconoce sobre una copia reducida y después
    las posiciones se reajustan a los ticks detectados a resolución COMPLETA (sin pérdida de precisión sub-píxel).
    """
    H, W = rgb.shape[:2]
    if max(H, W) <= OCR_MAX_SIDE_PX:
        return _recognize_axes_core(rgb, panel, ticks, background_rgb)
    import cv2
    s = OCR_MAX_SIDE_PX / max(H, W)
    small = cv2.resize(rgb, (max(1, round(W * s)), max(1, round(H * s))), interpolation=cv2.INTER_AREA)
    sc = lambda seg: LineSeg(seg.orientation, seg.pos * s, seg.start * s, seg.end * s, max(1.0, seg.thickness * s),  # noqa: E731
                             seg.strength)
    p2 = Panel(panel.x0 * s, panel.y0 * s, panel.x1 * s, panel.y1 * s, sc(panel.x_axis), sc(panel.y_axis),
               panel.has_top, panel.has_right)
    t2 = {k: (None if t is None else TickSet(t.axis, [v * s for v in t.positions], t.kind, t.regular,
                                             None if t.spacing is None else t.spacing * s)) for k, t in ticks.items()}
    out = _recognize_axes_core(small, p2, t2, background_rgb)
    for axis, rec in out.items():
        full = sorted(ticks[axis].positions) if ticks.get(axis) and ticks[axis].kind != "marco" else []
        spacing = float(np.median(np.diff(full))) if len(full) > 1 else None
        for l in rec.labels:
            l.bbox_px = [v / s for v in l.bbox_px]
            pos = l.position_px / s
            if full:
                near = min(full, key=lambda q: abs(q - pos))
                if abs(near - pos) <= max(6.0, 0.3 * (spacing or 0)):
                    pos, l.snapped_to_tick = near, True
            l.position_px = float(pos)
        if rec.title:
            rec.title = {**rec.title, "bbox_px": [round(v / s, 1) for v in rec.title["bbox_px"]]}
        if rec.slope is not None or rec.labels:
            new = recompute(rec, spacing)
            new.reasons = new.reasons + [f"OCR sobre copia reducida ×{s:.2f}; posiciones a resolución completa."]
            out[axis] = new
    return out


def _recognize_axes_core(rgb: np.ndarray, panel: Panel, ticks: dict[str, TickSet | None],
                         background_rgb=(255, 255, 255)) -> dict[str, AxisRecognition]:
    from .ocr import ENGINE_ID
    bg_luma = float(np.dot(background_rgb, [0.299, 0.587, 0.114]))
    out: dict[str, AxisRecognition] = {}
    for axis, band in _bands(panel, rgb.shape).items():
        try:
            boxes = recognize_boxes(rgb, find_text_boxes(rgb, band, bg_luma))
        except OCRUnavailable as exc:
            out[axis] = AxisRecognition(axis, ST_INSUFFICIENT, [f"OCR no disponible: {exc}"], engine="—")
            continue
        tk, titles, mults = _classify(axis, boxes, panel, band)
        suspects = [b for b in boxes if b not in tk and b not in mults and looks_like_multiplier(b.text)]
        if axis == "Y":
            ob = _offset_band(panel, rgb.shape)
            if ob[3] - ob[1] > 4:
                extra = recognize_boxes(rgb, find_text_boxes(rgb, ob, bg_luma))
                mults += [b for b in extra if parse_multiplier(b.text) is not None]
                suspects += [b for b in extra if parse_multiplier(b.text) is None and looks_like_multiplier(b.text)]
        tickpos = sorted(ticks[axis].positions) if ticks.get(axis) and ticks[axis].kind != "marco" else []
        spacing = float(np.median(np.diff(tickpos))) if len(tickpos) > 1 else None
        labels: list[LabelEvidence] = []
        for b in sorted(tk, key=lambda b: b.cx if axis == "X" else b.cy):
            c = b.cx if axis == "X" else b.cy
            snapped = False
            if tickpos:
                near = min(tickpos, key=lambda p: abs(p - c))
                if abs(near - c) <= max(6.0, 0.3 * (spacing or 0)):
                    c, snapped = near, True
            labels.append(LabelEvidence(b.text, b.conf, [b.x0, b.y0, b.x1, b.y1], float(c), snapped,
                                        [asdict(i) for i in parse_label(b.text)]))
        rec = evaluate_axis(axis, labels, spacing)
        rec.engine = ENGINE_ID
        if mults:
            m = min(mults, key=lambda b: b.cy if axis == "Y" else -b.cx)
            rec.multiplier, rec.multiplier_text = parse_multiplier(m.text), m.text
        if titles:
            titles = recognize_boxes(rgb, [TextBox(t.x0, t.y0, t.x1, t.y1, rotated=t.rotated) for t in titles])
            t = max(titles, key=lambda b: (detect_unit(b.text)[1] is not None, len(b.text), b.conf))
            q, u, frag = detect_unit(t.text)
            rec.title = {**t.to_dict(), "quantity": q, "unit": u, "fragment": frag}
        rec.unparsed_multipliers = [b.text for b in suspects]
        _finalize_status(rec)
        out[axis] = rec
    return out


def evaluate_axis(axis: str, labels: list[LabelEvidence], spacing: float | None) -> AxisRecognition:
    """Ajuste geométrico sobre etiquetas (también tras correcciones del usuario)."""
    usable = [l for l in labels if not l.excluded_by_user]
    interps = []
    for l in usable:
        if l.user_value is not None:
            interps.append([Interp(float(l.user_value), "usuario", 0.0)])
        else:
            interps.append([Interp(**c) for c in l.candidates])
    for l in labels:
        l.inlier, l.residual_px, l.value, l.kind = False, None, None, None
    idx = [k for k, it in enumerate(interps) if it]
    fit = fit_axis([usable[k].position_px for k in idx], [interps[k] for k in idx], spacing)
    rec = AxisRecognition(axis, ST_INSUFFICIENT, [], labels=labels)
    if fit is None:
        rec.reasons.append(f"Menos de 2 etiquetas numéricas coherentes ({len(idx)} legibles).")
        return rec
    rec.scale = "logarítmica" if fit["log"] else "lineal"
    rec.slope, rec.intercept = fit["slope"], fit["intercept"]
    rec.ambiguous_alternatives = fit["n_alternatives"]
    chosen = {idx[k]: c for k, c in fit["chosen"]}
    for n, k in enumerate(sorted(chosen)):
        l = usable[k]
        l.inlier, l.value, l.kind = True, chosen[k].value, chosen[k].kind
        l.residual_px = fit["residuals"][n]
    for k, l in enumerate(usable):        # residuo de las atípicas con su mejor interpretación
        if not l.inlier and interps[k]:
            rs = []
            for c in interps[k]:
                t = _t(c.value, fit["log"])
                if t is not None:
                    rs.append((abs((t - fit["intercept"]) / fit["slope"] - l.position_px), c))
            if rs:
                r, c = min(rs, key=lambda x: x[0])
                l.residual_px, l.value, l.kind = r, c.value, c.kind
    inl = [l for l in usable if l.inlier]
    rec.n_inliers = len(inl)
    rec.rms_px = float(np.sqrt(np.mean([l.residual_px ** 2 for l in inl])))
    rec.max_residual_px = float(max(l.residual_px for l in inl))
    a, b = min(inl, key=lambda l: l.position_px), max(inl, key=lambda l: l.position_px)
    rec.anchors = [(a.position_px, float(a.effective_value if a.user_value is not None else a.value)),
                   (b.position_px, float(b.effective_value if b.user_value is not None else b.value))]
    return rec


def _finalize_status(rec: AxisRecognition) -> None:
    """Estado a partir de evidencias observables (no una cifra arbitraria)."""
    if rec.status == ST_INSUFFICIENT and rec.slope is None:
        rec.status = ST_INSUFFICIENT
        return
    reasons, review = [], False
    numeric = [l for l in rec.labels if l.candidates or l.user_value is not None]
    usable = [l for l in numeric if not l.excluded_by_user]
    outliers = [l for l in usable if not l.inlier]
    inl = [l for l in usable if l.inlier]
    if rec.n_inliers < 2:
        rec.status = ST_INSUFFICIENT
        rec.reasons.append("Menos de 2 etiquetas coherentes.")
        return
    if rec.n_inliers < 3:
        review = True
        reasons.append(f"Solo {rec.n_inliers} etiquetas coherentes (se exigen ≥ 3 para confiar).")
    if outliers:
        review = True
        reasons.append("Etiquetas incoherentes con la geometría: " + ", ".join(f"«{l.text}»" for l in outliers) + ".")
    if rec.max_residual_px is not None and rec.max_residual_px > 1.5:
        review = True
        reasons.append(f"Residuo geométrico máximo {rec.max_residual_px:.2f} px (> 1,5 px).")
    low = [l for l in inl if l.user_value is None and l.ocr_conf < 0.85
           and not (l.ocr_conf >= 0.6 and (l.residual_px or 0) <= 1.0 and rec.n_inliers >= 4)]
    corroborated = [l for l in inl if l.user_value is None and 0.6 <= l.ocr_conf < 0.85 and l not in low]
    if corroborated:
        reasons.append("Corroboradas por la geometría (OCR 0,6–0,85, residuo ≤ 1 px): "
                       + ", ".join(f"«{l.text}»" for l in corroborated) + ".")
    if low:
        review = True
        reasons.append("Confianza OCR baja en: " + ", ".join(f"«{l.text}» ({l.ocr_conf:.2f})" for l in low) + ".")
    amb = [l for l in inl if l.user_value is None and len(l.candidates) > 1 and l.kind in ("miles", "potencia10")
           and not (l.kind == "potencia10" and rec.scale == "logarítmica")]
    if amb:
        review = True
        reasons.append("Interpretación ambigua resuelta solo por la geometría: "
                       + ", ".join(f"«{l.text}»→{l.value:g}" for l in amb) + ".")
    if rec.ambiguous_alternatives:
        review = True
        reasons.append(f"{rec.ambiguous_alternatives} interpretación(es) alternativa(s) igual de coherentes.")
    if rec.multiplier is not None:
        review = True
        reasons.append(f"Multiplicador de eje «{rec.multiplier_text}» (×{rec.multiplier:g}) detectado: confirme que "
                       "aplica a todas las etiquetas.")
    if rec.unparsed_multipliers:
        review = True
        reasons.append("Texto con aspecto de multiplicador/exponente no interpretable cerca del eje: "
                       + ", ".join(f"«{t}»" for t in rec.unparsed_multipliers) + ". Compruebe la escala.")
    if rec.slope is not None:
        increasing = rec.slope > 0 if rec.axis == "X" else rec.slope < 0
        if not increasing:
            review = True
            reasons.append("Eje invertido (los valores decrecen en el sentido habitual).")
    if all(l.user_value is not None for l in inl):
        reasons.append("Valores corregidos por el usuario.")
    rec.status = ST_REVIEW if review else ST_RELIABLE
    if not review:
        reasons.insert(0, f"{rec.n_inliers} etiquetas coherentes, residuo RMS {rec.rms_px:.2f} px.")
    rec.reasons = reasons


def recompute(rec: AxisRecognition, spacing: float | None = None) -> AxisRecognition:
    """Reevalúa tras correcciones individuales del usuario (conserva título y multiplicador)."""
    new = evaluate_axis(rec.axis, rec.labels, spacing)
    new.title, new.multiplier, new.multiplier_text, new.engine = rec.title, rec.multiplier, rec.multiplier_text, rec.engine
    new.unparsed_multipliers = list(rec.unparsed_multipliers)
    _finalize_status(new)
    return new
