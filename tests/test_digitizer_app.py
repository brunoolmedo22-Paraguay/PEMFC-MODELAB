"""Flujo del digitalizador en la interfaz real (streamlit.testing.v1.AppTest).

Las interacciones del lienzo (arrastrar, zoom) se verifican en navegador real con
Playwright (docs/VERIFICACION_DIGITALIZADOR.md); aquí se prueban el diálogo, el
estado de sesión, el bloqueo sin calibración, la confirmación y el aislamiento.
"""
from pathlib import Path

from ui_driver import goto, open_workspace

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app.py")
FX = ROOT / "tests" / "fixtures" / "digitizer"
PNG = (FX / "01_curva_simple.png").read_bytes()


def _app():
    return open_workspace(step=2, name="Dispositivo digitalizado")


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _open_and_upload(at, data=PNG, name="01_curva_simple.png"):
    at.radio(key="src_mode").set_value("Imagen de una curva").run()
    at.button(key="dz_open_btn").click().run()
    assert at.session_state.dz_open
    up = next(u for u in at.get("file_uploader") if u.proto.id and "dz_up_" in u.id)
    up.set_value((name, data, "image/png")).run()
    assert not at.exception


def _calibrate(at, vals=(("X1", "0"), ("X2", "1,5"), ("Y1", "0.4"), ("Y2", "1.1"))):
    for n, v in vals:
        at.text_input(key=f"dz_val_{n}").set_value(v).run()


def _metadata(at, cid="dig_app"):
    at.text_input(key="dz_id").set_value(cid).run()
    at.number_input(key="dz_T").set_value(343.15).run()
    at.number_input(key="dz_P").set_value(1.5).run()


def _device(at):
    """v0.3.0: el dispositivo se crea en el catálogo y se edita en la etapa 01."""


def test_upload_triggers_detection_and_blocks_without_calibration():
    at = _app()
    _device(at)
    _open_and_upload(at)
    d = at.session_state.dz_draft
    assert len(d.points) == 40 and d.selected_candidate == "C1"
    # v0.3.0: valores de los ejes reconocidos automáticamente (OCR + verificación geométrica)
    assert d.is_calibrated and d.axis_confirmed == {"X": True, "Y": True} and d.units_confirmed
    assert at.text_input(key="dz_val_X2").value == "1.5" and at.text_input(key="dz_val_Y2").value == "1.1"
    assert _btn(at, "Confirmar y añadir curva").disabled          # faltan condiciones de medición
    assert at.session_state.curves == []


def test_confirm_adds_digitized_curve_to_existing_flow_and_fit_runs():
    at = _app()
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_handoff").click().run()
    n0 = len(at.session_state.curves)
    _open_and_upload(at)
    _calibrate(at)
    _metadata(at)
    _btn(at, "Confirmar y añadir curva").click().run()
    assert not at.exception
    curves = at.session_state.curves
    assert len(curves) == n0 + 1 and curves[-1].curve_id == "dig_app"
    assert curves[-1].meta.quality == "digitalizado"
    assert "01_curva_simple.png" in at.session_state.originals
    assert any(k.endswith("__digitalizacion.json") for k in at.session_state.originals)
    assert not at.session_state.dz_open
    assert any("añadida" in s.value for s in at.success)
    dr = at.session_state.ws.drafts[at.session_state.route["draft"]]
    assert len(dr.curves) == n0 + 1 and "01_curva_simple.png" in dr.originals        # volcado al borrador
    goto(at, 3)
    goto(at, 4)
    at.button(key="run_fit").click().run()
    assert not at.exception and at.session_state.fit_result is not None
    assert at.session_state.profile["status"]["code"] != "VALIDADO_EXPERIMENTALMENTE"


def test_cancel_keeps_dataset_fit_and_profile():
    at = _app()
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_otekon").click().run()
    goto(at, 3)
    _btn(at, "Preset OTEKON (9 parámetros, reproducción del artículo)").click().run()
    goto(at, 4)
    at.button(key="run_fit").click().run()
    goto(at, 2)
    ws = at.session_state.ws
    draft_before = ws.record_value(f"draft:{at.session_state.route['draft']}")
    n_cal = len(ws.calibrations)
    before = (at.session_state.data_key if hasattr(at.session_state, "data_key") else None,
              [c.normalized_sha256 for c in at.session_state.curves], at.session_state.fit_key,
              at.session_state.profile["profile_id"], dict(at.session_state.originals).keys(),
              at.session_state.dataset_label, id(at.session_state.fit_result))
    _open_and_upload(at)
    _calibrate(at)
    _btn(at, "Cancelar").click().run()
    assert not at.exception
    after = (at.session_state.data_key if hasattr(at.session_state, "data_key") else None,
             [c.normalized_sha256 for c in at.session_state.curves], at.session_state.fit_key,
             at.session_state.profile["profile_id"], dict(at.session_state.originals).keys(),
             at.session_state.dataset_label, id(at.session_state.fit_result))
    assert before == after
    assert "dz_draft" not in at.session_state and not at.session_state.dz_open
    assert ws.record_value(f"draft:{at.session_state.route['draft']}") == draft_before     # borrador intacto
    assert len(ws.calibrations) == n_cal


def test_errors_keep_dialog_open_and_dataset_intact():
    at = _app()
    _device(at)
    _open_and_upload(at)
    _calibrate(at)
    _metadata(at)
    at.number_input(key="dz_P").set_value(99.0).run()            # presión fuera de rango → error del pipeline
    _btn(at, "Confirmar y añadir curva").click().run()
    assert not at.exception
    assert at.session_state.curves == [] and at.session_state.dz_open
    assert any("Presión absoluta" in e.value for e in at.error)


def test_corrupt_and_svg_images_are_recoverable():
    at = _app()
    _open_and_upload(at, b"\x89PNG\r\n\x1a\n" + b"basura" * 100, "roto.png")
    assert "dz_draft" not in at.session_state or at.session_state.dz_draft is None
    assert any("Imagen rechazada" in e.value for e in at.error)
    up = next(u for u in at.get("file_uploader") if "dz_up_" in u.id)
    up.set_value(("01.png", PNG, "image/png")).run()
    assert at.session_state.dz_draft is not None and not at.exception


def test_new_image_with_edited_draft_asks_before_discarding():
    at = _app()
    _open_and_upload(at)
    _calibrate(at, (("X2", "1.4"),))                                   # edición real del usuario
    d = at.session_state.dz_draft
    sha = d.image.sha256
    other = (FX / "02_dos_curvas.png").read_bytes()
    up = next(u for u in at.get("file_uploader") if "dz_up_" in u.id)
    up.set_value(("02.png", other, "image/png")).run()
    assert at.session_state.dz_draft.image.sha256 == sha          # aún no se descarta
    assert any("Descartarlo" in w.value for w in at.warning)
    _btn(at, "Conservar el borrador actual").click().run()
    assert at.session_state.dz_draft.image.sha256 == sha
    up = next(u for u in at.get("file_uploader") if "dz_up_" in u.id)
    up.set_value(("02.png", other, "image/png")).run()                 # se vuelve a preguntar
    assert any("Descartarlo" in w.value for w in at.warning)
    _btn(at, "Descartar borrador y usar la nueva imagen").click().run()
    assert at.session_state.dz_draft.image.sha256 != sha
    assert len([c for c in at.session_state.dz_draft.detection.candidates if c.kind == "línea"]) == 2
