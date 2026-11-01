"""Borrador de digitalización: estado editable, deshacer/rehacer y auditoría.

Fuente de verdad geométrica: los puntos en PÍXELES. Los valores físicos se
DERIVAN en cada consulta a partir de las anclas (nunca se almacenan dos veces).
Las ediciones hechas en unidades físicas (tabla) se convierten a píxeles con la
calibración vigente y se registran como tales.

El borrador no es una PolarizationCurve: solo se convierte en una al confirmar
(ver ``digitizer.confirm``), con unidades, anclas y condiciones completas.
"""
from __future__ import annotations

import copy
import io
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import ALGORITHM_ID, DIGITIZER_VERSION
from .calibration import ANCHOR_NAMES, SCALE_LINEAR, Anchor, Calibration, build_axis
from .detection import DetectionParams, DetectionResult, TraceCandidate, detect
from .imageio import LoadedImage

METHOD_AUTO = "automático"
METHOD_MANUAL = "manual"
MAX_HISTORY = 200

# Estados (ESPECIFICACION_FUNCIONAL.md)
ST_NO_IMAGE = "SIN_IMAGEN"
ST_AUTO = "AUTO_DETECTADA"
ST_NEEDS_CAL = "REQUIERE_CALIBRACION"
ST_REVIEW = "REVISION"
ST_READY = "LISTO_PARA_CONFIRMAR"
ST_ERROR = "ERROR_RECUPERABLE"
ST_CONFIRMED = "CONFIRMADO"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class DraftPoint:
    id: int
    px: float
    py: float
    include: bool = True
    method: str = METHOD_AUTO
    edits: int = 0
    edited_at: str | None = None
    origin: str = ""                  # candidato de origen o «manual»

    @property
    def modified(self) -> bool:
        return self.method == METHOD_MANUAL or self.edits > 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DigitizationDraft:
    image: LoadedImage
    params: DetectionParams = field(default_factory=DetectionParams)
    detection: DetectionResult | None = None
    selected_candidate: str | None = None
    extraction_method: str = "automático"
    roi: tuple[float, float, float, float] | None = None
    plot_box: tuple[float, float, float, float] | None = None
    anchors: dict[str, Anchor] = field(default_factory=dict)
    scales: dict[str, str] = field(default_factory=lambda: {"X": SCALE_LINEAR, "Y": SCALE_LINEAR})
    current_unit: str = "A/cm²"
    voltage_unit: str = "V"
    voltage_basis: str = "celda"
    points: list[DraftPoint] = field(default_factory=list)
    next_id: int = 1
    audit: list[dict] = field(default_factory=list)
    undo_stack: list[dict] = field(default_factory=list, repr=False)
    redo_stack: list[dict] = field(default_factory=list, repr=False)
    rev: int = 0
    deleted_points: list[dict] = field(default_factory=list)
    confirmed_curve_ids: list[str] = field(default_factory=list)
    created_utc: str = field(default_factory=_now)
    last_error: str | None = None
    # v0.3.0 — reconocimiento automático de ejes (OCR + geometría), confirmaciones y curvas guardadas
    ocr_enabled: bool = True
    axis_recognition: dict = field(default_factory=dict)        # "X"/"Y" → AxisRecognition
    axis_confirmed: dict = field(default_factory=lambda: {"X": False, "Y": False})
    units_confirmed: bool = False
    units_source: str = ""
    x_unit_text: str = ""                                       # unidad libre (exportación autónoma)
    y_unit_text: str = ""
    saved_curves: list = field(default_factory=list)            # curvas guardadas de este panel
    panel_index: int | None = None

    # ------------------------------------------------------------------ creación
    @classmethod
    def from_image(cls, image: LoadedImage, params: DetectionParams | None = None,
                   ocr: bool = True, progress=None) -> "DigitizationDraft":
        """``progress``: función opcional que recibe mensajes de fase (indicador visible en la interfaz)."""
        import time as _t
        d = cls(image=image, params=params or DetectionParams(), ocr_enabled=ocr)
        d._progress = progress
        d.anchors = {n: Anchor(n) for n in ANCHOR_NAMES}
        d._log("imagen_cargada", image.describe())
        t0 = _t.perf_counter()
        d.run_detection(initial=True)
        d.timings = {"total_s": round(_t.perf_counter() - t0, 3), **getattr(d, "timings", {})}
        d._log("procesamiento_inicial", dict(d.timings))
        d._progress = None
        return d

    def run_detection(self, params: DetectionParams | None = None, initial: bool = False) -> None:
        """(Re)ejecuta la extracción automática. Reemplaza el trazo; respeta anclas editadas."""
        if params is not None:
            self.params = params
        if not initial:
            self._push_undo()
        import time as _t
        prog = getattr(self, "_progress", None)
        if prog:
            prog("Detectando paneles, ejes y trazos…")
        t0 = _t.perf_counter()
        try:
            res = detect(self.image.rgb, self.params)
        except Exception as exc:  # recuperable: se conserva la imagen y el borrador
            self.last_error = f"La detección automática falló: {exc}"
            self._log("deteccion_fallida", {"error": str(exc)})
            self.detection = None
            return
        self.last_error = None
        self.detection = res
        self.plot_box = res.plot_box
        self.roi = res.roi
        for name in ANCHOR_NAMES:
            a = self.anchors.get(name) or Anchor(name)
            if a.edited:
                continue                     # nunca se pisan anclas del usuario
            t = res.ticks.get(name[0])
            if t is None or not t.positions:
                self.anchors[name] = Anchor(name)
                continue
            # X1 = primer tick (izquierda), X2 = último; Y1 = tick inferior, Y2 = superior.
            if name == "X1":
                pos = t.positions[0]
            elif name == "X2":
                pos = t.positions[-1]
            elif name == "Y1":
                pos = max(t.positions)
            else:
                pos = min(t.positions)
            src = {"tick": "auto-tick", "gridline": "auto-grid", "marco": "auto-marco"}[t.kind]
            other = res.plot_box
            if name[0] == "X":
                py = other[3] if other else None
                self.anchors[name] = Anchor(name, px=float(pos), py=py, value=a.value, source=src)
            else:
                px = other[0] if other else None
                self.anchors[name] = Anchor(name, px=px, py=float(pos), value=a.value, source=src)
        best = res.best_candidate
        self.selected_candidate = best.id if best else None
        self.points = []
        if best is not None:
            self._points_from_candidate(best)
        self.extraction_method = "automático"
        self._log("deteccion_automatica", {"summary": res.summary(), "selected": self.selected_candidate})
        self.panel_index = res.panel_index
        self.timings = {"deteccion_s": round(_t.perf_counter() - t0, 3)}
        if self.ocr_enabled and res.panel_index is not None and res.panels:
            if prog:
                prog("Reconociendo los números de los ejes (OCR local)…")
            t1 = _t.perf_counter()
            self._recognize_axes()
            self.timings["ocr_s"] = round(_t.perf_counter() - t1, 3)
        self._bump()

    def _points_from_candidate(self, cand: TraceCandidate) -> None:
        self.points = []
        for x, y in cand.points:
            self.points.append(DraftPoint(self.next_id, float(x), float(y), origin=cand.id))
            self.next_id += 1

    # ------------------------------------------------------------------ historial
    def _state(self) -> dict:
        return {"points": [p.to_dict() for p in self.points], "anchors": {k: a.to_dict() for k, a in self.anchors.items()},
                "roi": self.roi, "selected_candidate": self.selected_candidate, "scales": dict(self.scales),
                "next_id": self.next_id, "extraction_method": self.extraction_method,
                "deleted_points": copy.deepcopy(self.deleted_points),
                "axis_confirmed": dict(self.axis_confirmed), "units_confirmed": self.units_confirmed,
                "axis_recognition": copy.deepcopy(self.axis_recognition),
                "saved_curves": copy.deepcopy(self.saved_curves),
                "units": (self.current_unit, self.voltage_unit, self.voltage_basis, self.x_unit_text, self.y_unit_text)}

    def _set_state(self, s: dict) -> None:
        self.points = [DraftPoint(**p) for p in s["points"]]
        self.anchors = {k: Anchor(**a) for k, a in s["anchors"].items()}
        self.roi = s["roi"]
        self.selected_candidate = s["selected_candidate"]
        self.scales = dict(s["scales"])
        self.next_id = s["next_id"]
        self.extraction_method = s["extraction_method"]
        self.deleted_points = copy.deepcopy(s["deleted_points"])
        self.axis_confirmed = dict(s.get("axis_confirmed", self.axis_confirmed))
        self.units_confirmed = s.get("units_confirmed", self.units_confirmed)
        self.axis_recognition = copy.deepcopy(s.get("axis_recognition", self.axis_recognition))
        self.saved_curves = copy.deepcopy(s.get("saved_curves", self.saved_curves))
        if "units" in s:
            (self.current_unit, self.voltage_unit, self.voltage_basis, self.x_unit_text, self.y_unit_text) = s["units"]

    def _push_undo(self) -> None:
        self.undo_stack.append(self._state())
        del self.undo_stack[:-MAX_HISTORY]
        self.redo_stack.clear()

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self._state())
        self._set_state(self.undo_stack.pop())
        self._log("deshacer", {})
        self._bump()
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self._state())
        self._set_state(self.redo_stack.pop())
        self._log("rehacer", {})
        self._bump()
        return True

    def _bump(self) -> None:
        self.rev += 1

    def _log(self, action: str, data: dict) -> None:
        self.audit.append({"timestamp_utc": _now(), "action": action, "data": _jsonable(data)})

    # ------------------------------------------------------------------ geometría
    def _clamp(self, px: float, py: float) -> tuple[float, float]:
        return (min(max(float(px), 0.0), float(self.image.width)), min(max(float(py), 0.0), float(self.image.height)))

    def _point(self, pid: int) -> DraftPoint | None:
        return next((p for p in self.points if p.id == int(pid)), None)

    def _touch(self, p: DraftPoint) -> None:
        p.edits += 1
        p.edited_at = _now()
        self.extraction_method = "automático + corrección manual" if any(
            q.origin and q.origin != "manual" for q in self.points) else "manual"

    # ------------------------------------------------------------------ edición
    def apply_event(self, ev: dict) -> bool:
        """Aplica un evento discreto del lienzo o de la interfaz. Devuelve True si cambió algo."""
        if not isinstance(ev, dict):
            return False
        t = ev.get("type")
        try:
            if t == "undo":
                return self.undo()
            if t == "redo":
                return self.redo()
            if t == "move_point":
                p = self._point(ev["id"])
                if p is None:
                    return False
                nx, ny = self._clamp(ev["px"], ev["py"])
                if abs(nx - p.px) < 1e-9 and abs(ny - p.py) < 1e-9:
                    return False
                self._push_undo()
                old = (p.px, p.py)
                p.px, p.py = nx, ny
                self._touch(p)
                self._log("mover_punto", {"id": p.id, "de_px": old, "a_px": (nx, ny)})
            elif t == "add_point":
                nx, ny = self._clamp(ev["px"], ev["py"])
                self._push_undo()
                p = DraftPoint(self.next_id, nx, ny, method=METHOD_MANUAL, edited_at=_now(), origin="manual")
                self.next_id += 1
                self.points.append(p)
                self._touch(p)
                p.edits = 0
                self._log("añadir_punto", {"id": p.id, "px": (nx, ny)})
            elif t == "delete_point":
                p = self._point(ev["id"])
                if p is None:
                    return False
                self._push_undo()
                self.points.remove(p)
                self.deleted_points.append({**p.to_dict(), "deleted_at": _now()})
                self._touch(p)
                self._log("borrar_punto", {"id": p.id, "px": (p.px, p.py), "metodo": p.method})
            elif t == "toggle_include":
                p = self._point(ev["id"])
                if p is None:
                    return False
                self._push_undo()
                p.include = not p.include
                self._log("excluir_punto" if not p.include else "incluir_punto", {"id": p.id})
            elif t == "set_include_box":
                x0, x1 = sorted((float(ev["x0"]), float(ev["x1"])))
                y0, y1 = sorted((float(ev["y0"]), float(ev["y1"])))
                inc = bool(ev.get("include", False))
                hit = [p for p in self.points if x0 <= p.px <= x1 and y0 <= p.py <= y1 and p.include != inc]
                if not hit:
                    return False
                self._push_undo()
                for p in hit:
                    p.include = inc
                self._log("incluir_seleccion" if inc else "excluir_seleccion", {"ids": [p.id for p in hit]})
            elif t == "set_anchor":
                name = ev["name"]
                if name not in ANCHOR_NAMES:
                    return False
                nx, ny = self._clamp(ev["px"], ev["py"])
                a = self.anchors[name]
                self._push_undo()
                old = (a.px, a.py)
                a.px, a.py, a.edited, a.source = nx, ny, True, "usuario"
                self._log("mover_ancla", {"ancla": name, "de_px": old, "a_px": (nx, ny)})
            elif t == "set_roi":
                x0, y0 = self._clamp(ev["x0"], ev["y0"])
                x1, y1 = self._clamp(ev["x1"], ev["y1"])
                x0, x1 = sorted((x0, x1))
                y0, y1 = sorted((y0, y1))
                if x1 - x0 < 10 or y1 - y0 < 10:
                    self.last_error = "ROI demasiado pequeño (mínimo 10 × 10 px)."
                    return False
                self._push_undo()
                self.roi = (x0, y0, x1, y1)
                self._log("cambiar_roi", {"roi_px": self.roi})
            else:
                return False
        except (KeyError, TypeError, ValueError) as exc:
            self.last_error = f"Evento de edición inválido ({t}): {exc}"
            return False
        self.last_error = None
        self._bump()
        return True

    def select_candidate(self, cid: str | None) -> bool:
        if self.detection is None or cid == self.selected_candidate:
            return False
        cand = next((c for c in self.detection.candidates if c.id == cid), None)
        if cid is not None and cand is None:
            return False
        self._push_undo()
        self.selected_candidate = cid
        if cand is not None:
            self._points_from_candidate(cand)
        else:
            self.points = []
        self.extraction_method = "automático" if cand is not None else "manual"
        self._log("seleccionar_candidato", {"candidato": cid, "resumen": cand.summary() if cand else None})
        self._bump()
        return True

    def clear_points(self) -> bool:
        """Modo manual completo: vacía el trazo (queda registrado y es reversible)."""
        if not self.points:
            return False
        self._push_undo()
        for p in self.points:
            self.deleted_points.append({**p.to_dict(), "deleted_at": _now()})
        self._log("vaciar_trazo", {"n": len(self.points)})
        self.points = []
        self.selected_candidate = None
        self.extraction_method = "manual"
        self._bump()
        return True

    def set_anchor_value(self, name: str, value: float | None) -> bool:
        a = self.anchors[name]
        v = None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)
        if v == a.value:
            return False
        self._push_undo()
        old = a.value
        a.value = v
        a.edited = True
        a.source = "usuario"
        self.axis_confirmed[name[0]] = True        # el usuario declara el valor: calibración manual de ese eje
        self._log("valor_ancla", {"ancla": name, "de": old, "a": v})
        self._bump()
        return True

    def set_anchor_position(self, name: str, pos: float | None) -> bool:
        a = self.anchors[name]
        if pos is None:
            return False
        if name[0] == "X":
            nx, _ = self._clamp(pos, 0)
            if a.px is not None and abs(nx - a.px) < 1e-9:
                return False
            return self.apply_event({"type": "set_anchor", "name": name, "px": nx,
                                     "py": a.py if a.py is not None else (self.plot_box[3] if self.plot_box else 0)})
        _, ny = self._clamp(0, pos)
        if a.py is not None and abs(ny - a.py) < 1e-9:
            return False
        return self.apply_event({"type": "set_anchor", "name": name, "py": ny,
                                 "px": a.px if a.px is not None else (self.plot_box[0] if self.plot_box else 0)})

    def set_scale(self, axis: str, scale: str) -> bool:
        if self.scales.get(axis) == scale:
            return False
        self._push_undo()
        self._log("escala_eje", {"eje": axis, "de": self.scales.get(axis), "a": scale})
        self.scales[axis] = scale
        self._bump()
        return True

    def set_units(self, current_unit: str, voltage_unit: str, voltage_basis: str) -> bool:
        new = (current_unit, voltage_unit, voltage_basis)
        if new == (self.current_unit, self.voltage_unit, self.voltage_basis):
            return False
        self._log("unidades", {"de": [self.current_unit, self.voltage_unit, self.voltage_basis], "a": list(new)})
        self.current_unit, self.voltage_unit, self.voltage_basis = new
        self.units_confirmed, self.units_source = True, "elegidas por el usuario"
        self.x_unit_text, self.y_unit_text = new[0], new[1]
        self._bump()
        return True

    # ------------------------------------------------------------------ calibración
    def calibration(self) -> tuple[Calibration | None, list[str], list[str]]:
        span_x = (self.plot_box[2] - self.plot_box[0]) if self.plot_box else self.image.width
        span_y = (self.plot_box[3] - self.plot_box[1]) if self.plot_box else self.image.height
        cx, ex, wx = build_axis(self.anchors["X1"], self.anchors["X2"], self.scales["X"], span_x)
        cy, ey, wy = build_axis(self.anchors["Y1"], self.anchors["Y2"], self.scales["Y"], span_y)
        if cx is None or cy is None:
            return None, ex + ey, wx + wy
        return Calibration(cx, cy), [], wx + wy

    @property
    def is_calibrated(self) -> bool:
        return self.calibration()[0] is not None

    # ------------------------------------------------------------------ vistas
    def sorted_points(self) -> list[DraftPoint]:
        return sorted(self.points, key=lambda p: (p.px, p.py))

    @property
    def x_label(self) -> str:
        return f"x [{self.current_unit}]"

    @property
    def y_label(self) -> str:
        return f"V [{self.voltage_unit}{'/celda' if self.voltage_basis == 'celda' else ' stack'}]"

    def table(self) -> pd.DataFrame:
        cal = self.calibration()[0]
        pts = self.sorted_points()
        df = pd.DataFrame({
            "id": [p.id for p in pts], "px": [round(p.px, 3) for p in pts], "py": [round(p.py, 3) for p in pts],
            self.x_label: [None] * len(pts), self.y_label: [None] * len(pts),
            "incluir": [p.include for p in pts], "método": [p.method for p in pts],
            "modificado": [p.modified for p in pts]})
        if cal is not None and pts:
            xv, yv = cal.to_physical([p.px for p in pts], [p.py for p in pts])
            df[self.x_label] = np.asarray(xv, float)
            df[self.y_label] = np.asarray(yv, float)
        return df

    def physical(self, include_only: bool = True) -> tuple[np.ndarray, np.ndarray, list[DraftPoint]]:
        cal = self.calibration()[0]
        if cal is None:
            raise ValueError("Calibración pendiente: no hay valores físicos.")
        pts = [p for p in self.sorted_points() if p.include or not include_only]
        xv, yv = cal.to_physical([p.px for p in pts], [p.py for p in pts])
        return np.asarray(xv, float).reshape(-1), np.asarray(yv, float).reshape(-1), pts

    def apply_table_delta(self, delta: dict, row_ids: list[int]) -> bool:
        """Aplica las ediciones de ``st.data_editor`` (edited_rows/added_rows/deleted_rows).

        Ediciones en columnas físicas se convierten a píxeles con la calibración vigente.
        """
        cal = self.calibration()[0]
        edited = delta.get("edited_rows", {}) or {}
        added = delta.get("added_rows", []) or []
        deleted = delta.get("deleted_rows", []) or []
        if not (edited or added or deleted):
            return False
        self._push_undo()
        changes = []
        for ridx, cols in edited.items():
            ridx = int(ridx)
            if ridx >= len(row_ids):
                continue
            p = self._point(row_ids[ridx])
            if p is None:
                continue
            nx, ny = p.px, p.py
            if "incluir" in cols:
                p.include = bool(cols["incluir"])
                changes.append({"id": p.id, "incluir": p.include})
            if "px" in cols and cols["px"] is not None:
                nx = float(cols["px"])
            if "py" in cols and cols["py"] is not None:
                ny = float(cols["py"])
            if cal is not None:
                if cols.get(self.x_label) is not None:
                    nx = float(cal.x.to_pixel(float(cols[self.x_label])))
                if cols.get(self.y_label) is not None:
                    ny = float(cal.y.to_pixel(float(cols[self.y_label])))
            if not (math.isfinite(nx) and math.isfinite(ny)):
                self.last_error = f"Punto {p.id}: valor no finito; edición ignorada."
                continue
            if (nx, ny) != (p.px, p.py):
                out = not (0 <= nx <= self.image.width and 0 <= ny <= self.image.height)
                if out:
                    self.last_error = (f"Punto {p.id}: el valor introducido cae fuera de la imagen "
                                       f"({nx:.1f}, {ny:.1f}) px; edición ignorada.")
                    continue
                changes.append({"id": p.id, "de_px": (p.px, p.py), "a_px": (nx, ny)})
                p.px, p.py = nx, ny
                self._touch(p)
        for ridx in sorted(int(i) for i in deleted):
            if ridx < len(row_ids):
                p = self._point(row_ids[ridx])
                if p is not None:
                    self.points.remove(p)
                    self.deleted_points.append({**p.to_dict(), "deleted_at": _now()})
                    changes.append({"id": p.id, "borrado": True})
        for row in added:
            nx, ny = row.get("px"), row.get("py")
            if cal is not None and row.get(self.x_label) is not None and row.get(self.y_label) is not None:
                nx = float(cal.x.to_pixel(float(row[self.x_label])))
                ny = float(cal.y.to_pixel(float(row[self.y_label])))
            if nx is None or ny is None:
                continue
            nx, ny = float(nx), float(ny)
            if not (0 <= nx <= self.image.width and 0 <= ny <= self.image.height):
                self.last_error = "Fila añadida fuera de la imagen; ignorada."
                continue
            p = DraftPoint(self.next_id, nx, ny, method=METHOD_MANUAL, edited_at=_now(), origin="manual")
            self.next_id += 1
            self.points.append(p)
            changes.append({"id": p.id, "añadido_px": (nx, ny)})
        if not changes:
            self.undo_stack.pop()
            return False
        if any("de_px" in c or "borrado" in c or "añadido_px" in c for c in changes):
            self.extraction_method = "automático + corrección manual" if any(
                q.origin and q.origin != "manual" for q in self.points) else "manual"
        self._log("edicion_tabla", {"cambios": changes})
        self._bump()
        return True

    # ------------------------------------------------------------------ resúmenes
    def edit_counts(self) -> dict:
        return {"movidos": sum(1 for p in self.points if p.method == METHOD_AUTO and p.edits > 0),
                "añadidos": sum(1 for p in self.points if p.method == METHOD_MANUAL),
                "borrados": len(self.deleted_points),
                "excluidos": sum(1 for p in self.points if not p.include)}

    @property
    def manually_edited(self) -> bool:
        c = self.edit_counts()
        return bool(c["movidos"] or c["añadidos"] or c["borrados"])

    def resolution(self) -> dict | None:
        """Resolución de la imagen en unidades físicas (por píxel) y estimación de digitalización.

        La estimación (±0,5 px de cuantización/colocación) NO es la incertidumbre de la
        medición original: solo describe la imagen. No se asigna a σ_V sin decisión del usuario.
        """
        cal = self.calibration()[0]
        if cal is None:
            return None
        try:
            xv, yv, pts = self.physical()
        except ValueError:
            return None
        if not pts:
            return None
        mid_x, mid_y = float(np.median(xv)), float(np.median(yv))
        dx = cal.x.value_per_pixel(mid_x)
        dy = cal.y.value_per_pixel(mid_y)
        thick = None
        if self.detection and self.selected_candidate:
            c = next((c for c in self.detection.candidates if c.id == self.selected_candidate), None)
            thick = c.thickness if c else None
        return {"x_per_px": dx, "y_per_px": dy, "x_unit": self.current_unit, "y_unit": self.voltage_unit,
                "sigma_dig_y": 0.5 * dy, "sigma_dig_x": 0.5 * dx, "line_thickness_px": thick,
                "basis": "±0,5 px de cuantización y colocación de anclas, convertidos con la pendiente de calibración"}

    def ranges(self) -> dict:
        """Rangos del área de trazado y de los puntos, en píxeles y (si hay calibración) físicos."""
        out: dict = {"calibrated": False}
        pts = [p for p in self.points if p.include]
        if pts:
            out["points_px"] = {"x": (min(p.px for p in pts), max(p.px for p in pts)),
                                "y": (min(p.py for p in pts), max(p.py for p in pts))}
        cal = self.calibration()[0]
        if cal is None:
            return out
        out["calibrated"] = True
        if self.plot_box:
            x0, y0, x1, y1 = self.plot_box
            ax = sorted(float(v) for v in cal.x.to_value([x0, x1]))
            ay = sorted(float(v) for v in cal.y.to_value([y1, y0]))
            out["axes"] = {"x": tuple(ax), "y": tuple(ay)}
        if pts:
            xv, yv, _ = self.physical()
            out["points"] = {"x": (float(xv.min()), float(xv.max())), "y": (float(yv.min()), float(yv.max())),
                             "n": int(len(xv))}
        return out

    def status(self, metadata_ok: bool = False) -> str:
        if self.confirmed_curve_ids and not self.rev_since_confirm:
            return ST_CONFIRMED
        if self.last_error and not self.points:
            return ST_ERROR
        if not self.is_calibrated:
            return ST_NEEDS_CAL if self.points or self.detection else ST_AUTO
        return ST_READY if metadata_ok and len([p for p in self.points if p.include]) >= 3 else ST_REVIEW

    rev_at_confirm: int = -1

    @property
    def rev_since_confirm(self) -> bool:
        return self.rev != self.rev_at_confirm

    def quality_warnings(self) -> list[str]:
        """Avisos de la digitalización (no del ajuste)."""
        w: list[str] = []
        cal, errs, cw = self.calibration()
        w += cw
        if cal is None:
            w.append("Coordenadas en píxeles / calibración pendiente: no hay valores físicos.")
        inc = [p for p in self.points if p.include]
        if len(inc) < 4:
            w.append(f"Solo {len(inc)} punto(s) incluidos: se recomiendan al menos 4 (mínimo del pipeline: 3).")
        if self.detection:
            w += self.detection.warnings
            c = next((c for c in self.detection.candidates if c.id == self.selected_candidate), None)
            if c:
                w += [f"[{c.id}] {m}" for m in c.warnings]
        if cal is not None and inc:
            xs = [a.px for a in (self.anchors["X1"], self.anchors["X2"])]
            ys = [a.py for a in (self.anchors["Y1"], self.anchors["Y2"])]
            outx = [p.id for p in inc if not (min(xs) - 0.5 <= p.px <= max(xs) + 0.5)]
            outy = [p.id for p in inc if not (min(ys) - 0.5 <= p.py <= max(ys) + 0.5)]
            if outx:
                w.append(f"{len(outx)} punto(s) fuera del intervalo entre X1 y X2: extrapolación de la escala "
                         f"(ids {outx[:8]}).")
            if outy:
                w.append(f"{len(outy)} punto(s) fuera del intervalo entre Y1 y Y2: extrapolación de la escala "
                         f"(ids {outy[:8]}).")
            if self.plot_box:
                x0, y0, x1, y1 = self.plot_box
                outbox = [p.id for p in inc if not (x0 - 1 <= p.px <= x1 + 1 and y0 - 1 <= p.py <= y1 + 1)]
                if outbox:
                    w.append(f"{len(outbox)} punto(s) fuera del área de trazado detectada (ids {outbox[:8]}): "
                             "exclúyalos o corríjalos; no se recortan automáticamente.")
        for axis, rec in self.axis_recognition.items():
            if not self.axis_confirmed.get(axis) and rec.status != "CONFIABLE":
                w.append(f"Eje {axis}: {rec.status} — " + "; ".join(rec.reasons[:3]))
        if not self.units_confirmed:
            w.append("Unidades no confirmadas: elíjalas o confírmelas explícitamente.")
        if any(a.source == "auto-marco" and not a.edited for a in self.anchors.values()):
            w.append("Alguna ancla propuesta está en el borde del marco (sin tick detectado): confirme su posición.")
        if self.manually_edited:
            c = self.edit_counts()
            w.append(f"Trazo intervenido manualmente: {c['movidos']} movido(s), {c['añadidos']} añadido(s), "
                     f"{c['borrados']} borrado(s).")
        return list(dict.fromkeys(w))


    # ------------------------------------------------------------------ reconocimiento de ejes (v0.3.0)
    def _recognize_axes(self) -> None:
        from .axis_ocr import recognize_axes
        res = self.detection
        try:
            recs = recognize_axes(self.image.rgb, res.panels[res.panel_index], res.ticks, res.background_rgb)
        except Exception as exc:  # noqa: BLE001 — el reconocimiento nunca bloquea el modo manual
            self._log("ocr_fallido", {"error": str(exc)})
            return
        self.axis_recognition = recs
        self._log("reconocimiento_ejes", {k: v.to_dict() for k, v in recs.items()})
        for axis in ("X", "Y"):
            self._apply_axis(axis)
        self._apply_units()

    def _tick_spacing(self, axis: str) -> float | None:
        t = self.detection.ticks.get(axis) if self.detection else None
        if t and len(t.positions) > 1:
            return float(np.median(np.diff(sorted(t.positions))))
        return None

    def _apply_axis(self, axis: str) -> None:
        """Lleva el reconocimiento de un eje a sus anclas (nunca pisa anclas editadas por el usuario)."""
        from .axis_ocr import ST_RELIABLE
        rec = self.axis_recognition.get(axis)
        names = ("X1", "X2") if axis == "X" else ("Y1", "Y2")
        if rec is None or len(rec.anchors) < 2:
            self.axis_confirmed[axis] = False if not any(self.anchors[n].edited for n in names) else self.axis_confirmed[axis]
            return
        if any(self.anchors[n].edited and self.anchors[n].source == "usuario" for n in names):
            return
        mult = rec.multiplier or 1.0
        (p_lo, v_lo), (p_hi, v_hi) = sorted(rec.anchors)
        pb = self.plot_box
        if axis == "X":
            py = pb[3] if pb else None
            self.anchors["X1"] = Anchor("X1", px=p_lo, py=py, value=v_lo * mult, source="auto-ocr")
            self.anchors["X2"] = Anchor("X2", px=p_hi, py=py, value=v_hi * mult, source="auto-ocr")
        else:
            px = pb[0] if pb else None      # Y1 = referencia inferior (py mayor)
            self.anchors["Y1"] = Anchor("Y1", px=px, py=p_hi, value=v_hi * mult, source="auto-ocr")
            self.anchors["Y2"] = Anchor("Y2", px=px, py=p_lo, value=v_lo * mult, source="auto-ocr")
        if rec.scale:
            self.scales[axis] = rec.scale
        self.axis_confirmed[axis] = rec.status == ST_RELIABLE

    def _apply_units(self) -> None:
        from pemfc_core import units as u
        rx, ry = self.axis_recognition.get("X"), self.axis_recognition.get("Y")
        tx = (rx.title or {}) if rx else {}
        ty = (ry.title or {}) if ry else {}
        self.x_unit_text = tx.get("unit") or ""
        self.y_unit_text = ty.get("unit") or ""
        ok_x = tx.get("quantity") == "corriente" and tx.get("unit") in u.CURRENT_UNITS
        ok_y = ty.get("quantity") == "tensión" and ty.get("unit") in u.VOLTAGE_UNITS
        if ok_x:
            self.current_unit = tx["unit"]
        if ok_y:
            self.voltage_unit = ty["unit"]
        self.units_confirmed = bool(ok_x and ok_y)
        if self.units_confirmed:
            self.units_source = (f"leídas en los títulos de los ejes: «{tx.get('text')}» → {tx['unit']}; "
                                 f"«{ty.get('text')}» → {ty['unit']}")

    def confirm_axis(self, axis: str) -> bool:
        cal = self.calibration()[0]
        names = ("X1", "X2") if axis == "X" else ("Y1", "Y2")
        if any(self.anchors[n].value is None or self.anchors[n].position is None for n in names):
            self.last_error = f"Eje {axis}: no hay dos referencias completas que confirmar."
            return False
        self._push_undo()
        self.axis_confirmed[axis] = True
        self._log("confirmar_eje", {"eje": axis, "anclas": {n: self.anchors[n].to_dict() for n in names},
                                    "calibrado": cal is not None})
        self._bump()
        return True

    def confirm_units(self) -> bool:
        self._push_undo()
        self.units_confirmed = True
        if not self.units_source:
            self.units_source = "confirmadas por el usuario"
        self.x_unit_text = self.x_unit_text or self.current_unit
        self.y_unit_text = self.y_unit_text or self.voltage_unit
        self._log("confirmar_unidades", {"x": self.current_unit, "y": self.voltage_unit, "base": self.voltage_basis})
        self._bump()
        return True

    def set_free_units(self, x_unit: str, y_unit: str) -> bool:
        """Unidades libres (digitalizador autónomo). Las escribe el usuario: quedan confirmadas."""
        x_unit, y_unit = str(x_unit).strip(), str(y_unit).strip()
        if (x_unit, y_unit) == (self.x_unit_text, self.y_unit_text) and self.units_confirmed:
            return False
        self._push_undo()
        self.x_unit_text, self.y_unit_text = x_unit, y_unit
        self.units_confirmed = bool(x_unit and y_unit)
        self.units_source = "escritas por el usuario"
        self._log("unidades_libres", {"x": x_unit, "y": y_unit})
        self._bump()
        return True

    def correct_label(self, axis: str, index: int, value: float | None = None, exclude: bool | None = None) -> bool:
        """Corrige (o excluye) individualmente una etiqueta reconocida y recalcula la geometría."""
        from .axis_ocr import recompute
        rec = self.axis_recognition.get(axis)
        if rec is None or not (0 <= index < len(rec.labels)):
            return False
        self._push_undo()
        lab = rec.labels[index]
        old = (lab.user_value, lab.excluded_by_user)
        if value is not None or exclude is None:
            lab.user_value = None if value is None or (isinstance(value, float) and math.isnan(value)) else float(value)
        if exclude is not None:
            lab.excluded_by_user = bool(exclude)
        new = recompute(rec, self._tick_spacing(axis))
        self.axis_recognition[axis] = new
        names = ("X1", "X2") if axis == "X" else ("Y1", "Y2")
        for n in names:                       # la corrección de etiquetas vuelve a mandar sobre las anclas automáticas
            if self.anchors[n].source != "usuario":
                self.anchors[n].edited = False
        self._apply_axis(axis)
        self._log("corregir_etiqueta", {"eje": axis, "etiqueta": lab.text, "de": old,
                                        "a": (lab.user_value, lab.excluded_by_user), "estado": new.status})
        self._bump()
        return True

    def physical_ready(self) -> tuple[bool, list[str]]:
        """¿Se pueden usar los valores físicos de forma definitiva? (calibración + confirmaciones)."""
        reasons = []
        cal, errs, _ = self.calibration()
        if cal is None:
            reasons += errs or ["Calibración incompleta."]
        for axis in ("X", "Y"):
            if not self.axis_confirmed.get(axis):
                rec = self.axis_recognition.get(axis)
                why = f" ({rec.status}: {'; '.join(rec.reasons[:2])})" if rec else ""
                reasons.append(f"Eje {axis} pendiente de confirmación{why}.")
        if not self.units_confirmed:
            reasons.append("Unidades no confirmadas (no se detectaron con evidencia en los títulos de los ejes).")
        return (not reasons), reasons

    def ocr_boxes(self) -> list[dict]:
        out = []
        for axis, rec in self.axis_recognition.items():
            for i, l in enumerate(rec.labels):
                out.append({"axis": axis, "i": i, "bbox": l.bbox_px, "text": l.text, "value": l.effective_value,
                            "inlier": l.inlier and not l.excluded_by_user, "user": l.user_value is not None,
                            "excluded": l.excluded_by_user, "pos": l.position_px})
            if rec.title:
                out.append({"axis": axis, "i": -1, "bbox": rec.title["bbox_px"], "text": rec.title["text"],
                            "value": None, "inlier": rec.title.get("unit") is not None, "title": True,
                            "unit": rec.title.get("unit")})
        return out

    # ------------------------------------------------------------------ curvas guardadas del panel
    def save_curve(self, name: str) -> dict:
        name = str(name).strip()
        if not name:
            raise ValueError("La curva necesita un nombre.")
        if any(c["name"] == name for c in self.saved_curves):
            raise ValueError(f"Ya existe una curva guardada llamada {name!r} en este panel.")
        if not self.points:
            raise ValueError("No hay puntos que guardar.")
        self._push_undo()
        rec = {"name": name, "candidate": self.selected_candidate, "method": self.extraction_method,
               "saved_utc": _now(), "points": [p.to_dict() for p in self.sorted_points()]}
        self.saved_curves.append(rec)
        self._log("guardar_curva", {"curva": name, "n": len(rec["points"]), "candidato": self.selected_candidate})
        self._bump()
        return rec

    def delete_saved_curve(self, name: str) -> bool:
        idx = next((i for i, c in enumerate(self.saved_curves) if c["name"] == name), None)
        if idx is None:
            return False
        self._push_undo()
        self.saved_curves.pop(idx)
        self._log("borrar_curva_guardada", {"curva": name})
        self._bump()
        return True

    def load_saved_curve(self, name: str) -> bool:
        rec = next((c for c in self.saved_curves if c["name"] == name), None)
        if rec is None:
            return False
        self._push_undo()
        self.points = [DraftPoint(**p) for p in rec["points"]]
        self.next_id = max([p.id for p in self.points] + [self.next_id - 1]) + 1
        self.selected_candidate = rec.get("candidate")
        self._log("cargar_curva_guardada", {"curva": name})
        self._bump()
        return True

    # ------------------------------------------------------------------ serialización
    def to_audit_dict(self) -> dict:
        cal, errs, warns = self.calibration()
        d = {
            "schema": "pemfc-modellab/digitization", "schema_version": "1.0.0",
            "extraction_engine": {"algorithm": ALGORITHM_ID, "version": DIGITIZER_VERSION},
            "created_utc": self.created_utc, "exported_utc": _now(),
            "pixel_convention": "origen en la esquina superior izquierda; x hacia la derecha; y hacia ABAJO; "
                                "coordenadas continuas (centro del píxel (c, f) en (c+0,5, f+0,5))",
            "image": self.image.describe(),
            "extraction_method": self.extraction_method,
            "detection_params": self.params.to_dict(),
            "detection": self.detection.summary() if self.detection else None,
            "selected_trace_id": self.selected_candidate,
            "plot_box_px": list(self.plot_box) if self.plot_box else None,
            "roi_px": list(self.roi) if self.roi else None,
            "axis_scales": dict(self.scales),
            "calibration_anchors": [self.anchors[n].to_dict() for n in ANCHOR_NAMES],
            "calibration": cal.to_dict() if cal else None,
            "calibration_errors": errs, "calibration_warnings": warns,
            "units": {"current_unit": self.current_unit, "voltage_unit": self.voltage_unit,
                      "voltage_basis": self.voltage_basis, "x_unit_text": self.x_unit_text,
                      "y_unit_text": self.y_unit_text, "confirmed": self.units_confirmed, "source": self.units_source},
            "axis_recognition": {k: v.to_dict() for k, v in self.axis_recognition.items()},
            "axis_confirmed": dict(self.axis_confirmed),
            "panel_index": self.panel_index,
            "saved_curves": [{"name": c["name"], "n_points": len(c["points"]), "saved_utc": c["saved_utc"],
                              "candidate": c.get("candidate")} for c in self.saved_curves],
            "points": [p.to_dict() for p in self.sorted_points()],
            "deleted_points": self.deleted_points,
            "edit_counts": self.edit_counts(),
            "resolution": self.resolution(),
            "warnings": self.quality_warnings(),
            "audit_events": self.audit,
            "notice": "Datos DIGITALIZADOS de una imagen. No constituyen una medición independiente ni validación "
                      "experimental. Los valores físicos derivan de las anclas declaradas por el usuario.",
        }
        if cal is not None:
            xv, yv, pts = self.physical(include_only=False)
            for rec, x, y in zip(d["points"], xv, yv):
                rec["x_value"] = float(x)
                rec["y_value"] = float(y)
        return _jsonable(d)

    def to_csv(self) -> str:
        """CSV de la digitalización (píxeles + físicos si hay calibración)."""
        df = self.table()
        out = pd.DataFrame({"point_id": df["id"], "px": df["px"], "py": df["py"]})
        if self.is_calibrated:
            out[f"current_{self.current_unit}"] = df[self.x_label]
            out[f"voltage_{self.voltage_unit}_{self.voltage_basis}"] = df[self.y_label]
            # Columnas normalizadas solo si no requieren geometría (no se infieren N_cells ni A_active).
            from pemfc_core import units as u
            if not u.current_is_total(self.current_unit):
                out["current_density_A_cm2"] = df[self.x_label] * u.CURRENT_UNITS[self.current_unit][1]
            if self.voltage_basis == "celda":
                out["voltage_V"] = df[self.y_label] * u.VOLTAGE_UNITS[self.voltage_unit]
        out["include"] = df["incluir"]
        out["method"] = df["método"]
        out["modified"] = df["modificado"]
        buf = io.StringIO()
        buf.write(f"# Digitalización de {self.image.filename} (SHA-256 {self.image.sha256})\n")
        buf.write(f"# {ALGORITHM_ID} v{DIGITIZER_VERSION}; método: {self.extraction_method}; "
                  f"{'calibrado' if self.is_calibrated else 'SIN CALIBRAR (solo píxeles)'}\n")
        out.to_csv(buf, index=False)
        return buf.getvalue()


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        return x if math.isfinite(x) else None
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    return obj


def audit_json(draft: DigitizationDraft) -> str:
    return json.dumps(draft.to_audit_dict(), indent=2, ensure_ascii=False)
