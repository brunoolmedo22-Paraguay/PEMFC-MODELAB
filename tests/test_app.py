"""Flujos de la interfaz Streamlit de extremo a extremo (A01, A07, A09, A11, A12)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")
STACK_CSV = "corriente_A;tension_stack_V\n" + "\n".join(
    f"{i};{v}" for i, v in [(2.5, 18.4), (5, 17.6), (10, 16.9), (15, 16.4), (20, 15.95), (25, 15.5),
                            (30, 15.05), (35, 14.55), (40, 13.95), (45, 13.2)])


def _app():
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception
    return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def _paste(at, csv, sep=";"):
    at.radio(key="src_mode").set_value("Pegar datos CSV").run()
    at.selectbox(key="csv_sep").set_value(sep).run()
    at.text_area(key="csv_text").set_value(csv).run()


def _device(at, name="Stack X", n=20, area=50.0):
    at.text_input(key="dev_name").set_value(name).run()
    at.checkbox(key="dev_n_known").check().run()
    at.number_input(key="dev_n").set_value(n).run()
    at.checkbox(key="dev_a_known").check().run()
    at.number_input(key="dev_a").set_value(area).run()


def test_initial_render_and_guards():
    at = _app()
    texts = " ".join(i.value for i in at.info)
    assert "Sin curva V–I no es posible crear un perfil" in texts
    assert "datasheet" in texts
    at.radio(key="src_mode").set_value("Imagen de una curva").run()
    assert any("no está implementada" in w.value for w in at.warning)


def test_otekon_example_full_flow():
    at = _app()
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_otekon").click().run()
    assert len(at.session_state.curves) == 4
    _button(at, "Preset OTEKON (9 parámetros, reproducción del artículo)").click().run()
    at.button(key="run_fit").click().run()
    assert not at.exception
    r = at.session_state.fit_result
    assert r.status == "AJUSTADO_A_CURVA" and abs(r.metrics_global["rmse_V"] - 0.0014113700033) < 1e-6
    assert at.session_state.profile is not None
    at.button(key="prep_zip").click().run()
    assert not at.exception and len(at.session_state.zip_bytes) > 100_000


def test_new_stack_csv_without_code_changes():
    at = _app()
    _device(at)
    _paste(at, STACK_CSV)
    at.number_input(key="sc_T").set_value(65.0).run()
    at.selectbox(key="sc_Tu").set_value("°C").run()
    at.number_input(key="sc_P").set_value(50.0).run()
    at.selectbox(key="sc_Pu").set_value("kPa").run()
    at.selectbox(key="sc_Pref").set_value("manométrica").run()
    at.number_input(key="sc_amb").set_value(101.325).run()
    _button(at, "Validar y añadir al conjunto").click().run()
    assert not at.exception and not at.error
    c = at.session_state.curves[0]
    assert abs(c.j_A_cm2[0] - 2.5 / 50) < 1e-12 and abs(c.v_cell_V[0] - 18.4 / 20) < 1e-12
    assert abs(c.conditions.temperature_K - 338.15) < 1e-9
    at.button(key="run_fit").click().run()
    assert not at.exception
    assert at.session_state.fit_result.status == "AJUSTADO_A_CURVA"
    assert at.session_state.profile["device"]["n_cells"] == 20


def test_invalid_csv_shows_error_and_creates_nothing():
    at = _app()
    _device(at)
    _paste(at, "corriente_A;tension_stack_V\n2.5;18.4\n5;abc\n10;16.9\n15;\n20;15.9", ";")
    at.number_input(key="sc_T").set_value(338.15).run()
    at.number_input(key="sc_P").set_value(1.5).run()
    _button(at, "Validar y añadir al conjunto").click().run()
    assert not at.exception
    err = " ".join(e.value for e in at.error)
    assert "no numéricos" in err and "vacías" in err
    assert at.session_state.curves == [] and at.session_state.profile is None


def test_missing_conditions_block_validation():
    at = _app()
    _device(at)
    _paste(at, STACK_CSV)
    assert not [b for b in at.button if b.label == "Validar y añadir al conjunto"]
    assert any("Complete temperatura y presión" in i.value for i in at.info)


def test_stack_data_without_geometry_rejected():
    at = _app()
    at.text_input(key="dev_name").set_value("Sin geometría").run()
    _paste(at, STACK_CSV)
    at.number_input(key="sc_T").set_value(338.15).run()
    at.number_input(key="sc_P").set_value(1.5).run()
    _button(at, "Validar y añadir al conjunto").click().run()
    assert any("área activa" in e.value for e in at.error)
    assert at.session_state.curves == []


def test_synthetic_example_validation_status_and_profile_reload():
    at = _app()
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_synthetic").click().run()
    at.button(key="run_fit").click().run()
    r = at.session_state.fit_result
    assert r.status == "AJUSTADO_A_CURVA"
    assert r.validation["status"] == "VALIDACION_CON_DATOS_NO_EXPERIMENTALES"
    from identification.profiles import profile_to_json
    at.text_area(key="profile_text").set_value(profile_to_json(at.session_state.profile)).run()
    assert not at.exception
    assert any("Reproducción de la curva guardada" in s.value and "OK" in s.value for s in at.success)


def test_stale_result_blocks_export():
    at = _app()
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_handoff").click().run()
    at.button(key="run_fit").click().run()
    assert at.session_state.fit_result is not None
    at.number_input(key="cfg_starts").set_value(3).run()
    assert any("desactualizado" in e.value for e in at.error)
