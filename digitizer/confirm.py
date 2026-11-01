"""Confirmación: borrador → PolarizationCurve mediante el pipeline EXISTENTE.

No hay ruta matemática alternativa: se llama a ``identification.datasets.build_curve``
con los puntos incluidos (en las unidades declaradas del gráfico) y después a
``check_curve_set`` sobre el conjunto combinado. Esta función es pura: no toca
``st.session_state``; el llamador decide si aplica el resultado (una sola vez).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

from identification.datasets import (
    ConditionInput, PolarizationCurve, ValidationIssue, build_curve, check_curve_set,
)
from pemfc_core.schemas import QUALITY_DIGITIZED, CurveMetadata, DeviceInfo

from . import ALGORITHM_ID, DIGITIZER_VERSION
from .calibration import ANCHOR_NAMES
from .draft import DigitizationDraft, audit_json


@dataclass
class ConfirmationResult:
    curve: PolarizationCurve | None
    issues: list[ValidationIssue]
    artifacts: dict[str, bytes] = field(default_factory=dict)   # nombre → bytes para `originals`

    @property
    def ok(self) -> bool:
        return self.curve is not None and not any(i.level == "error" for i in self.issues)


def _unique_name(name: str, data: bytes, existing: dict[str, bytes]) -> str:
    """Evita sobrescribir silenciosamente originales con el mismo nombre y distinto contenido."""
    if name not in existing or existing[name] == data:
        return name
    stem, suf = Path(name).stem, Path(name).suffix
    import hashlib
    h = hashlib.sha256(data).hexdigest()[:8]
    cand = f"{stem}__{h}{suf}"
    k = 2
    while cand in existing and existing[cand] != data:
        cand = f"{stem}__{h}_{k}{suf}"
        k += 1
    return cand


def _safe_id(cid: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in cid)[:80] or "curva"


def overlay_png(draft: DigitizationDraft, max_side: int = 1600) -> bytes:
    """Imagen original con el trazo, puntos y anclas superpuestos (evidencia auditable)."""
    img = Image.fromarray(draft.image.rgb).convert("RGB")
    s = min(1.0, max_side / max(img.size))
    if s < 1:
        img = img.resize((round(img.width * s), round(img.height * s)), Image.Resampling.LANCZOS)
    dr = ImageDraw.Draw(img)
    pts = draft.sorted_points()
    inc = [(p.px * s, p.py * s) for p in pts if p.include]
    if len(inc) >= 2:
        dr.line(inc, fill=(0, 200, 120), width=2)
    for p in pts:
        x, y, r = p.px * s, p.py * s, 4
        if not p.include:
            dr.ellipse([x - r, y - r, x + r, y + r], outline=(130, 130, 130), width=2)
        else:
            col = (255, 140, 0) if p.modified else (0, 170, 110)
            dr.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(0, 0, 0))
    for n in ANCHOR_NAMES:
        a = draft.anchors[n]
        if a.px is None or a.py is None:
            continue
        x, y = a.px * s, a.py * s
        col = (200, 0, 160) if n[0] == "X" else (0, 90, 220)
        if n[0] == "X":
            dr.line([(x, 0), (x, img.height)], fill=col, width=1)
        else:
            dr.line([(0, y), (img.width, y)], fill=col, width=1)
        dr.rectangle([x - 5, y - 5, x + 5, y + 5], outline=col, width=2)
        dr.text((x + 7, y - 14), f"{n}={a.value if a.value is not None else '?'}", fill=col)
    if draft.roi:
        x0, y0, x1, y1 = (v * s for v in draft.roi)
        dr.rectangle([x0, y0, x1, y1], outline=(240, 160, 0), width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_digitized_curve(draft: DigitizationDraft, meta: CurveMetadata, condition_input: ConditionInput,
                          device: DeviceInfo, existing_curves: list[PolarizationCurve],
                          existing_originals: dict[str, bytes]) -> ConfirmationResult:
    issues: list[ValidationIssue] = []
    cid = (meta.curve_id or "").strip()
    E = lambda m: issues.append(ValidationIssue("error", cid, m))  # noqa: E731

    if meta.quality != QUALITY_DIGITIZED:
        E("Una curva obtenida de una imagen debe tener calidad «digitalizado».")
    for e in device.validate():
        issues.append(ValidationIssue("error", "", e))
    if cid in {c.curve_id for c in existing_curves}:
        E(f"Ya existe una curva con id {cid!r} en el conjunto actual: elija otro identificador "
          "(no se sobrescribe).")
    cal, cal_errors, cal_warns = draft.calibration()
    for m in cal_errors:
        E(f"Calibración: {m}")
    ready, why = draft.physical_ready()
    if cal is not None and not ready:
        for m in why:
            E(f"Confirmación pendiente: {m}")
    if cal is None:
        return ConfirmationResult(None, issues)
    try:
        xv, yv, pts = draft.physical(include_only=True)
    except ValueError as exc:
        E(str(exc))
        return ConfirmationResult(None, issues)
    if not pts:
        E("No hay puntos incluidos: trace o incluya puntos antes de confirmar.")
        return ConfirmationResult(None, issues)
    outside = [p.id for p in pts if not (0 <= p.px <= draft.image.width and 0 <= p.py <= draft.image.height)]
    if outside:
        E(f"Puntos fuera de la imagen: {outside[:10]}.")
    if not (np.isfinite(xv).all() and np.isfinite(yv).all()):
        E("La calibración produce valores no finitos para algún punto.")
    for w in draft.quality_warnings():
        if "calibración pendiente" not in w:
            issues.append(ValidationIssue("aviso", cid, f"Digitalización: {w}"))
    if any(i.level == "error" for i in issues):
        return ConfirmationResult(None, issues)

    img = draft.image
    img_name = _unique_name(img.filename, img.original_bytes, existing_originals)
    base = f"{Path(img_name).stem}__{_safe_id(cid)}"
    json_name = _unique_name(f"{base}__digitalizacion.json", b"", existing_originals)
    csv_name = _unique_name(f"{base}__digitalizacion.csv", b"", existing_originals)
    png_name = _unique_name(f"{base}__overlay.png", b"", existing_originals)

    anchors = {n: draft.anchors[n].to_dict() for n in ANCHOR_NAMES}
    counts = draft.edit_counts()
    log = [
        f"Imagen original {img.filename} ({img.width}×{img.height} px, {img.format}, SHA-256 {img.sha256[:16]}…).",
        *[f"Decodificación: {t}" for t in img.transformations],
        f"Extracción {draft.extraction_method} con {ALGORITHM_ID} v{DIGITIZER_VERSION}"
        + (f"; candidato {draft.selected_candidate}" if draft.selected_candidate else "")
        + (f"; ROI px {tuple(round(v, 1) for v in draft.roi)}" if draft.roi else "") + ".",
        f"Ediciones manuales: {counts['movidos']} movido(s), {counts['añadidos']} añadido(s), "
        f"{counts['borrados']} borrado(s); {counts['excluidos']} excluido(s) del ajuste.",
        "Calibración X ({sx}): px {p1:.3f}→{v1:g}, px {p2:.3f}→{v2:g} [{u}].".format(
            sx=cal.x.scale, p1=cal.x.p1, v1=cal.x.v1, p2=cal.x.p2, v2=cal.x.v2, u=draft.current_unit),
        "Calibración Y ({sy}): py {p1:.3f}→{v1:g}, py {p2:.3f}→{v2:g} [{u}] (py crece hacia abajo; sin "
        "inversión adicional).".format(sy=cal.y.scale, p1=cal.y.p1, v1=cal.y.v1, p2=cal.y.p2, v2=cal.y.v2,
                                       u=f"{draft.voltage_unit} {draft.voltage_basis}"),
        f"{len(pts)} punto(s) píxel→físico; los píxeles se conservan como fuente geométrica "
        f"(JSON {json_name}).",
    ]
    if counts["excluidos"]:
        log.append("Excluidos por el usuario (ids): "
                   + ", ".join(str(p.id) for p in draft.sorted_points() if not p.include) + ".")
    mapping = {
        "source_kind": "imagen_digitalizada", "current_unit": draft.current_unit,
        "voltage_unit": draft.voltage_unit, "voltage_basis": draft.voltage_basis,
        "axis_scales": dict(draft.scales), "anchors_px": anchors, "calibration": cal.to_dict(),
        "axis_recognition": {k: {"status": v.status, "scale": v.scale, "n_inliers": v.n_inliers,
                                 "rms_px": v.rms_px, "multiplier": v.multiplier, "engine": v.engine,
                                 "labels": [(l.text, l.effective_value, l.inlier) for l in v.labels]}
                             for k, v in draft.axis_recognition.items()},
        "axis_confirmed": dict(draft.axis_confirmed), "units_source": draft.units_source,
        "image_file": img_name, "image_sha256": img.sha256, "image_size_px": [img.width, img.height],
        "digitizer": {"algorithm": ALGORITHM_ID, "version": DIGITIZER_VERSION,
                      "method": draft.extraction_method, "selected_trace": draft.selected_candidate,
                      "roi_px": list(draft.roi) if draft.roi else None,
                      "plot_box_px": list(draft.plot_box) if draft.plot_box else None,
                      "params": draft.params.to_dict()},
        "digitization_resolution": draft.resolution(),
        "digitization_files": {"audit_json": json_name, "points_csv": csv_name, "overlay_png": png_name},
    }
    raw = pd.DataFrame({
        "point_id": [p.id for p in pts], "px": [p.px for p in pts], "py": [p.py for p in pts],
        f"corriente [{draft.current_unit}]": xv, f"tensión [{draft.voltage_unit} {draft.voltage_basis}]": yv,
        "método": [p.method for p in pts], "ediciones": [p.edits for p in pts]})
    if not meta.provenance:
        meta.provenance = f"Digitalización asistida de {img_name}; confirmado por el usuario"
    elif "Digitalización asistida" not in meta.provenance:
        meta.provenance = f"Digitalización asistida de {img_name}; confirmado por el usuario. {meta.provenance}"
    note = (f"Curva digitalizada (SHA-256 imagen {img.sha256[:12]}…). Calidad «digitalizado»: no constituye "
            "validación experimental independiente.")
    meta.notes = f"{meta.notes} {note}".strip() if meta.notes else note

    curve, cissues = build_curve(
        xv, yv, meta=meta, condition_input=condition_input, device=device, current_unit=draft.current_unit,
        voltage_unit=draft.voltage_unit, voltage_basis=draft.voltage_basis, raw=raw, source_file=img_name,
        source_sha256=img.sha256, mapping=mapping, transformations=log)
    issues += cissues
    if curve is None or any(i.level == "error" for i in issues):
        return ConfirmationResult(None, issues)
    set_errors = [i for i in check_curve_set(list(existing_curves) + [curve]) if i.level == "error"]
    if set_errors:
        return ConfirmationResult(None, issues + set_errors)
    artifacts = {img_name: img.original_bytes,
                 json_name: audit_json(draft).encode("utf-8"),
                 csv_name: draft.to_csv().encode("utf-8"),
                 png_name: overlay_png(draft)}
    return ConfirmationResult(curve, issues, artifacts)
