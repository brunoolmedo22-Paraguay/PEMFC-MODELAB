"""Pruebas deterministas del digitalizador (sin Streamlit).

Errores de DIGITALIZACIÓN (imagen → datos) se miden contra los truth CSV sintéticos del
handoff; no se confunden con errores del ajuste electroquímico.
"""
import csv
import io
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from digitizer.calibration import SCALE_LOG, Anchor, Calibration, build_axis
from digitizer.confirm import build_digitized_curve
from digitizer.detection import DetectionParams, detect
from digitizer.draft import ST_NEEDS_CAL, ST_REVIEW, DigitizationDraft
from digitizer.imageio import MAX_BYTES, ImageLoadError, load_image, safe_filename
from identification.datasets import ConditionInput, check_curve_set
from pemfc_core.schemas import CurveMetadata, DeviceInfo

from digitizer_synth import render

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "tests" / "fixtures" / "digitizer"
FIXTURES = ["01_curva_simple", "02_dos_curvas", "03_marcadores_y_ruido"]
COND = ConditionInput(343.15, "K", 1.5, "atm")


def _img(name):
    return load_image((FX / f"{name}.png").read_bytes(), f"{name}.png")


def _truth(name, curve):
    with open(FX / f"{name}_truth.csv", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["curve_id"] == curve]
    return np.array([[float(r["current_density_A_cm2"]), float(r["voltage_V"])] for r in rows])


def _evaluate(truth, got):
    """Misma métrica que handoff/verificacion/evaluar_extraccion.py (RMSE en la intersección X)."""
    got = got[np.argsort(got[:, 0])]
    lo, hi = max(truth[0, 0], got[0, 0]), min(truth[-1, 0], got[-1, 0])
    ins = truth[(truth[:, 0] >= lo) & (truth[:, 0] <= hi)]
    res = np.interp(ins[:, 0], got[:, 0], got[:, 1]) - ins[:, 1]
    return float(np.sqrt(np.mean(res ** 2))), (hi - lo) / (truth[-1, 0] - truth[0, 0])


def _calibrate(d, values=None, manifest=None):
    if manifest:
        a = manifest["reference_anchors_px"]
        d.set_anchor_position("X1", a["x1"]["px"]); d.set_anchor_position("X2", a["x2"]["px"])
        d.set_anchor_position("Y1", a["y1"]["py"]); d.set_anchor_position("Y2", a["y2"]["py"])
        values = {"X1": a["x1"]["value"], "X2": a["x2"]["value"], "Y1": a["y1"]["value"], "Y2": a["y2"]["value"]}
    for n, v in values.items():
        d.set_anchor_value(n, v)


# ---------------------------------------------------------------------------- calibración
def test_linear_transform_with_y_inversion_min_max_mid():
    cx, e1, _ = build_axis(Anchor("X1", px=150, value=0.0), Anchor("X2", px=1080, value=1.5))
    cy, e2, _ = build_axis(Anchor("Y1", py=667.5, value=0.4), Anchor("Y2", py=90, value=1.1))
    assert not e1 and not e2
    cal = Calibration(cx, cy)
    x, y = cal.to_physical([150, 615, 1080], [667.5, 378.75, 90])
    assert np.allclose(x, [0.0, 0.75, 1.5]) and np.allclose(y, [0.4, 0.75, 1.1])
    # y decrece al bajar en la imagen (sin doble inversión)
    assert cal.y.to_value(600) < cal.y.to_value(100)
    px, py = cal.to_pixels([0.3, 0.9], [0.5, 1.0])
    assert np.allclose(cal.to_physical(px, py), ([0.3, 0.9], [0.5, 1.0]))


def test_anchors_at_different_heights_project_on_own_axis():
    cx, _, _ = build_axis(Anchor("X1", px=100, py=500, value=0), Anchor("X2", px=300, py=20, value=2))
    assert cx.to_value(200) == pytest.approx(1.0)


@pytest.mark.parametrize("a1,a2,msg", [
    (Anchor("X1", px=200, value=0), Anchor("X2", px=200.4, value=1), "misma posición"),
    (Anchor("X1", px=100, value=1), Anchor("X2", px=300, value=1), "mismo valor"),
    (Anchor("X1", px=100, value=None), Anchor("X2", px=300, value=1), "falta el valor"),
    (Anchor("X1", px=None, value=0), Anchor("X2", px=300, value=1), "falta la posición"),
    (Anchor("X1", px=100, value=float("nan")), Anchor("X2", px=300, value=1), "finito"),
    (Anchor("X1", px=100, value=float("inf")), Anchor("X2", px=300, value=1), "finito"),
])
def test_degenerate_or_incomplete_anchors_are_errors(a1, a2, msg):
    cal, errors, _ = build_axis(a1, a2)
    assert cal is None and any(msg in e for e in errors)


