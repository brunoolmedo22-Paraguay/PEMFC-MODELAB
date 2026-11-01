"""Reconocimiento automático de ejes: OCR local + verificación geométrica (v0.3.0)."""
import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from digitizer import axis_ocr, ocr  # noqa: E402
from digitizer.axis_ocr import (  # noqa: E402
    ST_INSUFFICIENT, ST_RELIABLE, ST_REVIEW, LabelEvidence, detect_unit, evaluate_axis, fit_axis, parse_label,
    parse_multiplier, recognize_axes, recompute, Interp,
)
from digitizer.detection import DetectionParams, detect  # noqa: E402
from digitizer.imageio import load_image  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "tests" / "fixtures" / "digitizer"


def _fig(kind):
    j = np.linspace(0.05, 1.4, 60)
    v = 1 - 0.06 * np.log(j / 0.01 + 1) - 0.25 * j
    fig, ax = plt.subplots(figsize=(8, 5), dpi=100)
    if kind == "comma":
        ax.plot(j, v); ax.set_xlim(0, 1.5); ax.set_ylim(0.4, 1.1)
        f = mt.FuncFormatter(lambda x, p: f"{x:.1f}".replace(".", ","))
        ax.xaxis.set_major_formatter(f); ax.yaxis.set_major_formatter(f)
        ax.set_xlabel("j (A/cm²)"); ax.set_ylabel("U (V)")
    elif kind == "neg":
        ax.plot(j, v - 0.7); ax.set_xlim(-0.5, 1.5); ax.set_ylim(-0.4, 0.4); ax.set_xlabel("x (mA)"); ax.set_ylabel("ΔV (mV)")
    elif kind == "log":
        jj = np.logspace(-3, 0.2, 60)
        ax.semilogx(jj, 1 - 0.06 * np.log(jj / 0.001 + 1)); ax.set_xlim(1e-3, 2); ax.set_ylim(0.4, 1.1)
        ax.set_xlabel("i (A cm$^{-2}$)"); ax.set_ylabel("E (V)")
    elif kind == "sci_x":
        ax.plot(j * 2000, v * 40); ax.set_xlim(0, 3000); ax.set_ylim(15, 45)
        ax.ticklabel_format(style="sci", axis="x", scilimits=(0, 0)); ax.set_xlabel("I (mA)"); ax.set_ylabel("Stack voltage (V)")
    elif kind == "sci_y":
        ax.plot(j, v * 0.004); ax.set_xlim(0, 1.5); ax.set_ylim(0.0016, 0.0044)
        ax.ticklabel_format(style="sci", axis="y", scilimits=(0, 0)); ax.set_xlabel("j (A/cm2)"); ax.set_ylabel("P (W)")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def _recognize(png, panel_index=None):
    im = load_image(png, "x.png")
    r = detect(im.rgb, DetectionParams(panel_index=panel_index))
    return recognize_axes(im.rgb, r.panels[r.panel_index], r.ticks, r.background_rgb), r


# --------------------------------------------------------------------------- análisis de texto
@pytest.mark.parametrize("text,values", [
    ("0.4", [0.4]), ("0,4", [0.4]), ("1,2", [1.2]), ("-0.25", [-0.25]), ("−0,5", [-0.5]), ("1.0-", [1.0]),
    ("10-3", [0.001]), ("10^-2", [0.01]), ("100", [100.0, 1.0]), ("103", [103.0, 1000.0]),
    ("1e-3", [0.001]), ("2.5E+02", [250.0]), ("3×10-2", [0.03]), ("1,000", [1.0, 1000.0]), ("50%", [50.0]),
    ("O.5", [0.5]), ("l.5", [1.5]),
])
def test_parse_label_candidates(text, values):
    assert [pytest.approx(v) for v in values] == [i.value for i in parse_label(text)]


@pytest.mark.parametrize("text", ["", "Tensión", "A/cm2", "(V)", "--", "abc1"])
def test_non_numeric_labels(text):
    assert parse_label(text) == []


@pytest.mark.parametrize("text,m", [("1e3", 1e3), ("le-3", 1e-3), ("×10³", 1e3), ("x10-2", 1e-2), ("1e−3", 1e-3),
                                    ("0.5", None), ("Tensión", None)])
def test_parse_multiplier(text, m):
    assert parse_multiplier(text) == (pytest.approx(m) if m else None)


@pytest.mark.parametrize("title,unit", [
    ("Densidad de corriente [A/cm2]", "A/cm²"), ("Current Density ( A/cm2)", "A/cm²"), ("i (A cm-2)", "A/cm²"),
    ("j (mA/cm²)", "mA/cm²"), ("Tensión de celda [V]", "V"), ("Activation Loss ( Volts )", "V"), ("ΔV (mV)", "mV"),
    ("I (mA)", "mA"), ("Stack current (A)", "A"), ("Power ( Watt )", "W"), ("Efficiency ( % )", "%"),
    ("Tensión de celda", None), ("", None),
])
def test_detect_unit(title, unit):
    assert detect_unit(title)[1] == unit


# --------------------------------------------------------------------------- ajuste geométrico
def test_fit_rejects_outlier_and_resolves_ambiguity():
    pos = [100, 200, 300, 400, 500]
    texts = ["0,0", "0,5", "7,0", "1,5", "2,0"]          # «7,0» es una lectura errónea (debería ser 1,0)
    fit = fit_axis(pos, [parse_label(t) for t in texts], 100)
    assert not fit["log"] and len(fit["chosen"]) == 4 and 2 not in [k for k, _ in fit["chosen"]]
    fit = fit_axis([100, 200, 300, 400], [parse_label(t) for t in ["10-3", "10-2", "10-1", "100"]], 100)
    assert fit["log"] and [round(c.value, 6) for _, c in fit["chosen"]] == [0.001, 0.01, 0.1, 1.0]


