"""Digitalizador asistido (popup) para la pestaña «1. Importar curva».

Aislamiento: el borrador vive en ``st.session_state.dz_draft`` y solo este módulo lo
toca. Cancelar o un error nunca modifican ``curves``, ``originals``, ``fit_config``,
``fit_result``, ``profile`` ni ``dataset_label``. Confirmar llama UNA vez a
``state.set_dataset`` con el conjunto combinado, tras ``build_curve`` y
``check_curve_set`` (ver ``digitizer.confirm``).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from digitizer import ALGORITHM_ID, DIGITIZER_VERSION
from digitizer.calibration import ANCHOR_NAMES, AXIS_SCALES, SCALE_LOG
from digitizer.confirm import build_digitized_curve
from digitizer.detection import DetectionParams
from digitizer.draft import (
    ST_CONFIRMED, ST_ERROR, ST_NEEDS_CAL, ST_READY, ST_REVIEW, DigitizationDraft, audit_json,
)
from digitizer.imageio import ACCEPTED_EXTENSIONS, ImageLoadError, load_image
from identification.datasets import ConditionInput, ValidationIssue
from pemfc_core import units
from pemfc_core.parameters import ORIGINS
from pemfc_core.schemas import CURVE_ROLES, QUALITY_DIGITIZED, CurveMetadata

from . import state

STATIC = Path(__file__).resolve().parent / "static"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "digitizer"
_JS = (STATIC / "digitizer_canvas.js").read_text(encoding="utf-8")
_CSS = (STATIC / "digitizer_canvas.css").read_text(encoding="utf-8")
DEVICE_ORIGINS = [o for o in ORIGINS if o != "IDENTIFICADO"]
NONE_CAND = "(ninguno: trazado manual)"
CURRENT_CHOICES = ["A/cm²", "mA/cm²", "A", "mA", "A/m²"]
STATUS_TEXT = {
    "AUTO_DETECTADA": ("info", "Trazo detectado en píxeles."),
    ST_NEEDS_CAL: ("warning", "Coordenadas en píxeles / calibración pendiente: escriba los valores de X1, X2, Y1 e Y2. "
                              "Confirmar está bloqueado."),
    ST_REVIEW: ("info", "Calibrado: revise el trazo, la tabla y complete las condiciones de medición."),
    ST_READY: ("success", "Listo para confirmar."),
    ST_ERROR: ("error", "Error recuperable: la imagen y el borrador se conservan; reintente o trace manualmente."),
    ST_CONFIRMED: ("success", "Curva ya añadida al conjunto. Puede digitalizar otra curva de esta imagen."),
}
EXAMPLE_IMAGES = [
    ("01_curva_simple.png", "Sintético: una curva", "Fixture SINTÉTICO del handoff (no experimental)."),
    ("02_dos_curvas.png", "Sintético: dos curvas", "Fixture SINTÉTICO del handoff (no experimental)."),
    ("otekon_figure3_source.png", "Figura publicada OTEKON Fig. 3",
     "Gráfica real (4 paneles) de Altıntaş & Ertan, OTEKON 2024, vía repositorio PEM-FC @ a533432."),
]


def _canvas_component():
    # Registrar en cada ejecución es inocuo (definición idéntica) y robusto ante runtimes nuevos.
    return st.components.v2.component("pml_digitizer_canvas", css=_CSS, js=_JS)


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def _ss():
    return st.session_state


def _draft() -> DigitizationDraft | None:
    return _ss().get("dz_draft")


def _fmt(v, nd=5) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    a = abs(v)
    if a != 0 and (a < 1e-3 or a >= 1e5):
        return f"{v:.3e}"
    return f"{v:.{nd}g}"


def _parse(text) -> float | None:
    if text is None:
        return None
    s = str(text).strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return float("nan")
    return x


def _sync_widgets(d: DigitizationDraft) -> None:
    """Refleja el borrador en los widgets (solo desde callbacks o antes de crearlos)."""
    ss = _ss()
    for n in ANCHOR_NAMES:
        a = d.anchors[n]
        pos = a.px if n[0] == "X" else a.py
        ss[f"dz_pos_{n}"] = "" if pos is None else f"{pos:.2f}"
        ss[f"dz_val_{n}"] = "" if a.value is None else f"{a.value:g}"
    ss["dz_scale_X"], ss["dz_scale_Y"] = d.scales["X"], d.scales["Y"]
    ss["dz_cu"], ss["dz_vu"], ss["dz_vb"] = d.current_unit, d.voltage_unit, d.voltage_basis
    ss["dz_xu_text"], ss["dz_yu_text"] = d.x_unit_text, d.y_unit_text
    labels = _cand_labels(d)
    ss["dz_cand"] = next((lab for cid, lab in labels if cid == d.selected_candidate), NONE_CAND)
    if d.detection is not None:
        ss["dz_panel"] = (d.detection.panel_index or 0) + 1 if d.detection.panels else 1
        ss["dz_panel_saved"] = sorted(k + 1 for k in (ss.get("dz_panels") or {}))
    p = d.params
    ss["dz_npts"], ss["dz_tol"], ss["dz_alpha"] = int(p.n_points), float(p.color_tolerance), float(p.alpha_min)
    ss["dz_trim"], ss["dz_legend"] = bool(p.trim_caps), bool(p.exclude_legends)


def _cand_labels(d: DigitizationDraft) -> list[tuple[str | None, str]]:
    out = [(None, NONE_CAND)]
    if d.detection:
        out += [(c.id, c.label) for c in d.detection.candidates]
    return out


def _reset_metadata_widgets(stem: str) -> None:
    ss = _ss()
    ss["dz_id"] = f"dig_{stem}"[:60]
    for k in ("dz_T", "dz_P", "dz_amb", "dz_ph2", "dz_yo2", "dz_sig"):
        ss[k] = None
    ss["dz_sig_origin"] = ""
    ss["dz_src"] = ""
    ss["dz_prov"] = ""


def _new_draft(data: bytes, name: str, progress=None, upload_id: str | None = None) -> bool:
    """Crea el borrador de forma ATÓMICA: el estado solo cambia si todo el procesamiento termina bien.

    Así, si la ejecución se interrumpe o falla, la siguiente ejecución vuelve a procesar el archivo (no queda
    «marcado como procesado» sin borrador, que obligaría a cargarlo dos veces).
    """
    ss = _ss()
    try:
        if progress:
            progress(f"Validando «{name}»…")
        img = load_image(data, name)
        d = DigitizationDraft.from_image(img, progress=progress)
    except ImageLoadError as exc:
        ss["dz_load_error"] = f"Imagen rechazada ({name}): {exc}"
        ss["dz_failed_upload"] = upload_id
        return False
    except Exception as exc:  # noqa: BLE001 — error recuperable: la sesión y el borrador anterior se conservan
        ss["dz_load_error"] = f"No se pudo procesar «{name}»: {exc}"
        ss["dz_failed_upload"] = upload_id
        return False
    ss["dz_draft"] = d
    ss["dz_panels"] = {int(d.panel_index or 0): d}       # cada panel conserva su propio borrador
    ss["dz_export"] = None
    ss["dz_load_error"] = None
    ss["dz_failed_upload"] = None
    ss["dz_pending"] = None
    t = getattr(d, "timings", {})
    ss["dz_loaded_msg"] = (f"Imagen procesada en {t.get('total_s', 0):.1f} s (detección {t.get('deteccion_s', 0):.1f} s"
                           + (f", OCR {t['ocr_s']:.1f} s" if "ocr_s" in t else "") + ").")
    _sync_widgets(d)
    _reset_metadata_widgets(Path(img.filename).stem)
    return True


def _sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _draft_has_work(d: DigitizationDraft) -> bool:
    panels = list((_ss().get("dz_panels") or {}).values()) or [d]
    return any(p.manually_edited or any(a.edited for a in p.anchors.values()) or p.saved_curves
               or any(l.user_value is not None or l.excluded_by_user
                      for r in p.axis_recognition.values() for l in r.labels) for p in panels)


# ---------------------------------------------------------------------------
# callbacks (se ejecutan antes de la reejecución del diálogo)
# ---------------------------------------------------------------------------
def _on_canvas_edit() -> None:
    d = _draft()
    val = _ss().get("dz_canvas")
    ev = None
    try:
        ev = val.get("edit") if hasattr(val, "get") else getattr(val, "edit", None)
    except Exception:  # noqa: BLE001
        ev = None
    if d is None or not isinstance(ev, dict):
        return
    if ev.get("seq") is not None and ev.get("seq") == _ss().get("dz_last_seq"):
        return
    _ss()["dz_last_seq"] = ev.get("seq")
    d.apply_event(ev)
    _sync_widgets(d)


def _on_action(action: str) -> None:
    d = _draft()
    if d is None:
        return
    if action == "undo":
        d.undo()
    elif action == "redo":
        d.redo()
    elif action == "clear":
        d.clear_points()
    elif action == "redetect":
        d.run_detection(_params_from_widgets(d, keep_roi=True))
        _ss()["dz_confirm_redetect"] = False
    elif action == "reset_roi":
        p = _params_from_widgets(d, keep_roi=False)
        p.roi = None
        d.run_detection(p)
        _ss()["dz_confirm_redetect"] = False
    _sync_widgets(d)


def _params_from_widgets(d: DigitizationDraft, keep_roi: bool) -> DetectionParams:
    ss = _ss()
    roi = None
    if keep_roi and d.roi and d.detection is not None and tuple(d.roi) != tuple(d.detection.roi or ()):
        roi = tuple(d.roi)       # ROI cambiado por el usuario
    elif keep_roi and d.params.roi:
        roi = tuple(d.roi) if d.roi else d.params.roi
    panel = ss.get("dz_panel")
    return DetectionParams(n_points=int(ss.get("dz_npts", 40)), alpha_min=float(ss.get("dz_alpha", 0.65)),
                           color_tolerance=float(ss.get("dz_tol", 45.0)), trim_caps=bool(ss.get("dz_trim", True)),
                           exclude_legends=bool(ss.get("dz_legend", True)), roi=roi,
                           panel_index=(int(panel) - 1) if panel else None)


def _on_candidate() -> None:
    d = _draft()
    if d is None:
        return
    lab = _ss().get("dz_cand")
    cid = next((c for c, l in _cand_labels(d) if l == lab), None)
    d.select_candidate(cid)
    _sync_widgets(d)


def _on_panel() -> None:
    """Cambia de panel SIN perder el trabajo del anterior (cada panel tiene su borrador y calibración)."""
    ss = _ss()
    d = _draft()
    if d is None:
        return
    idx = int(ss.get("dz_panel", 1)) - 1
    panels = ss.setdefault("dz_panels", {int(d.panel_index or 0): d})
    panels[int(d.panel_index or 0)] = d
    if idx not in panels:
        params = _params_from_widgets(d, keep_roi=False)
        params.roi, params.panel_index = None, idx
        panels[idx] = DigitizationDraft.from_image(d.image, params)
    ss["dz_draft"] = panels[idx]
    ss["dz_export"] = None
    _sync_widgets(panels[idx])


def _on_axis_confirm(axis: str) -> None:
    d = _draft()
    if d is not None:
        d.confirm_axis(axis)
        _sync_widgets(d)


def _on_units_confirm() -> None:
    d = _draft()
    if d is not None:
        d.confirm_units()


def _on_free_units() -> None:
    d = _draft()
    if d is not None:
        d.set_free_units(_ss().get("dz_xu_text", ""), _ss().get("dz_yu_text", ""))


def _on_labels(axis: str, key: str, idx_map: list[int]) -> None:
    d = _draft()
    delta = _ss().get(key) or {}
    if d is None:
        return
    for row, cols in (delta.get("edited_rows") or {}).items():
        i = idx_map[int(row)]
        if "excluir" in cols:
            d.correct_label(axis, i, exclude=bool(cols["excluir"]))
        if "valor" in cols:
            v = cols["valor"]
            d.correct_label(axis, i, value=None if v in (None, "") else float(v))
    _sync_widgets(d)


def _on_save_curve() -> None:
    d = _draft()
    name = str(_ss().get("dz_curve_name", "")).strip()
    if d is None:
        return
    try:
        d.save_curve(name or f"curva_{len(d.saved_curves) + 1}")
        _ss()["dz_curve_name"] = ""
        _ss()["dz_export"] = None
    except ValueError as exc:
        d.last_error = str(exc)


def _on_curve_action(action: str) -> None:
    d = _draft()
    name = _ss().get("dz_saved_pick")
    if d is None or not name:
        return
    (d.load_saved_curve if action == "load" else d.delete_saved_curve)(name)
    _ss()["dz_export"] = None
    _sync_widgets(d)


# ---------------------------------------------------------------------------
# contextos aislados: cada identificación del Motor 1 y el modo autónomo tienen su propio digitalizador
# ---------------------------------------------------------------------------
_CTX_KEYS = ("dz_draft", "dz_panels", "dz_pending", "dz_load_error", "dz_failed_upload", "dz_flash", "dz_open",
             "dz_export")


def use_context(name: str) -> None:
    ss = _ss()
    cur = ss.get("dzctx_name", "motor1")
    if cur == name:
        return
    stash = ss.setdefault("dzctx_stash", {})
    stash[cur] = {k: ss[k] for k in _CTX_KEYS if k in ss}
    for k in _CTX_KEYS:
        ss.pop(k, None)
    for k, v in stash.pop(name, {}).items():
        ss[k] = v
    ss["dz_upload_nonce"] = ss.get("dz_upload_nonce", 0) + 1
    ss["dzctx_name"] = name
    d = _draft()
    if d is not None:
        _sync_widgets(d)


def _on_anchor(name: str, what: str) -> None:
    d = _draft()
    if d is None:
        return
    v = _parse(_ss().get(f"dz_{what}_{name}"))
    if what == "val":
        if v is not None and not math.isfinite(v):
            d.last_error = f"{name}: el valor debe ser un número (admite coma decimal)."
        else:
            d.set_anchor_value(name, v)
    else:
        if v is None or not math.isfinite(v):
            d.last_error = f"{name}: la posición debe ser un número de píxel."
        else:
            d.set_anchor_position(name, v)
    _sync_widgets(d)


def _on_scale(axis: str) -> None:
    d = _draft()
    if d is not None:
        d.set_scale(axis, _ss()[f"dz_scale_{axis}"])
        _sync_widgets(d)


def _on_units() -> None:
    d = _draft()
    if d is not None:
        ss = _ss()
        d.set_units(ss["dz_cu"], ss["dz_vu"], ss["dz_vb"])


def _on_table(key: str, row_ids: list[int]) -> None:
    d = _draft()
    delta = _ss().get(key)
    if d is None or not delta:
        return
    d.apply_table_delta(dict(delta), row_ids)
    _sync_widgets(d)


def _on_use_sigma(value_mV: float, basis: str) -> None:
    _ss()["dz_sig"] = round(float(value_mV), 4)
    _ss()["dz_sig_origin"] = basis
    _ss()["dz_sig_value_at_origin"] = round(float(value_mV), 4)


def _on_dismiss() -> None:
    _ss()["dz_open"] = False


def _open() -> None:
    _ss()["dz_open"] = True


def _cancel() -> None:
    """Descarta el borrador. NO toca curvas, originales, configuración, resultados ni perfil."""
    ss = _ss()
    for k in [k for k in list(ss.keys()) if str(k).startswith("dz_") and not str(k).startswith("dz_up_")]:
        if k in ("dz_upload_nonce",):
            continue
        del ss[k]
    ss["dz_upload_nonce"] = ss.get("dz_upload_nonce", 0) + 1
    ss["dz_open"] = False
    ss["dz_flash"] = ("info", "Digitalización descartada: el conjunto de curvas y los resultados no se modificaron.")


# ---------------------------------------------------------------------------
# secciones del diálogo
# ---------------------------------------------------------------------------
def _load_example(fname: str) -> None:
    path = EXAMPLES / fname
    if path.exists():
        _new_draft(path.read_bytes(), fname)


def _pending_choice(accept: bool) -> None:
    ss = _ss()
    pend = ss.get("dz_pending")
    ss["dz_pending"] = None
    if accept and pend:
        _new_draft(*pend)
    else:
        ss["dz_upload_nonce"] = ss.get("dz_upload_nonce", 0) + 1     # vacía el selector de archivos


def _upload_section(d: DigitizationDraft | None) -> None:
    """Uploader + ejemplos. Procesa la imagen en esta misma ejecución (sin st.rerun)."""
    ss = _ss()
    nonce = ss.setdefault("dz_upload_nonce", 0)
    label = "Imagen del gráfico (PNG, JPEG o WebP; máx. 10 MB, 25 MP)" if d is None else "Cambiar de imagen"
    up = st.file_uploader(label, type=ACCEPTED_EXTENSIONS, key=f"dz_up_{nonce}",
                          help="La imagen se procesa localmente en el servidor de la aplicación, en memoria; "
                               "no se envía a servicios externos ni se guarda en disco. SVG no se admite.")
    if up is not None:
        data = up.getvalue()
        sha = _sha(data)
        upload_id = getattr(up, "file_id", None) or f"{up.name}:{sha}"
        # Idempotente: se procesa mientras no exista un borrador de ESTE archivo. Un fallo no se reintenta en cada
        # reejecución, pero sí si el usuario vuelve a seleccionar el archivo (nueva subida = nuevo file_id).
        if (d is None or sha != d.image.sha256) and upload_id != ss.get("dz_failed_upload"):
            if d is not None and _draft_has_work(d):
                if not ss.get("dz_pending") or _sha(ss["dz_pending"][0]) != sha:
                    ss["dz_pending"] = (data, up.name)
            else:
                with st.status(f"Procesando «{up.name}»…", expanded=True) as status:
                    ok = _new_draft(data, up.name, progress=status.write, upload_id=upload_id)
                    status.update(label=("Imagen cargada." if ok else "No se pudo cargar la imagen."),
                                  state="complete" if ok else "error", expanded=not ok)
    if ss.get("dz_load_error"):
        st.error(ss["dz_load_error"] + " El borrador anterior (si lo había) se conserva.")
    pend = ss.get("dz_pending")
    if pend and d is not None:
        st.warning(f"Ya hay un borrador con ediciones de **{d.image.filename}**. ¿Descartarlo y usar "
                   f"**{pend[1]}**?")
        c1, c2 = st.columns(2)
        c1.button("Descartar borrador y usar la nueva imagen", key="dz_pend_yes", on_click=_pending_choice,
                  args=(True,))
        c2.button("Conservar el borrador actual", key="dz_pend_no", on_click=_pending_choice, args=(False,))
    if d is None and _draft() is None:
        st.markdown("**…o pruebe con una imagen de ejemplo:**")
        cols = st.columns(len(EXAMPLE_IMAGES))
        for col, (fname, title, desc) in zip(cols, EXAMPLE_IMAGES):
            if (EXAMPLES / fname).exists():
                col.button(title, key=f"dz_ex_{fname}", width="stretch", help=desc, on_click=_load_example,
                           args=(fname,))


def _canvas_data(d: DigitizationDraft) -> dict:
    """Datos del lienzo en tipos JSON nativos (los tipos numpy harían que llegaran como texto al navegador)."""
    from digitizer.draft import _jsonable
    return _jsonable(_canvas_data_raw(d))


def _canvas_data_raw(d: DigitizationDraft) -> dict:
    url, scale = d.image.display
    cal = d.calibration()[0]
    calib = None
    if cal is not None:
        calib = {"x": {"p1": cal.x.p1, "v1": cal.x.v1, "p2": cal.x.p2, "v2": cal.x.v2, "log": cal.x.scale == SCALE_LOG},
                 "y": {"p1": cal.y.p1, "v1": cal.y.v1, "p2": cal.y.p2, "v2": cal.y.v2, "log": cal.y.scale == SCALE_LOG},
                 "xunit": d.current_unit, "yunit": d.voltage_unit + (" (stack)" if d.voltage_basis == "stack" else "")}
    cands = []
    if d.detection:
        for c in d.detection.candidates:
            dense = c.dense
            if len(dense) > 600:
                dense = dense[np.linspace(0, len(dense) - 1, 600).astype(int)]
            cands.append({"id": c.id, "dense": np.round(dense, 2).tolist(), "selected": c.id == d.selected_candidate})
    ticks = {"X": [], "Y": []}
    if d.detection:
        for k in ("X", "Y"):
            t = d.detection.ticks.get(k)
            ticks[k] = [round(v, 3) for v in t.positions] if t else []
    return {
        "instance": "dz", "rev": d.rev, "edited": d.manually_edited,
        "image": {"url": url, "w": d.image.width, "h": d.image.height, "key": f"{d.image.sha256}:{scale:.4f}"},
        "points": [[p.id, round(p.px, 3), round(p.py, 3), int(p.include), int(p.modified)] for p in d.points],
        "anchors": {n: {"px": d.anchors[n].px, "py": d.anchors[n].py,
                        "label": "?" if d.anchors[n].value is None else f"{d.anchors[n].value:g}"} for n in ANCHOR_NAMES},
        "roi": list(d.roi) if d.roi else None, "plot_box": list(d.plot_box) if d.plot_box else None,
        "candidates": cands, "ticks": ticks, "calib": calib, "ocr": d.ocr_boxes(),
    }


AXIS_BADGE = {"CONFIABLE": ("success", "Reconocimiento confiable"), "REVISION": ("warning", "Pendiente de revisión"),
              "INSUFICIENTE": ("error", "Reconocimiento insuficiente")}


def _recognition_panel(d: DigitizationDraft) -> None:
    """Estado del reconocimiento de cada eje con sus evidencias y corrección individual de etiquetas."""
    st.markdown("**Reconocimiento automático de ejes** (OCR local + verificación geométrica)")
    if not d.axis_recognition:
        st.caption("Sin reconocimiento automático para este panel (no se detectaron ejes o el OCR no está "
                   "disponible). Use las referencias manuales.")
        return
    for axis in ("X", "Y"):
        rec = d.axis_recognition.get(axis)
        if rec is None:
            continue
        kind, label = AXIS_BADGE.get(rec.status, ("info", rec.status))
        conf = d.axis_confirmed.get(axis)
        head = (f"**Eje {axis}** · {label}" + (f" · escala {rec.scale}" if rec.scale else "")
                + (f" · {rec.n_inliers} etiquetas coherentes · RMS {rec.rms_px:.2f} px" if rec.rms_px is not None else "")
                + (" · ✔ confirmado" if conf else " · **sin confirmar**"))
        getattr(st, kind if not conf or kind != "warning" else "info")(head + ("\n\n" + "\n".join(
            f"- {r}" for r in rec.reasons[:4]) if rec.reasons else ""))
        if not conf and rec.status != "INSUFICIENTE":
            st.button(f"Confirmar eje {axis} tras revisarlo", key=f"dz_conf_{axis}", on_click=_on_axis_confirm,
                      args=(axis,), help="Declara que ha revisado los números reconocidos y su posición en la imagen.")
        if rec.labels:
            with st.expander(f"Etiquetas reconocidas en {axis} ({len(rec.labels)})", expanded=rec.status != "CONFIABLE"):
                rows, idx = [], []
                for i, l in enumerate(rec.labels):
                    rows.append({"texto OCR": l.text, "valor": l.effective_value, "coherente": bool(l.inlier),
                                 "residuo [px]": None if l.residual_px is None else round(l.residual_px, 2),
                                 "conf. OCR": round(l.ocr_conf, 2), "excluir": bool(l.excluded_by_user)})
                    idx.append(i)
                key = f"dz_lbl_{axis}_{d.rev}"
                st.data_editor(pd.DataFrame(rows), key=key, hide_index=True, width="stretch",
                               disabled=["texto OCR", "coherente", "residuo [px]", "conf. OCR"],
                               column_config={"valor": st.column_config.NumberColumn("valor", format="%.6g",
                                              help="Corrija el número si el OCR se equivocó.")},
                               on_change=_on_labels, args=(axis, key, idx))
                if rec.multiplier:
                    st.caption(f"Multiplicador detectado: «{rec.multiplier_text}» (×{rec.multiplier:g}); los valores de "
                               "las referencias ya lo incluyen.")
                if rec.title:
                    st.caption(f"Título del eje leído: «{rec.title.get('text')}»"
                               + (f" → unidad {rec.title['unit']}" if rec.title.get("unit") else " (sin unidad reconocible)"))


def _units_panel(d: DigitizationDraft) -> None:
    standalone = _ss().get("dz_mode") in ("standalone", "series")
    if standalone:
        c1, c2 = st.columns(2)
        c1.text_input("Unidad X", key="dz_xu_text", on_change=_on_free_units, placeholder="p. ej. A/cm²",
                      help="Texto libre. La escala la fijan las referencias; la unidad solo etiqueta los datos.")
        c2.text_input("Unidad Y", key="dz_yu_text", on_change=_on_free_units, placeholder="p. ej. V")
    else:
        c1, c2, c3 = st.columns(3)
        c1.selectbox("Unidad X", CURRENT_CHOICES, key="dz_cu", on_change=_on_units)
        c2.selectbox("Unidad V", list(units.VOLTAGE_UNITS), key="dz_vu", on_change=_on_units)
        c3.selectbox("Tensión", list(units.VOLTAGE_BASES), key="dz_vb", on_change=_on_units,
                     format_func=lambda b: "por celda" if b == "celda" else "de stack")
    if d.units_confirmed:
        st.caption(f"Unidades confirmadas ({d.units_source}).")
    else:
        st.warning("Unidades sin confirmar: no se detectaron con evidencia en los títulos de los ejes. Elíjalas o "
                   "confirme las mostradas; nunca se suponen.")
        st.button("Confirmar unidades", key="dz_units_ok", on_click=_on_units_confirm,
                  disabled=standalone and not (_ss().get("dz_xu_text") and _ss().get("dz_yu_text")))


def _saved_curves_panel(d: DigitizationDraft) -> None:
    st.markdown("**Curvas de este panel**")
    c1, c2 = st.columns([2, 1])
    c1.text_input("Nombre", key="dz_curve_name", placeholder=f"curva_{len(d.saved_curves) + 1}",
                  label_visibility="collapsed")
    c2.button("Guardar curva", key="dz_save_curve", on_click=_on_save_curve, disabled=not d.points, width="stretch",
              help="Guarda la traza actual con nombre para exportarla junto con otras curvas.")
    if d.saved_curves:
        names = [c["name"] for c in d.saved_curves]
        if _ss().get("dz_saved_pick") not in names:
            _ss()["dz_saved_pick"] = names[-1]
        st.selectbox("Guardadas", names, key="dz_saved_pick",
                     format_func=lambda n: next(f"{c['name']} · {len(c['points'])} pts · {c.get('candidate') or 'manual'}"
                                                for c in d.saved_curves if c["name"] == n))
        c1, c2 = st.columns(2)
        c1.button("Cargar en el lienzo", key="dz_load_curve", on_click=_on_curve_action, args=("load",), width="stretch")
        c2.button("Borrar", key="dz_del_curve", on_click=_on_curve_action, args=("delete",), width="stretch")


def _side_panel(d: DigitizationDraft) -> None:
    ss = _ss()
    det = d.detection
    if det and len(det.panels) > 1:
        st.selectbox("Panel", list(range(1, len(det.panels) + 1)), key="dz_panel", on_change=_on_panel,
                     help="La imagen contiene varios gráficos con ejes. Cada panel conserva su propia calibración, "
                          "curvas y correcciones al cambiar entre ellos.",
                     format_func=lambda k: f"Panel {k}" + (" · trabajado" if k in (ss.get("dz_panel_saved") or []) else ""))
    st.markdown("**Curva candidata**")
    labels = [lab for _, lab in _cand_labels(d)]
    if ss.get("dz_cand") not in labels:
        ss["dz_cand"] = NONE_CAND
    st.selectbox("Trazo", labels, key="dz_cand", on_change=_on_candidate, label_visibility="collapsed",
                 help="Cada candidato es un trazo de un color. No se mezclan puntos de candidatos distintos.")
    _saved_curves_panel(d)
    with st.expander("Parámetros de detección"):
        st.slider("Puntos a muestrear", 5, 200, key="dz_npts")
        st.slider("Tolerancia de color (RGB)", 10.0, 120.0, key="dz_tol")
        st.slider("Cobertura mínima α del trazo", 0.3, 0.95, key="dz_alpha")
        st.checkbox("Recortar terminaciones de línea (½ grosor)", key="dz_trim")
        st.checkbox("Excluir recuadros de leyenda", key="dz_legend")
        st.caption("Se aplican al pulsar «Identificar automáticamente».")
    _recognition_panel(d)
    with st.expander("Referencias de calibración (manual)", expanded=not all(d.axis_confirmed.values())):
        st.caption("Las referencias reconocidas automáticamente se pueden corregir aquí o en el lienzo. Escribir un "
                   "valor lo declara usted y confirma ese eje.")
        for n in ANCHOR_NAMES:
            a = d.anchors[n]
            c1, c2 = st.columns([1, 1])
            coord = "px" if n[0] == "X" else "py"
            src = {"auto-tick": "propuesta automática: tick detectado", "auto-grid": "propuesta automática: gridline",
                   "auto-marco": "propuesta automática: borde del marco (sin tick); confírmela",
                   "auto-ocr": "reconocida automáticamente (OCR + geometría)",
                   "usuario": "fijada por el usuario"}.get(a.source, a.source)
            c1.text_input(f"{n}: {coord}", key=f"dz_pos_{n}", on_change=_on_anchor, args=(n, "pos"),
                          help=f"Coordenada de imagen ({coord}, y hacia abajo). Origen: {src}.")
            c2.text_input(f"{n}: valor", key=f"dz_val_{n}", on_change=_on_anchor, args=(n, "val"),
                          placeholder="valor", help=f"Valor rotulado en esa posición. Origen: {src}. Admite coma decimal.")
        c1, c2 = st.columns(2)
        c1.selectbox("Escala X", AXIS_SCALES, key="dz_scale_X", on_change=_on_scale, args=("X",))
        c2.selectbox("Escala Y", AXIS_SCALES, key="dz_scale_Y", on_change=_on_scale, args=("Y",))
    _units_panel(d)
    cal, errs, warns = d.calibration()
    ready, why = d.physical_ready()
    if cal is None:
        st.warning("**Coordenadas en píxeles / calibración pendiente.**\n\n" + "\n".join(f"- {e}" for e in errs))
    elif not ready:
        st.info("Calibración propuesta, **pendiente de confirmación** antes de usar los valores físicos:\n\n"
                + "\n".join(f"- {w}" for w in why))
    else:
        st.success(f"Calibrado y confirmado: X {cal.x.scale}, Y {cal.y.scale}. Los valores físicos se recalculan "
                   "desde los píxeles en cada cambio.")


def _fmt_range(lo, hi, per_px=None) -> str:
    """Rango redondeado a la resolución (evita mostrar −4·10⁻⁵ cuando el borde está a 0,02 px del ancla)."""
    if lo is None or hi is None:
        return "—"
    step = per_px if per_px else abs(hi - lo) * 1e-4
    nd = max(0, min(10, int(math.ceil(-math.log10(step))) + 1)) if step and step > 0 else 4
    lo_r, hi_r = round(lo, nd), round(hi, nd)
    lo_r = 0.0 if lo_r == 0 else lo_r
    return f"{lo_r:.{nd}f} – {hi_r:.{nd}f}"


def _summary(d: DigitizationDraft) -> None:
    r = d.ranges()
    res = d.resolution()
    n_inc = sum(1 for p in d.points if p.include)
    if r["calibrated"]:
        ax, pts = r.get("axes"), r.get("points")
        dx = res["x_per_px"] if res else None
        dy = res["y_per_px"] if res else None
        rows = [
            {"": "Ejes (área de trazado)", f"X [{d.current_unit}]": _fmt_range(*ax["x"], dx) if ax else "—",
             f"Y [{d.voltage_unit}]": _fmt_range(*ax["y"], dy) if ax else "—", "n": ""},
            {"": "Puntos incluidos", f"X [{d.current_unit}]": _fmt_range(*pts["x"], dx) if pts else "—",
             f"Y [{d.voltage_unit}]": _fmt_range(*pts["y"], dy) if pts else "—", "n": f"{n_inc} / {len(d.points)}"},
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if res:
            st.caption(f"Resolución de la imagen: 1 px = {_fmt(res['x_per_px'], 3)} {d.current_unit} en X y "
                       f"{_fmt(res['y_per_px'], 3)} {d.voltage_unit} en Y. Incertidumbre de digitalización estimada "
                       f"(±0,5 px): ±{_fmt(res['sigma_dig_y'], 3)} {d.voltage_unit}. No incluye la incertidumbre de la "
                       "medición original.")
    else:
        pp = r.get("points_px")
        rows = [{"": "Puntos (píxeles; calibración pendiente)",
                 "x [px]": f"{pp['x'][0]:.1f} – {pp['x'][1]:.1f}" if pp else "—",
                 "y [px] (↓)": f"{pp['y'][0]:.1f} – {pp['y'][1]:.1f}" if pp else "—", "n": f"{n_inc} / {len(d.points)}"}]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("Sin calibración no se muestran amperios ni voltios: solo coordenadas en píxeles.")


def _table_tab(d: DigitizationDraft) -> None:
    df = d.table()
    key = f"dz_tbl_{d.rev}"
    cal = d.is_calibrated
    cfg = {
        "id": st.column_config.NumberColumn(disabled=True),
        "px": st.column_config.NumberColumn("px", format="%.2f"),
        "py": st.column_config.NumberColumn("py (↓)", format="%.2f"),
        d.x_label: st.column_config.NumberColumn(d.x_label, format="%.5g", disabled=not cal),
        d.y_label: st.column_config.NumberColumn(d.y_label, format="%.5g", disabled=not cal),
        "incluir": st.column_config.CheckboxColumn("incluir"),
        "método": st.column_config.TextColumn(disabled=True),
        "modificado": st.column_config.CheckboxColumn(disabled=True),
    }
    st.caption("Editar px/py o los valores físicos mueve el punto en la imagen (los físicos se convierten a píxeles "
               "con la calibración vigente). Desmarcar «incluir» excluye el punto del ajuste sin borrarlo de la "
               "trazabilidad. Puede añadir o borrar filas." + ("" if cal else " Columnas físicas bloqueadas: "
                                                                        "calibración pendiente."))
    st.data_editor(df, key=key, column_config=cfg, hide_index=True, num_rows="dynamic", width="stretch",
                   on_change=_on_table, args=(key, df["id"].tolist()), height=min(420, 38 + 35 * max(len(df), 3)))


def _preview_tab(d: DigitizationDraft) -> None:
    if not d.is_calibrated:
        st.info("La vista en unidades físicas aparece cuando las cuatro referencias tienen posición y valor. "
                "No se convierten píxeles a amperios o voltios sin calibración confirmada.")
        return
    xv, yv, pts = d.physical(include_only=False)
    inc = np.array([p.include for p in pts], bool)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=xv[inc], y=yv[inc], mode="lines+markers", name="incluidos",
                             marker=dict(color=["#ff8c00" if p.modified else "#119966" for p, i in zip(pts, inc) if i])))
    if (~inc).any():
        fig.add_trace(go.Scatter(x=xv[~inc], y=yv[~inc], mode="markers", name="excluidos",
                                 marker=dict(symbol="x", color="#888", size=9)))
    r = d.ranges().get("axes")
    fig.update_layout(height=360, margin=dict(l=10, r=10, t=30, b=10), title="Curva digitalizada (unidades físicas)",
                      xaxis_title=d.x_label, yaxis_title=d.y_label)
    if r:
        fig.update_xaxes(range=list(r["x"]), type="log" if d.scales["X"] == SCALE_LOG else "linear")
        fig.update_yaxes(range=list(r["y"]), type="log" if d.scales["Y"] == SCALE_LOG else "linear")
        if d.scales["X"] == SCALE_LOG:
            fig.update_xaxes(range=[math.log10(max(r["x"][0], 1e-300)), math.log10(r["x"][1])])
        if d.scales["Y"] == SCALE_LOG:
            fig.update_yaxes(range=[math.log10(max(r["y"][0], 1e-300)), math.log10(r["y"][1])])
    st.plotly_chart(fig, width="stretch", key="dz_preview_plot")
    st.caption("Naranja: puntos movidos o añadidos manualmente. Estos son datos digitalizados de una imagen; "
               "no constituyen una medición independiente.")


def _metadata_tab(d: DigitizationDraft):
    """Formulario de condiciones. Devuelve (meta, cond) o None si falta algo obligatorio."""
    ss = _ss()
    dev = ss.device
    geo = []
    if units.current_is_total(d.current_unit):
        geo.append(f"corriente total → requiere A_active (actual: {dev.active_area_cm2 or 'no declarada'})")
    if d.voltage_basis == "stack":
        geo.append(f"tensión de stack → requiere N_cells (actual: {dev.n_cells or 'no declarado'})")
    st.caption(f"Dispositivo: **{dev.name or '(sin nombre)'}** · N_cells = {dev.n_cells or '—'} · "
               f"A = {dev.active_area_cm2 or '—'} cm². Se edita en la sección «Dispositivo» de la pestaña (cierre "
               "este diálogo con ✕: el borrador se conserva)." + (" Atención: " + "; ".join(geo) if geo else ""))
    c1, c2, c3 = st.columns(3)
    cid = c1.text_input("Identificador de la curva *", key="dz_id")
    role = c2.selectbox("Rol", CURVE_ROLES, key="dz_role",
                        help="‘validación’: no se usa en el ajuste. Una curva digitalizada de la MISMA figura que las "
                             "de calibración no es una validación independiente.")
    c3.text_input("Calidad", value=QUALITY_DIGITIZED, disabled=True, key="dz_quality_fixed",
                  help="Fija: toda curva obtenida de una imagen es «digitalizado», aunque se haya corregido.")
    c1, c2, c3, c4 = st.columns(4)
    T = c1.number_input("Temperatura *", value=None, format="%.6g", key="dz_T")
    T_unit = c2.selectbox("Unidad T", units.TEMPERATURE_UNITS, key="dz_Tu")
    P = c3.number_input("Presión de cátodo *", value=None, format="%.6g", key="dz_P")
    P_unit = c4.selectbox("Unidad P", list(units.PRESSURE_UNITS), key="dz_Pu")
    c1, c2, c3, c4 = st.columns(4)
    P_ref = c1.selectbox("Referencia de presión", units.PRESSURE_REFERENCES, key="dz_Pref")
    amb = c2.number_input("P ambiente [kPa]", value=None, format="%.6g", key="dz_amb") if P_ref == "manométrica" else None
    ph2 = c3.number_input("p_H2 [atm abs] (opcional)", value=None, format="%.6g", key="dz_ph2")
    yo2 = c4.number_input("Fracción de O2 (opcional)", value=None, min_value=0.0, max_value=1.0, format="%.4g",
                          key="dz_yo2")
    c1, c2, c3 = st.columns(3)
    sig = c1.number_input("σ_V [mV/celda] (opcional)", value=None, min_value=0.0, format="%.4g", key="dz_sig",
                          help="No se asume ningún valor por defecto. Puede adoptar la estimación de resolución.")
    corig = c2.selectbox("Origen de las condiciones", DEVICE_ORIGINS, key="dz_corig")
    src = c3.text_input("Fuente (artículo, figura)", key="dz_src", placeholder="Autor, año, figura…")
    prov = st.text_input("Procedencia adicional", key="dz_prov",
                         placeholder="Se registra automáticamente «Digitalización asistida de <archivo>»")
    res = d.resolution()
    if res:
        f = units.VOLTAGE_UNITS[d.voltage_unit]
        est = res["sigma_dig_y"] * f
        basis = ""
        if d.voltage_basis == "stack":
            if dev.n_cells:
                est /= dev.n_cells
                basis = f" (÷ N_cells = {dev.n_cells})"
            else:
                est = None
        if est:
            text = (f"Estimada por resolución de la imagen: ±0,5 px × {_fmt(res['y_per_px'], 3)} {d.voltage_unit}/px"
                    f"{basis} = {1000 * est:.3g} mV/celda (no es la incertidumbre de la medición original)")
            st.button(f"Usar estimación de digitalización como σ_V ({1000 * est:.3g} mV/celda)", key="dz_use_sig",
                      on_click=_on_use_sigma, args=(1000 * est, text))
    if T is None or P is None or (P_ref == "manométrica" and amb is None) or not str(cid).strip():
        st.info("Complete identificador, temperatura y presión (y la presión ambiente si es manométrica).")
        return None
    sigma_origin = ""
    if sig:
        sigma_origin = (ss.get("dz_sig_origin") if ss.get("dz_sig_origin")
                        and abs(float(sig) - float(ss.get("dz_sig_value_at_origin", -1))) < 1e-9
                        else "Declarada por el usuario")
    meta = CurveMetadata(curve_id=str(cid).strip(), role=role, source=src, provenance=prov, quality=QUALITY_DIGITIZED,
                         sigma_V=None if not sig else sig / 1000.0, sigma_origin=sigma_origin, conditions_origin=corig)
    yo2 = None if yo2 is None or (isinstance(yo2, float) and math.isnan(yo2)) else yo2
    cond = ConditionInput(T, T_unit, P, P_unit, P_ref, amb, ph2, yo2 or None)
    return meta, cond


def _audit_tab(d: DigitizationDraft) -> None:
    st.caption(f"{ALGORITHM_ID} v{DIGITIZER_VERSION} · imagen SHA-256 `{d.image.sha256}` · "
               f"{d.image.width}×{d.image.height} px · método: {d.extraction_method}")
    if d.image.transformations:
        st.markdown("Decodificación: " + "; ".join(d.image.transformations))
    ev = pd.DataFrame([{"hora (UTC)": e["timestamp_utc"][11:23], "acción": e["action"]} for e in d.audit[-60:]][::-1])
    st.dataframe(ev, hide_index=True, width="stretch", height=220)
    st.download_button("Descargar JSON de digitalización (auditoría completa)", audit_json(d).encode("utf-8"),
                       file_name=f"{Path(d.image.filename).stem}__digitalizacion.json", mime="application/json",
                       key="dz_dl_json")


SCOPES = {"curva_actual": "Curva actual (traza visible)", "curva_guardada": "Una curva guardada",
          "panel": "Todas las curvas guardadas del panel", "imagen": "Todas las curvas guardadas de la imagen"}


def _export_tab(d: DigitizationDraft) -> None:
    """Exportación X–Y autónoma: no requiere dispositivo, calibración electroquímica ni perfil."""
    from digitizer.export import CURRENT, FORMATS, ExportError, collect, entries_for
    ss = _ss()
    st.caption("Convierte la figura en una tabla numérica sin pasar por el Motor 1. Los cinco formatos contienen "
               "exactamente los mismos valores; las unidades y referencias son las confirmadas en cada panel.")
    c1, c2 = st.columns([2, 1.4])
    scope = c1.radio("Alcance", list(SCOPES), format_func=SCOPES.get, key="dz_exp_scope", horizontal=True)
    name = None
    if scope == "curva_guardada":
        names = [c["name"] for c in d.saved_curves]
        if not names:
            st.info("Todavía no hay curvas guardadas en este panel: use «Guardar curva».")
            return
        name = c2.selectbox("Curva", names, key="dz_exp_curve")
    pixels_only = st.checkbox("Exportar solo coordenadas en píxeles (SIN CALIBRAR)", key="dz_exp_px",
                              help="Para figuras cuyos ejes no pueden calibrarse. No incluye valores ni unidades físicas.")
    panels = list((ss.get("dz_panels") or {int(d.panel_index or 0): d}).values())
    try:
        entries = entries_for(panels, {"curva_actual": "curva", "curva_guardada": "curva"}.get(scope, scope), d,
                              CURRENT if scope == "curva_actual" else name)
        bundle = collect(entries, pixels_only=pixels_only)
    except ExportError as exc:
        st.warning(str(exc))
        return
    df = pd.DataFrame(bundle.rows)
    show = df.rename(columns={"curve_id": "curva", "point": "punto", "origin": "origen", "x_unit": "unidad X",
                              "y_unit": "unidad Y"})
    st.dataframe(show, hide_index=True, width="stretch", height=min(360, 38 + 35 * len(show)))
    with st.expander("Copiar valores (texto tabulado)"):
        st.code(show.to_csv(sep="\t", index=False), language=None)
    sig = (scope, name, pixels_only, tuple(p.rev for p in panels))
    if ss.get("dz_export") and ss["dz_export"].get("sig") != sig:
        ss["dz_export"] = None
    if st.button("Preparar archivos de exportación", key="dz_exp_prep", type="primary"):
        with st.spinner("Generando CSV, XLSX, JSON, PNG y ZIP…"):
            ss["dz_export"] = {"sig": sig, "files": {k: f(bundle) for k, (_, _, f) in FORMATS.items()}}
    if ss.get("dz_export"):
        stem = Path(d.image.filename).stem
        cols = st.columns(len(FORMATS))
        for col, (k, (fname, mime, _)) in zip(cols, FORMATS.items()):
            col.download_button(k, ss["dz_export"]["files"][k], file_name=f"{stem}__{fname}", mime=mime,
                                key=f"dz_dl_{k}", width="stretch")
        st.caption(f"{len(bundle.rows)} puntos · {len({r['curve_id'] for r in bundle.rows})} curva(s) · "
                   + ("SIN CALIBRAR (solo píxeles)" if pixels_only else "valores físicos confirmados"))


def _confirm(d: DigitizationDraft, form) -> None:
    ss = _ss()
    if form is None:
        st.error("Complete las condiciones de medición (pestaña «Condiciones y metadatos»).")
        return
    meta, cond = form
    res = build_digitized_curve(d, meta, cond, ss.device, list(ss.curves), dict(ss.originals))
    if not res.ok:
        state.show_issues(res.issues)
        ss["dz_last_issues"] = [str(i) for i in res.issues if i.level == "error"]
        return
    # Único punto de mutación del conjunto: una llamada a set_dataset con curvas existentes + nueva.
    originals = dict(ss.originals)
    originals.update(res.artifacts)
    state.set_dataset(list(ss.curves) + [res.curve], ss.device, originals,
                      ss.dataset_label or "Datos importados por el usuario")
    d.confirmed_curve_ids.append(res.curve.curve_id)
    d._log("curva_confirmada", {"curve_id": res.curve.curve_id, "normalized_sha256": res.curve.normalized_sha256,
                                "n_points": res.curve.n_points})
    d.rev_at_confirm = d.rev
    warn = [str(i) for i in res.issues if i.level != "error"]
    ss["dz_flash"] = ("success", f"Curva **{res.curve.curve_id}** añadida (calidad «digitalizado», "
                                 f"{res.curve.n_points} puntos, SHA-256 normalizado "
                                 f"{res.curve.normalized_sha256[:12]}…). Los resultados previos se invalidaron. "
                                 + (f"{len(warn)} aviso(s) registrados en la curva." if warn else ""))
    ss["dz_open"] = False
    ss["dz_next_id"] = f"{meta.curve_id}_2"   # se aplica antes de crear el widget en la próxima ejecución
    st.rerun()


# ---------------------------------------------------------------------------
@st.dialog("Digitalizar curva desde imagen", width="large", on_dismiss=_on_dismiss)
def _dialog() -> None:
    render_body("motor1")


def render_body(mode: str = "motor1") -> None:
    """Cuerpo del digitalizador. ``motor1``: confirmar curva hacia el Motor 1. ``standalone``: exportar X–Y."""
    _ss()["dz_mode"] = mode
    if "dz_next_id" in _ss():
        _ss()["dz_id"] = _ss().pop("dz_next_id")
    d = _draft()
    if d is None:
        st.markdown("Suba la imagen de un gráfico. Al cargarla se detectan **localmente** los paneles, los ejes, "
                    "los números de las escalas (OCR verificado geométricamente), las unidades y los trazos. Lo "
                    "que no se reconozca con fiabilidad queda pendiente de su confirmación"
                    + (". Nada se añade al conjunto hasta que pulse «Confirmar y añadir curva»." if mode == "motor1"
                       else "; después puede exportar los datos X–Y sin crear ningún dispositivo."))
        _upload_section(None)
        if _draft() is not None:
            # La subida se procesó en esta ejecución: se reejecuta para que el diálogo tenga desde el primer
            # momento la MISMA estructura que tendrá después. Si cambiara, el lienzo se remontaría tras la
            # primera edición y se perderían zoom, desplazamiento y foco (detectado en navegador real).
            st.rerun()
        if mode == "motor1" and st.button("Cancelar", key="dz_cancel_empty"):
            _cancel()
            st.rerun()
        return

    b = st.columns([1.45, 1.35, 0.9, 0.9, 1.3, 1.3])
    with b[5].popover("Cambiar imagen"):
        _upload_section(d)
    d = _draft()
    form_ok = all(_ss().get(k) is not None for k in ("dz_T", "dz_P")) and str(_ss().get("dz_id", "")).strip()
    status = d.status(metadata_ok=bool(form_ok))
    kind, text = STATUS_TEXT.get(status, ("info", status))
    if mode == "standalone":
        ready, _ = d.physical_ready()
        status, kind, text = (("LISTO_PARA_EXPORTAR", "success", "Calibración confirmada: revise el trazo, guarde las "
                               "curvas y expórtelas en «Exportar datos».") if ready else
                              ("REVISION", "warning", "Revise y confirme los ejes y las unidades antes de exportar "
                               "valores físicos (o exporte solo píxeles)."))
    getattr(st, kind)(f"**{status}** · {text}")
    st.caption(f"**{d.image.filename}** · {d.image.width}×{d.image.height} px · {d.image.format} · SHA-256 "
               f"`{d.image.sha256[:16]}…` · método: {d.extraction_method}"
               + (" · ✎ **trazo intervenido manualmente**" if d.manually_edited else ""))
    if d.last_error:
        st.error(d.last_error)
    msg = _ss().pop("dz_loaded_msg", None)
    if msg:
        st.toast(msg)
    if _ss().get("dz_confirm_redetect"):
        st.warning("Reidentificar reemplaza el trazo actual (las ediciones manuales se pierden del trazo, aunque "
                   "quedan en el historial y se pueden deshacer). Las anclas que usted editó se conservan.")
        c1, c2 = st.columns(2)
        c1.button("Sí, reidentificar", key="dz_redetect_yes", on_click=_on_action, args=("redetect",), type="primary")
        c2.button("No", key="dz_redetect_no", on_click=lambda: _ss().__setitem__("dz_confirm_redetect", False))
    if d.manually_edited:
        b[0].button("Identificar automáticamente", key="dz_redetect",
                    on_click=lambda: _ss().__setitem__("dz_confirm_redetect", True),
                    help="Reintenta la extracción con el ROI, panel y parámetros actuales (pide confirmación).")
    else:
        b[0].button("Identificar automáticamente", key="dz_redetect", on_click=_on_action, args=("redetect",),
                    help="Reintenta la extracción con el ROI, panel y parámetros actuales.")
    b[1].button("Restablecer ROI", key="dz_reset_roi", on_click=_on_action, args=("reset_roi",),
                help="Vuelve a detectar sobre la imagen completa (ROI automático).")
    b[2].button("Deshacer", key="dz_undo", on_click=_on_action, args=("undo",), disabled=not d.undo_stack)
    b[3].button("Rehacer", key="dz_redo", on_click=_on_action, args=("redo",), disabled=not d.redo_stack)
    b[4].button("Trazado manual", key="dz_clear", on_click=_on_action, args=("clear",), disabled=not d.points,
                help="Vacía el trazo para trazarlo a mano con «＋ Añadir» (reversible).")

    left, right = st.columns([2.55, 1.2], gap="medium")
    with left:
        _canvas_component()(key="dz_canvas", data=_canvas_data(d), on_edit_change=_on_canvas_edit,
                            height="content")
        st.caption("Rueda: zoom · arrastrar el fondo: desplazar · arrastrar un punto o un ancla: moverlo · "
                   "Supr: borrar el punto seleccionado · Ctrl+Z / Ctrl+Y. Verde: automático; naranja: manual; "
                   "gris tachado: excluido; magenta/azul: referencias X/Y; naranja discontinuo: ROI.")
    with right:
        _side_panel(d)

    _summary(d)
    warns = [w for w in d.quality_warnings() if "calibración pendiente" not in w]
    if warns:
        with st.expander(f"Avisos de digitalización ({len(warns)})", expanded=len(warns) <= 3):
            st.warning("\n".join(f"- {w}" for w in warns))

    if mode == "series":
        ready, why = d.physical_ready()
        pts = [p for p in d.sorted_points() if p.include]
        c1, c2 = st.columns([3, 1.4])
        c1.caption("Curva tiempo–magnitud para el Motor 2: el eje X debe ser el tiempo y el eje Y la magnitud del "
                   "perfil (potencia o caudal de H₂). Las unidades se confirman al usarla en la bancada."
                   + ("" if ready else " Pendiente: " + " ".join(why)))
        if c2.button("Usar esta curva como perfil temporal", type="primary", key="dz_use_series",
                     disabled=not (ready and len(pts) >= 2), width="stretch"):
            cal = d.calibration()[0]
            x, y = cal.to_physical([p.px for p in pts], [p.py for p in pts])
            _ss()["dz_series_result"] = {"x": [float(v) for v in x], "y": [float(v) for v in y],
                                         "x_unit": d.x_unit_text, "y_unit": d.y_unit_text, "image": d.image.filename,
                                         "sha256": d.image.sha256, "n": len(pts),
                                         "axis_status": {k: v.status for k, v in d.axis_recognition.items()},
                                         "axis_confirmed": dict(d.axis_confirmed)}
            _ss()["dz_open"] = False
            st.rerun()
    if mode in ("standalone", "series"):
        t1, t2, t3, t4 = st.tabs(["Exportar datos", "Tabla de puntos", "Vista previa física", "Auditoría"])
        with t1:
            _export_tab(d)
        with t2:
            _table_tab(d)
        with t3:
            _preview_tab(d)
        with t4:
            _audit_tab(d)
        st.divider()
        if st.button("Descartar esta digitalización", key="dz_cancel"):
            _cancel()
            st.rerun()
        return
    t1, t2, t3, t4, t5 = st.tabs(["Tabla de puntos", "Vista previa física", "Condiciones y metadatos",
                                  "Exportar datos", "Auditoría"])
    with t1:
        _table_tab(d)
    with t2:
        _preview_tab(d)
    with t3:
        form = _metadata_tab(d)
    with t4:
        _export_tab(d)
    with t5:
        _audit_tab(d)

    st.divider()
    c1, c2, c3 = st.columns([1.4, 1.2, 1])
    ready, _why = d.physical_ready()
    can = d.is_calibrated and ready and form is not None and any(p.include for p in d.points)
    if c1.button("Confirmar y añadir curva", type="primary", key="dz_confirm", disabled=not can, width="stretch"):
        _confirm(d, form)
    c2.download_button("Descargar CSV de la digitalización", d.to_csv().encode("utf-8"),
                       file_name=f"{Path(d.image.filename).stem}__digitalizacion.csv", mime="text/csv",
                       key="dz_dl_csv", width="stretch")
    if c3.button("Cancelar", key="dz_cancel", width="stretch",
                 help="Descarta el borrador y cierra. El conjunto de curvas y los resultados no cambian."):
        _cancel()
        st.rerun()
    if not can:
        missing = []
        if not d.is_calibrated:
            missing.append("calibración (cuatro referencias con valor)")
        elif not ready:
            missing.append("confirmar ejes/unidades")
        if form is None:
            missing.append("condiciones de medición")
        if not any(p.include for p in d.points):
            missing.append("puntos incluidos")
        st.caption("Confirmar bloqueado: falta " + ", ".join(missing) + ".")


@st.dialog("Digitalizar perfil temporal desde imagen", width="large", on_dismiss=_on_dismiss)
def _series_dialog() -> None:
    render_body("series")


def render_series_entry(context: str) -> dict | None:
    """Entrada del Motor 2: digitaliza una curva tiempo–magnitud. Devuelve el resultado una sola vez."""
    use_context(context)
    ss = _ss()
    d = _draft()
    if d is not None:
        st.caption(f"Digitalización en curso: **{d.image.filename}** ({len(d.points)} puntos). Al abrir se restaura.")
    st.button("Abrir digitalizador", type="primary", key=f"dz_open_series_{context}", on_click=_open)
    if ss.get("dz_open"):
        _series_dialog()
    return ss.pop("dz_series_result", None)


def render_entry() -> None:
    """Contenido de la opción «Imagen de una curva» en la pestaña de importación."""
    ss = _ss()
    flash = ss.pop("dz_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])
    st.markdown("Digitalice una curva de polarización desde una imagen (PNG, JPEG o WebP) en un editor visual: "
                "detección local del trazo, de los ejes y de los **números de las escalas** (OCR verificado "
                "geométricamente), corrección de etiquetas y puntos con zoom, tabla sincronizada y vista previa. La "
                "curva confirmada entra en el mismo flujo que un CSV, con calidad **«digitalizado»**.")
    d = _draft()
    if d is not None:
        st.caption(f"Borrador en curso: **{d.image.filename}** ({len(d.points)} puntos"
                   + (f"; ya añadida(s): {', '.join(d.confirmed_curve_ids)}" if d.confirmed_curve_ids else "")
                   + "). Al abrir el digitalizador se restaura.")
    st.button("Abrir digitalizador", type="primary", key="dz_open_btn", on_click=_open)
    if ss.get("dz_open"):
        _dialog()