def test_log_scale_roundtrip_and_positive_values_required():
    c, e, _ = build_axis(Anchor("X1", px=100, value=0.01), Anchor("X2", px=500, value=10), SCALE_LOG)
    assert not e
    assert c.to_value(300) == pytest.approx(math.sqrt(0.01 * 10))       # punto medio geométrico
    assert c.to_pixel(c.to_value(123.4)) == pytest.approx(123.4)
    _, e2, _ = build_axis(Anchor("X1", px=100, value=0), Anchor("X2", px=500, value=10), SCALE_LOG)
    assert any("positivos" in m for m in e2)


def test_swapped_y_anchors_warn():
    _, _, w = build_axis(Anchor("Y1", py=100, value=0.4), Anchor("Y2", py=600, value=1.1))
    assert any("ABAJO" in m for m in w)


# ---------------------------------------------------------------------------- imágenes
def test_image_rejections():
    with pytest.raises(ImageLoadError, match="vacío"):
        load_image(b"", "a.png")
    with pytest.raises(ImageLoadError, match="SVG"):
        load_image(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "a.png")
    with pytest.raises(ImageLoadError, match="firma"):
        load_image(b"GIF89a" + b"\0" * 100, "a.gif")
    with pytest.raises(ImageLoadError, match="corrupto|decodificar"):
        load_image(b"\x89PNG\r\n\x1a\n" + b"\x00garbage" * 50, "roto.png")
    with pytest.raises(ImageLoadError, match="MB"):
        load_image(b"\x89PNG\r\n\x1a\n" + b"\0" * (MAX_BYTES + 1), "grande.png")
    buf = io.BytesIO()
    Image.new("1", (6000, 5000)).save(buf, format="PNG")     # 30 MP, pocos bytes
    with pytest.raises(ImageLoadError, match="MP"):
        load_image(buf.getvalue(), "enorme.png")
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, format="PNG")
    with pytest.raises(ImageLoadError, match="pequeña"):
        load_image(buf.getvalue(), "mini.png")


def test_image_formats_and_logged_transformations():
    buf = io.BytesIO()
    Image.new("RGBA", (400, 300), (255, 0, 0, 128)).save(buf, format="PNG")
    im = load_image(buf.getvalue(), "../../etc/x.png")
    assert im.filename == "x.png" and any("Transparencia" in t for t in im.transformations)
    for fmt in ("JPEG", "WEBP"):
        b = io.BytesIO()
        Image.new("RGB", (400, 300), "white").save(b, format=fmt)
        im = load_image(b.getvalue(), f"a.{fmt.lower()}")
        assert im.format == fmt and im.rgb.shape == (300, 400, 3)
    assert safe_filename("C:\\a\\b<c>.png") == "b_c_.png"


# ---------------------------------------------------------------------------- detección
@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_detection_structure(name):
    r = detect(_img(name).rgb)
    assert len(r.panels) == 1 and r.ticks["X"].kind == "tick" and r.ticks["Y"].kind == "tick"
    assert r.ticks["X"].positions[0] == pytest.approx(150.5, abs=0.6)
    assert r.ticks["Y"].positions[-1] == pytest.approx(668.5, abs=0.6)
    lines = [c for c in r.candidates if c.kind == "línea" and c.confidence >= 0.5]
    assert len(lines) == (2 if name == "02_dos_curvas" else 1)
    assert all(c.coverage > 0.99 for c in lines)


@pytest.mark.parametrize("name,curve,color", [("01_curva_simple", "Curva A", "#1465b0"),
                                              ("02_dos_curvas", "Curva A", "#1465b0"),
                                              ("02_dos_curvas", "Curva B", "#d45532"),
                                              ("03_marcadores_y_ruido", "Curva A", "#1465b0")])