def test_user_correction_and_exclusion_recompute():
    labels = [LabelEvidence(t, 0.99, [0, 0, 1, 1], p, True, [i.__dict__ for i in parse_label(t)])
              for t, p in zip(["0", "2", "9", "6", "8"], [100, 200, 300, 400, 500])]
    rec = evaluate_axis("X", labels, 100)
    axis_ocr._finalize_status(rec)
    assert rec.status == ST_REVIEW and any("«9»" in r for r in rec.reasons)
    labels[2].user_value = 4.0
    rec2 = recompute(rec, 100)
    assert rec2.status == ST_RELIABLE and rec2.n_inliers == 5 and rec2.anchors == [(100, 0.0), (500, 8.0)]
    labels[2].user_value, labels[2].excluded_by_user = None, True
    assert recompute(rec, 100).n_inliers == 4


def test_two_labels_only_needs_review_and_one_is_insufficient():
    mk = lambda ts: [LabelEvidence(t, 0.99, [0, 0, 1, 1], p, True, [i.__dict__ for i in parse_label(t)])  # noqa: E731
                     for t, p in ts]
    r = evaluate_axis("X", mk([("0", 100), ("1", 300)]), None); axis_ocr._finalize_status(r)
    assert r.status == ST_REVIEW
    r = evaluate_axis("X", mk([("0", 100)]), None); axis_ocr._finalize_status(r)
    assert r.status == ST_INSUFFICIENT and r.anchors == []


# --------------------------------------------------------------------------- imágenes reales y sintéticas
@pytest.mark.parametrize("name", ["01_curva_simple", "02_dos_curvas", "03_marcadores_y_ruido"])
def test_handoff_fixtures_fully_automatic(name):
    rec, _ = _recognize((FX / f"{name}.png").read_bytes())
    x, y = rec["X"], rec["Y"]
    assert x.status == ST_RELIABLE and y.status == ST_RELIABLE
    assert x.scale == y.scale == "lineal"
    assert x.anchors == [(pytest.approx(150.5, abs=0.6), 0.0), (pytest.approx(1080.5, abs=0.6), 1.5)]
    assert sorted(v for _, v in y.anchors) == [0.4, 1.1]
    assert x.title["unit"] == "A/cm²" and y.title["unit"] == "V"
    assert x.rms_px < 1.0 and y.rms_px < 1.0


@pytest.mark.parametrize("kind,axis,scale,lo,hi,unit", [
    ("comma", "X", "lineal", 0.0, 1.4, "A/cm²"), ("comma", "Y", "lineal", 0.4, 1.1, None),
    ("neg", "X", "lineal", -0.5, 1.5, "mA"), ("neg", "Y", "lineal", -0.4, 0.4, "mV"),
    ("log", "X", "logarítmica", 0.001, 1.0, "A/cm²"),
])
def test_synthetic_axes_reliable(kind, axis, scale, lo, hi, unit):
    rec, _ = _recognize(_fig(kind))
    a = rec[axis]
    vals = sorted(l.value for l in a.labels if l.inlier)
    assert a.status == ST_RELIABLE and a.scale == scale and a.multiplier is None
    assert vals[0] == pytest.approx(lo) or vals[0] == pytest.approx(lo + (0.2 if kind == "comma" else 0)), vals
    assert vals[-1] == pytest.approx(hi)
    if unit:
        assert a.title and a.title["unit"] == unit


@pytest.mark.parametrize("kind,axis,mult", [("sci_x", "X", 1e3), ("sci_y", "Y", 1e-3)])
def test_axis_multiplier_is_detected_and_requires_review(kind, axis, mult):
    """El caso peligroso: sin el multiplicador los valores serían 1000 veces erróneos."""
    rec, _ = _recognize(_fig(kind))
    a = rec[axis]
    assert a.multiplier == pytest.approx(mult)
    assert a.status == ST_REVIEW and any("Multiplicador" in r for r in a.reasons)


def test_real_published_figure_otekon_panels():
    png = (ROOT / "examples" / "digitizer" / "otekon_figure3_source.png").read_bytes()
    for k, (ylo, yhi) in ((0, (0.5, 1.1)), (3, (0.5, 1.1))):
        rec, _ = _recognize(png, k)
        assert rec["X"].status == ST_RELIABLE and rec["Y"].status == ST_RELIABLE
        assert sorted(v for _, v in rec["X"].anchors) == [0.0, 1.2]
        assert sorted(v for _, v in rec["Y"].anchors) == [ylo, yhi]
        assert rec["X"].title["unit"] == "A/cm²" and rec["Y"].title["unit"] == "V"


def test_ocr_unavailable_degrades_to_manual(monkeypatch):
    def boom(*a, **k):
        raise ocr.OCRUnavailable("modelo ausente (prueba)")
    monkeypatch.setattr(axis_ocr, "recognize_boxes", boom)
    rec, _ = _recognize((FX / "01_curva_simple.png").read_bytes())
    assert rec["X"].status == ST_INSUFFICIENT and rec["X"].anchors == []
    assert "OCR no disponible" in rec["X"].reasons[0]


def test_model_integrity_and_local_only():
    assert ocr.MODEL_PATH.exists()
    import hashlib
    assert hashlib.sha256(ocr.MODEL_PATH.read_bytes()).hexdigest() == ocr.MODEL_SHA256
    ok, info = ocr.ocr_available()
    assert ok, info
