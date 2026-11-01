"""OCR local de etiquetas de ejes: reconocedor CRNN/SVTR (PP-OCRv4) en ONNX + agrupación propia.

- Solo se usa el modelo de RECONOCIMIENTO; las cajas de texto se localizan con componentes conexos
  (las etiquetas de ejes son texto impreso, aislado y horizontal; el título del eje Y suele estar girado 90°).
- Dependencia única: ``onnxruntime`` (CPU). Sin servicios externos, sin descarga en tiempo de ejecución,
  sin ``opencv-python`` con GUI. Modelo y licencia en ``digitizer/models/`` (SHA-256 verificado al cargar).
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = Path(__file__).resolve().parent / "models" / "ch_PP-OCRv4_rec_infer.onnx"
MODEL_SHA256 = "48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b"
REC_HEIGHT = 48
ENGINE_ID = "PP-OCRv4-rec (ONNX) + agrupación por componentes conexos"


class OCRUnavailable(RuntimeError):
    """El motor OCR no está disponible: el digitalizador sigue funcionando en modo manual."""


@dataclass
class TextBox:
    x0: float
    y0: float
    x1: float
    y1: float
    rotated: bool = False           # texto girado 90° (p. ej. título del eje Y)
    text: str = ""
    conf: float = 0.0
    char_conf: list[float] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def w(self) -> float:
        return self.x1 - self.x0

    @property
    def h(self) -> float:
        return self.y1 - self.y0

    def to_dict(self) -> dict:
        return {"bbox_px": [round(self.x0, 1), round(self.y0, 1), round(self.x1, 1), round(self.y1, 1)],
                "text": self.text, "ocr_conf": round(float(self.conf), 4), "rotated": self.rotated}


class TextRecognizer:
    """Reconocedor de líneas de texto (sin detección). Seguro para uso concurrente (lock)."""

    def __init__(self, model_path: Path = MODEL_PATH):
        try:
            import onnxruntime as ort
        except Exception as exc:  # noqa: BLE001
            raise OCRUnavailable(f"onnxruntime no disponible: {exc}") from exc
        if not model_path.exists():
            raise OCRUnavailable(f"Modelo OCR ausente: {model_path}")
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise OCRUnavailable("El modelo OCR no coincide con el SHA-256 esperado (archivo alterado).")
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.session = ort.InferenceSession(str(model_path), sess_options=so, providers=["CPUExecutionProvider"])
        chars = self.session.get_modelmeta().custom_metadata_map["character"].splitlines()
        self.chars = ["<blank>"] + chars + [" "]
        self.input_name = self.session.get_inputs()[0].name
        self._lock = threading.Lock()

    def recognize(self, crops: list[np.ndarray]) -> list[tuple[str, float, list[float]]]:
        """Reconoce una lista de recortes RGB uint8. Devuelve (texto, confianza media, conf. por carácter)."""
        if not crops:
            return []
        ratios = [max(c.shape[1] / max(c.shape[0], 1), 1.0) for c in crops]
        width = int(REC_HEIGHT * max(max(ratios), 320 / REC_HEIGHT))
        batch = np.zeros((len(crops), 3, REC_HEIGHT, width), np.float32)
        for i, c in enumerate(crops):
            bgr = c[..., ::-1]
            rw = min(width, int(np.ceil(REC_HEIGHT * c.shape[1] / max(c.shape[0], 1))))
            im = cv2.resize(bgr, (max(rw, 1), REC_HEIGHT), interpolation=cv2.INTER_CUBIC).astype(np.float32)
            im = (im.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
            batch[i, :, :, :rw] = im
        with self._lock:
            preds = self.session.run(None, {self.input_name: batch})[0]
        out = []
        idx = preds.argmax(axis=2)
        prob = preds.max(axis=2)
        for k in range(len(crops)):
            text, confs, prev = [], [], -1
            for t, p in zip(idx[k], prob[k]):
                if t != 0 and t != prev:
                    text.append(self.chars[t] if t < len(self.chars) else "")
                    confs.append(float(p))
                prev = t
            out.append(("".join(text), float(np.mean(confs)) if confs else 0.0, confs))
        return out


_REC: TextRecognizer | None = None
_REC_LOCK = threading.Lock()


def get_recognizer() -> TextRecognizer:
    """Instancia única por proceso (el modelo pesa ~11 MB; ~100 MB de RAM en ejecución)."""
    global _REC
    with _REC_LOCK:
        if _REC is None:
            _REC = TextRecognizer()
        return _REC


_WARM = {"started": False}


def warmup_async() -> None:
    """Carga el modelo en segundo plano al arrancar el proceso (una vez): la primera imagen no espera por él."""
    with _REC_LOCK:
        if _WARM["started"] or _REC is not None:
            return
        _WARM["started"] = True

    def _run():
        try:
            get_recognizer()
        except OCRUnavailable:
            pass
    threading.Thread(target=_run, name="pml-ocr-warmup", daemon=True).start()


def ocr_available() -> tuple[bool, str]:
    try:
        get_recognizer()
        return True, ENGINE_ID
    except OCRUnavailable as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Localización de cajas de texto en una banda
# ---------------------------------------------------------------------------
def find_text_boxes(rgb: np.ndarray, band: tuple[int, int, int, int], bg_luma: float,
                    ink_threshold: float = 70.0) -> list[TextBox]:
    """Agrupa componentes conexos de tinta de una banda en palabras/etiquetas.

    Se fusionan componentes con solape vertical (o casi) y separación horizontal menor que ~0,6
    veces la altura típica de carácter, lo que mantiene unidos «10» y su exponente pero separa
    etiquetas contiguas. Grupos altos y estrechos se marcan como texto girado.
    """
    x0, y0, x1, y1 = band
    sub = rgb[y0:y1, x0:x1].astype(np.float32)
    if sub.size == 0:
        return []
    luma = sub[..., 0] * 0.299 + sub[..., 1] * 0.587 + sub[..., 2] * 0.114
    ink = ((bg_luma - luma) > ink_threshold).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    comps = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < 2:
            continue
        bw, bh = x1 - x0, y1 - y0
        touches = x == 0 or y == 0 or x + w >= bw or y + h >= bh
        if touches and min(w, h) <= 2 and max(w, h) <= 12:
            continue      # marcas de tick o restos del eje en el borde de la banda
        if w > 0.6 * (x1 - x0) or h > 0.6 * (y1 - y0) and h > 60:
            continue      # líneas largas (marco, gridlines) que invaden la banda
        comps.append([x, y, x + w, y + h])
    if not comps:
        return []
    hs = np.array([c[3] - c[1] for c in comps], float)
    hchar = float(np.median(hs[hs >= 4])) if (hs >= 4).any() else float(np.median(hs))
    ws = np.array([c[2] - c[0] for c in comps], float)
    wchar = float(np.median(ws[ws >= 3])) if (ws >= 3).any() else float(np.median(ws))

    def merge(boxes, horizontal: bool):
        boxes = sorted(boxes, key=lambda b: (b[0], b[1]) if horizontal else (b[1], b[0]))
        changed = True
        while changed:
            changed = False
            out = []
            for b in boxes:
                for o in out:
                    if horizontal:
                        vover = min(o[3], b[3]) - max(o[1], b[1])
                        gap = max(b[0] - o[2], o[0] - b[2])
                        if vover > -0.35 * hchar and gap <= 0.6 * hchar:
                            o[:] = [min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])]
                            changed = True
                            break
                    else:
                        hover = min(o[2], b[2]) - max(o[0], b[0])
                        gap = max(b[1] - o[3], o[1] - b[3])
                        if hover > -0.35 * wchar and gap <= 0.6 * wchar:
                            o[:] = [min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3])]
                            changed = True
                            break
                else:
                    out.append(list(b))
            boxes = out
        return boxes

    groups = merge([list(c) for c in comps], horizontal=True)
    boxes: list[TextBox] = []
    for g in groups:
        gw, gh = g[2] - g[0], g[3] - g[1]
        boxes.append(TextBox(g[0] + x0, g[1] + y0, g[2] + x0, g[3] + y0, rotated=bool(gh > 2.2 * gw and gh > 2.5 * hchar)))
    # texto girado: reagrupar en vertical los componentes de columnas altas (títulos del eje Y)
    rot = [b for b in boxes if b.rotated]
    if rot:
        for b in rot:
            boxes.remove(b)
        rcomps = [[c[0] + x0, c[1] + y0, c[2] + x0, c[3] + y0] for c in comps
                  if any(r.x0 - 1 <= c[0] + x0 and c[2] + x0 <= r.x1 + 1 and r.y0 - 1 <= c[1] + y0 and c[3] + y0 <= r.y1 + 1
                         for r in rot)]
        for g in merge(rcomps, horizontal=False):
            boxes.append(TextBox(*g, rotated=True))
    return boxes


def recognize_boxes(rgb: np.ndarray, boxes: list[TextBox], pad: int = 3, upscale_min_h: int = 24) -> list[TextBox]:
    """Rellena texto y confianza de cada caja. El texto girado se prueba en ambos sentidos."""
    if not boxes:
        return boxes
    rec = get_recognizer()
    H, W = rgb.shape[:2]
    crops, owners = [], []
    for i, b in enumerate(boxes):
        xa, ya = max(0, int(b.x0) - pad), max(0, int(b.y0) - pad)
        xb, yb = min(W, int(np.ceil(b.x1)) + pad), min(H, int(np.ceil(b.y1)) + pad)
        c = rgb[ya:yb, xa:xb]
        if c.size == 0:
            continue
        variants = [np.rot90(c, k=-1), np.rot90(c, k=1)] if b.rotated else [c]
        for v in variants:
            v = np.ascontiguousarray(v)
            if v.shape[0] < upscale_min_h:
                f = upscale_min_h / v.shape[0]
                v = cv2.resize(v, (max(1, int(v.shape[1] * f)), upscale_min_h), interpolation=cv2.INTER_CUBIC)
            crops.append(v)
            owners.append(i)
    results = rec.recognize(crops)
    best: dict[int, tuple[str, float, list[float]]] = {}
    for i, r in zip(owners, results):
        if i not in best or r[1] > best[i][1]:
            best[i] = r
    for i, (t, c, cc) in best.items():
        boxes[i].text, boxes[i].conf, boxes[i].char_conf = t.strip(), c, cc
    return boxes