def test_extraction_error_against_truth(name, curve, color):
    """RMSE de DIGITALIZACIÓN [V]. Con anclas del manifiesto < 0,3 mV (≈0,25 px);
    con anclas automáticas (ticks ajustados al píxel por matplotlib) < 1,5 mV (≈1,2 px)."""
    man = json.loads((FX / f"{name}_manifest.json").read_text())
    truth = _truth(name, curve)
    d = DigitizationDraft.from_image(_img(name))
    cand = next(c for c in d.detection.candidates if c.color_hex == color)
    d.select_candidate(cand.id)
    _calibrate(d, values={"X1": 0.0, "X2": 1.5, "Y1": 0.4, "Y2": 1.1})   # posiciones automáticas
    x, y, _ = d.physical()
    rmse_auto, cov = _evaluate(truth, np.c_[x, y])
    _calibrate(d, manifest=man)
    x, y, _ = d.physical()
    rmse_man, cov2 = _evaluate(truth, np.c_[x, y])
    assert cov > 0.97 and cov2 > 0.97
    assert rmse_auto < 1.5e-3, rmse_auto
    assert rmse_man < 0.3e-3, rmse_man


def test_two_curves_are_not_mixed():
    r = detect(_img("02_dos_curvas").rgb)
    a, b = [c for c in r.candidates if c.kind == "línea"][:2]
    ya = np.interp(a.points[:, 0], b.points[:, 0], b.points[:, 1])
    assert np.all(np.abs(a.points[:, 1] - ya) > 30)       # ningún punto salta a la otra curva


def test_no_reliable_trace_and_no_axes():
    png, _, _ = render(curve=False)
    d = DigitizationDraft.from_image(load_image(png, "vacio.png"))
    assert d.points == [] and d.selected_candidate is None
    assert any("No se encontró un trazado fiable" in w for w in d.detection.warnings)
    png, _, _ = render(axes=False)
    d = DigitizationDraft.from_image(load_image(png, "sin_ejes.png"))
    assert d.points                                          # el trazo sí se detecta en píxeles
    assert all(a.position is None and a.value is None for a in d.anchors.values())
    assert d.status() == ST_NEEDS_CAL and not d.is_calibrated
    assert d.table()["x [A/cm²]"].isna().all()               # sin unidades ficticias
    with pytest.raises(ValueError):
        d.physical()


def test_log_axis_end_to_end_with_exact_anchors():
    png, (j, v), pof = render(xlog=True, xlim=(0.01, 2.0))
    d = DigitizationDraft.from_image(load_image(png, "log.png"))
    (x1, x2), _ = pof([0.01, 1.0], [0.5, 0.5])
    _, (y1, y2) = pof([0.1, 0.1], [0.5, 1.0])
    for n, pos in (("X1", x1), ("X2", x2), ("Y1", y1), ("Y2", y2)):
        d.set_anchor_position(n, float(pos))
    d.set_scale("X", SCALE_LOG)
    _calibrate(d, values={"X1": 0.01, "X2": 1.0, "Y1": 0.5, "Y2": 1.0})
    x, y, _ = d.physical()
    vis = v >= 0.41                     # matplotlib no dibuja la parte de la curva fuera del eje
    rmse, cov = _evaluate(np.c_[j, v][vis], np.c_[x, y])
    assert rmse < 1e-3 and cov > 0.95


def test_marker_series_detected_as_points():
    js = [0.1, 0.2, 0.35, 0.5, 0.7, 0.9, 1.1]
    png, (j, v), pof = render(marker="o", color="k", j=js)
    r = detect(load_image(png, "m.png").rgb)
    c = r.candidates[0]
    tx, ty = pof(j, v)
    assert c.kind == "marcadores" and len(c.points) == len(js)
    assert np.max(np.abs(c.points[:, 1] - ty)) < 1.2 and np.max(np.abs(c.points[:, 0] - tx)) < 1.2


def test_multipanel_real_figure_otekon():
    """Figura publicada OTEKON Fig. 3 (4 paneles): paneles, ticks y dos trazos del panel 1."""
    im = load_image((ROOT / "examples" / "digitizer" / "otekon_figure3_source.png").read_bytes(), "o.png")
    r = detect(im.rgb)
    assert len(r.panels) == 4 and r.panel_index == 0
    assert r.ticks["X"].kind == "tick" and len(r.ticks["X"].positions) == 7
    assert r.ticks["Y"].kind == "gridline" and len(r.ticks["Y"].positions) == 4
    names = sorted(c.color_name for c in r.candidates if c.confidence >= 0.5)
    assert names == ["azul", "rojo"]
    r4 = detect(im.rgb, DetectionParams(panel_index=3))
    assert r4.plot_box[0] > 700 and r4.plot_box[1] > 400


# ---------------------------------------------------------------------------- borrador
def test_draft_states_edits_undo_redo_and_audit():
    d = DigitizationDraft.from_image(_img("01_curva_simple"), ocr=False)      # modo manual (v0.2.0)
    assert d.status() == ST_NEEDS_CAL and all(a.value is None for a in d.anchors.values())
    _calibrate(d, values={"X1": 0.0, "X2": 1.5, "Y1": 0.4, "Y2": 1.1})
    assert d.status() == ST_REVIEW
    p = d.points[3]
    y0 = p.py
    assert d.apply_event({"type": "move_point", "id": p.id, "px": p.px, "py": y0 + 12})
    assert d.manually_edited and d.points[3].modified
    assert d.apply_event({"type": "add_point", "px": 600, "py": 300})
    n = len(d.points)
    assert d.apply_event({"type": "delete_point", "id": d.points[0].id})
    assert len(d.points) == n - 1 and d.edit_counts()["borrados"] == 1
    d.undo(); d.undo(); d.undo()
    assert d.points[3].py == pytest.approx(y0) and not d.manually_edited
    d.redo()
    assert d.points[3].py == pytest.approx(y0 + 12)
    # deshacer también restaura anclas
    d.set_anchor_value("Y2", 1.2)
    d.undo()
    assert d.anchors["Y2"].value == pytest.approx(1.1)
    acts = [e["action"] for e in d.audit]
    assert {"mover_punto", "añadir_punto", "borrar_punto", "deshacer", "rehacer", "valor_ancla"} <= set(acts)
    assert not d.apply_event({"type": "move_point", "id": 99999, "px": 1, "py": 1})
    assert not d.apply_event({"type": "bogus"})


def test_points_clamped_to_image_and_roi_validation():
    d = DigitizationDraft.from_image(_img("01_curva_simple"))
    d.apply_event({"type": "add_point", "px": -50, "py": 99999})
    p = d.points[-1]
    assert (p.px, p.py) == (0.0, 750.0)
    assert not d.apply_event({"type": "set_roi", "x0": 10, "y0": 10, "x1": 12, "y1": 12})
    assert "ROI demasiado pequeño" in d.last_error


def test_table_physical_edit_converts_to_pixels_and_exclusion_keeps_traceability():
    d = DigitizationDraft.from_image(_img("01_curva_simple"))
    _calibrate(d, values={"X1": 0.0, "X2": 1.5, "Y1": 0.4, "Y2": 1.1})
    ids = d.table()["id"].tolist()
    cal = d.calibration()[0]
    assert d.apply_table_delta({"edited_rows": {2: {d.y_label: 0.9}, 4: {"incluir": False}}}, ids)
    p = next(q for q in d.points if q.id == ids[2])
    assert p.py == pytest.approx(float(cal.y.to_pixel(0.9)))
    assert d.table().loc[2, d.y_label] == pytest.approx(0.9)
    x, y, pts = d.physical()
    assert ids[4] not in [q.id for q in pts] and len(d.points) == len(ids)   # excluido, no borrado
    assert not d.apply_table_delta({"edited_rows": {1: {d.y_label: 50.0}}}, ids)  # fuera de la imagen
    assert "fuera de la imagen" in d.last_error


def test_redetection_keeps_user_anchors_and_candidate_switch():
    d = DigitizationDraft.from_image(_img("02_dos_curvas"))
    d.set_anchor_position("X1", 150.0)
    d.set_anchor_value("X1", 0.0)
    d.run_detection(DetectionParams(n_points=15))
    assert d.anchors["X1"].px == 150.0 and d.anchors["X1"].value == 0.0
    assert len(d.points) == 15
    other = next(c for c in d.detection.candidates if c.id != d.selected_candidate and c.kind == "línea")
    d.select_candidate(other.id)
    assert {p.origin for p in d.points} == {other.id}
    d.undo()
    assert {p.origin for p in d.points} != {other.id}


def test_audit_json_and_csv_contents():
    d = DigitizationDraft.from_image(_img("01_curva_simple"), ocr=False)
    assert "SIN CALIBRAR" in d.to_csv() and "current_density_A_cm2" not in d.to_csv()
    _calibrate(d, values={"X1": 0.0, "X2": 1.5, "Y1": 0.4, "Y2": 1.1})
    a = d.to_audit_dict()
    assert a["image"]["sha256"] == d.image.sha256 and a["roi_px"] and a["calibration"]
    assert len(a["calibration_anchors"]) == 4 and a["points"][0]["px"] and "x_value" in a["points"][0]
    assert a["extraction_engine"]["version"] and a["audit_events"]
    rows = list(csv.DictReader(io.StringIO("\n".join(l for l in d.to_csv().splitlines() if not l.startswith("#")))))
    assert {"px", "py", "current_density_A_cm2", "voltage_V", "include"} <= set(rows[0])


# ---------------------------------------------------------------------------- confirmación
def _ready_draft(name="01_curva_simple"):
    d = DigitizationDraft.from_image(_img(name))
    _calibrate(d, values={"X1": 0.0, "X2": 1.5, "Y1": 0.4, "Y2": 1.1})
    return d


def test_confirm_builds_traceable_digitized_curve():
    d = _ready_draft()
    d.apply_event({"type": "toggle_include", "id": d.points[0].id})
    r = build_digitized_curve(d, CurveMetadata("dig", quality="digitalizado"), COND, DeviceInfo(name="D"), [], {})
    assert r.ok
    c = r.curve
    assert c.meta.quality == "digitalizado" and c.n_points == 39
    assert c.source_sha256 == d.image.sha256 and c.source_file == "01_curva_simple.png"
    assert "Digitalización asistida de 01_curva_simple.png" in c.meta.provenance
    assert c.mapping["anchors_px"]["Y1"]["value"] == 0.4 and c.mapping["digitizer"]["version"]
    assert any("Calibración Y" in t for t in c.transformations) and any("Excluidos" in t for t in c.transformations)
    assert set(r.artifacts) == {"01_curva_simple.png", "01_curva_simple__dig__digitalizacion.json",
                                "01_curva_simple__dig__digitalizacion.csv", "01_curva_simple__dig__overlay.png"}
    assert r.artifacts["01_curva_simple.png"] == d.image.original_bytes
    assert {"px", "py"} <= set(c.raw.columns)


def test_confirm_errors_do_not_mutate_inputs():
    d = _ready_draft()
    dev = DeviceInfo(name="D")
    first = build_digitized_curve(d, CurveMetadata("dig", quality="digitalizado"), COND, dev, [], {})
    existing, originals = [first.curve], dict(first.artifacts)
    snapshot = (list(existing), dict(originals))
    for meta, cond, device, msg in [
        (CurveMetadata("dig", quality="digitalizado"), COND, dev, "Ya existe"),
        (CurveMetadata("x", quality="medido"), COND, dev, "digitalizado"),
        (CurveMetadata("x", quality="digitalizado"), ConditionInput(343.15, "K", 99.0, "atm"), dev, "Presión"),
        (CurveMetadata("x", quality="digitalizado"), COND, DeviceInfo(name=""), "nombre"),
    ]:
        r = build_digitized_curve(d, meta, cond, device, existing, originals)
        assert not r.ok and any(msg in str(i) for i in r.issues if i.level == "error")
        assert (existing, originals) == snapshot
    d.set_anchor_value("X2", None)
    r = build_digitized_curve(d, CurveMetadata("y", quality="digitalizado"), COND, dev, existing, originals)
    assert not r.ok and any("Calibración" in str(i) for i in r.issues)


def test_units_requiring_geometry_are_not_inferred():
    d = _ready_draft()
    d.set_units("A", "V", "celda")
    r = build_digitized_curve(d, CurveMetadata("a", quality="digitalizado"), COND, DeviceInfo(name="D"), [], {})
    assert not r.ok and any("área activa" in str(i) for i in r.issues)
    d.set_units("A/cm²", "V", "stack")
    r = build_digitized_curve(d, CurveMetadata("b", quality="digitalizado"), COND, DeviceInfo(name="D"), [], {})
    assert not r.ok and any("número de celdas" in str(i) for i in r.issues)
    d.set_units("mA/cm²", "mV", "celda")     # 1,5 mA/cm² y 1,1 mV: valores físicos imposibles para una pila
    r = build_digitized_curve(d, CurveMetadata("c", quality="digitalizado"), COND, DeviceInfo(name="D"), [], {})
    assert r.ok and r.curve.v_cell_V.max() < 0.0012                 # se acepta pero queda registrado
    d.set_units("A/cm²", "V", "stack")
    r = build_digitized_curve(d, CurveMetadata("s", quality="digitalizado"), COND,
                              DeviceInfo(name="D", n_cells=10), [], {})
    assert r.ok and r.curve.v_cell_V.max() == pytest.approx(0.0962, abs=2e-3)


def test_duplicate_image_names_are_not_overwritten_and_two_curves_from_same_image():
    d = _ready_draft("02_dos_curvas")
    dev = DeviceInfo(name="D")
    lines = [c for c in d.detection.candidates if c.kind == "línea"]
    d.select_candidate(lines[0].id)
    r1 = build_digitized_curve(d, CurveMetadata("A", quality="digitalizado"), COND, dev, [], {})
    d.select_candidate(lines[1].id)
    r2 = build_digitized_curve(d, CurveMetadata("B", quality="digitalizado"), COND, dev, [r1.curve], r1.artifacts)
    assert r1.ok and r2.ok and "02_dos_curvas.png" in r2.artifacts       # misma imagen → mismo nombre
    assert not check_curve_set([r1.curve, r2.curve]) or all(i.level != "error" for i in check_curve_set([r1.curve, r2.curve]))
    other = {"02_dos_curvas.png": b"otro contenido"}
    r3 = build_digitized_curve(d, CurveMetadata("C", quality="digitalizado"), COND, dev, [], other)
    name = next(n for n in r3.artifacts if n.endswith(".png") and "overlay" not in n)
    assert name != "02_dos_curvas.png" and name.startswith("02_dos_curvas__")


def test_profile_with_digitized_curve_is_reproducible_and_not_validated():
    from identification.optimizer import preset_generic, run_identification
    from identification.profiles import build_profile, load_profile, profile_to_json
    d = _ready_draft()
    dev = DeviceInfo(name="D")
    r = build_digitized_curve(d, CurveMetadata("dig", quality="digitalizado"), COND, dev, [], {})
    fit = run_identification([r.curve], preset_generic([r.curve]))
    prof = build_profile(fit, [r.curve], dev)
    assert prof["status"]["code"] != "VALIDADO_EXPERIMENTALMENTE"
    assert prof["validation"]["status"] == "SIN_VALIDACION_INDEPENDIENTE"
    text = profile_to_json(prof)
    assert "base64" not in text and len(text) < 200_000      # sin imagen incrustada
    ds = prof["datasets"][0]
    assert ds["metadata"]["quality"] == "digitalizado" and ds["source_sha256"] == d.image.sha256
    loaded = load_profile(text)
    assert loaded.reproduction_ok


# ---------------------------------------------------------------------------- v0.3.0: reconocimiento automático
def _fig_sci_x():
    import matplotlib.pyplot as plt
    j = np.linspace(0.05, 1.4, 60)
    v = 1 - 0.06 * np.log(j / 0.01 + 1) - 0.25 * j
    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    ax.plot(j * 2000, v * 40)
    ax.set_xlim(0, 3000); ax.set_ylim(15, 45)
    ax.ticklabel_format(style="sci", axis="x", scilimits=(0, 0))
    ax.set_xlabel("I (mA)"); ax.set_ylabel("Stack voltage (V)")
    buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=100); plt.close(fig)
    return buf.getvalue(), j * 2000, v * 40


@pytest.mark.parametrize("name,curve,color", [("01_curva_simple", "Curva A", "#1465b0"),
                                              ("02_dos_curvas", "Curva B", "#d45532")])
def test_fully_automatic_calibration_without_typing(name, curve, color):
    d = DigitizationDraft.from_image(_img(name))
    assert d.axis_confirmed == {"X": True, "Y": True} and d.units_confirmed
    assert (d.current_unit, d.voltage_unit) == ("A/cm²", "V") and "títulos" in d.units_source
    assert {n: d.anchors[n].source for n in d.anchors} == {"X1": "auto-ocr", "X2": "auto-ocr", "Y1": "auto-ocr", "Y2": "auto-ocr"}
    assert d.physical_ready()[0]
    cand = next(c for c in d.detection.candidates if c.color_hex == color)
    d.select_candidate(cand.id)
    x, y, _ = d.physical()
    rmse, cov = _evaluate(_truth(name, curve), np.c_[x, y])
    assert rmse < 1.5e-3 and cov > 0.97
    r = build_digitized_curve(d, CurveMetadata("auto", quality="digitalizado"), COND, DeviceInfo(name="D"), [], {})
    assert r.ok and r.curve.mapping["axis_recognition"]["X"]["status"] == "CONFIABLE"
    assert r.curve.mapping["axis_confirmed"] == {"X": True, "Y": True}


def test_review_axis_blocks_physical_use_until_confirmed():
    png, i_true, v_true = _fig_sci_x()
    d = DigitizationDraft.from_image(load_image(png, "sci.png"))
    assert d.axis_recognition["X"].status == "REVISION" and d.axis_recognition["X"].multiplier == 1000
    assert d.anchors["X2"].value == pytest.approx(3000.0)           # valores ya escalados por el multiplicador
    ok, why = d.physical_ready()
    assert not ok and any("Eje X pendiente" in w for w in why)
    r = build_digitized_curve(d, CurveMetadata("s", quality="digitalizado"), COND,
                              DeviceInfo(name="D", n_cells=40, active_area_cm2=2000.0), [], {})
    assert not r.ok and any("Confirmación pendiente" in str(i) for i in r.issues)
    assert d.confirm_axis("X") and d.physical_ready()[0]
    assert (d.current_unit, d.voltage_unit) == ("mA", "V")
    d.undo()
    assert not d.axis_confirmed["X"]                                   # deshacer también revierte la confirmación


def test_individual_label_correction_and_exclusion():
    d = DigitizationDraft.from_image(_img("01_curva_simple"))
    rec = d.axis_recognition["Y"]
    k = next(i for i, l in enumerate(rec.labels) if l.inlier and l.value == pytest.approx(0.7))
    assert d.correct_label("Y", k, value=0.9)                          # lectura «equivocada» introducida a mano
    rec = d.axis_recognition["Y"]
    assert rec.status == "REVISION" and not d.axis_confirmed["Y"]
    assert d.correct_label("Y", k, exclude=True)
    assert d.axis_recognition["Y"].status == "CONFIABLE" and d.axis_confirmed["Y"]
    assert any(e["action"] == "corregir_etiqueta" for e in d.audit)


def test_ocr_never_overwrites_user_anchor_values():
    d = DigitizationDraft.from_image(_img("01_curva_simple"))
    d.set_anchor_position("X1", 150.0)
    d.set_anchor_value("X1", 0.0)
    d.run_detection(DetectionParams(n_points=20))
    assert d.anchors["X1"].px == 150.0 and d.anchors["X1"].source == "usuario"


def test_ocr_disabled_keeps_manual_v020_behaviour():
    d = DigitizationDraft.from_image(_img("01_curva_simple"), ocr=False)
    assert d.axis_recognition == {} and all(a.value is None for a in d.anchors.values())
    assert not d.physical_ready()[0]


def test_saved_curves_per_panel():
    d = DigitizationDraft.from_image(_img("02_dos_curvas"))
    lines = [c for c in d.detection.candidates if c.kind == "línea"]
    d.select_candidate(lines[0].id)
    d.save_curve("A")
    with pytest.raises(ValueError, match="Ya existe"):
        d.save_curve("A")
    d.select_candidate(lines[1].id)
    d.save_curve("B")
    assert [c["name"] for c in d.saved_curves] == ["A", "B"]
    assert d.load_saved_curve("A") and {p.origin for p in d.points} == {lines[0].id}
    assert d.delete_saved_curve("B") and [c["name"] for c in d.saved_curves] == ["A"]
    d.undo()
    assert [c["name"] for c in d.saved_curves] == ["A", "B"]


def test_high_resolution_tablet_sized_image_is_recognized_and_accurate():
    """Imagen 3× (3600 px, típica de capturas/fotos de tablet): ejes confiables y la misma exactitud relativa."""
    big = Image.open(FX / "01_curva_simple.png").convert("RGB").resize((3600, 2250), Image.Resampling.LANCZOS)
    buf = io.BytesIO(); big.save(buf, format="PNG")
    d = DigitizationDraft.from_image(load_image(buf.getvalue(), "big.png"))
    assert d.axis_confirmed == {"X": True, "Y": True} and d.units_confirmed
    assert d.detection.analysis_scale < 1.0                     # análisis normalizado por el lado mayor
    x, y, _ = d.physical()
    rmse, cov = _evaluate(_truth("01_curva_simple", "Curva A"), np.c_[x, y])
    assert rmse < 1.5e-3 and cov > 0.97
