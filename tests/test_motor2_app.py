"""Motor 2 en la interfaz real (AppTest): bancadas, persistencia, historial, duplicación y estudio completo."""
import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui_driver import APP

PROFILE = (Path(__file__).parent / "fixtures" / "compat" / "profile_v020.json").read_bytes()


def _lab():
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    from workspace.project_io import import_v020_profile
    m = import_v020_profile(at.session_state.ws, PROFILE, "p.json")
    at.session_state.route = {**at.session_state.route, "view": "motor2"}
    at.run()
    assert not at.exception, at.exception
    return at, m


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def _open(at, bench_label_idx):
    [b for b in at.button if b.label == "Abrir bancada"][bench_label_idx].click().run()
    assert not at.exception, at.exception


def test_lab_home_selector_profile_and_cards():
    at, m = _lab()
    html = " ".join(h.proto.body for h in at.get("html"))
    assert "Motor 2 — Laboratorio Virtual" in html and "AJUSTADO_A_CURVA" in html
    assert "PRÓXIMAMENTE" in html and "Sensibilidad y comparación de escenarios" in html and "Mapa operacional" in html
    assert len([b for b in at.button if b.label == "Abrir bancada"]) == 4
    assert all(b.disabled for b in at.button if b.label == "Funcionalidad futura")


def test_reproduction_bench_runs_and_persists():
    at, m = _lab()
    _open(at, 0)
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    ws = at.session_state.ws
    (ex,) = ws.experiments.values()
    assert ex.bench == "reproduccion" and ex.result["context"]["consistent_with_motor1"]
    assert f"experiment:{ex.id}" in ws.dirty                         # pendiente de persistir en el navegador
    assert any("RMSE" == mm.label for mm in at.metric)


def test_load_following_bench_needs_conditions_then_runs():
    at, m = _lab()
    _open(at, 1)
    assert at.selectbox(key="m2b_carga_cond").value.endswith("(calibrada)")   # condición real del perfil, visible
    at.selectbox(key="m2b_carga_cond").set_value(at.selectbox(key="m2b_carga_cond").options[2]).run()
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    ex = next(iter(at.session_state.ws.experiments.values()))
    assert ex.bench == "carga" and any(k["key"] == "E_uns" for k in ex.result["kpis"])
    assert any("Sin restricción de rampa evaluada" in w.value for w in at.warning)


def test_hydrogen_bench_max_power_requires_umax():
    at, m = _lab()
    _open(at, 2)
    at.selectbox(key="m2b_hidrogeno_cond").set_value(at.selectbox(key="m2b_hidrogeno_cond").options[2]).run()
    at.selectbox(key="m2b_hidrogeno_pol").set_value("max_potencia").run()
    assert _btn(at, "▶ Ejecutar experimento").disabled is False
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert any("utilización máxima" in e.value for e in at.error)    # no se inventa u_máx
    assert not at.session_state.ws.experiments
    at.number_input(key="m2b_hidrogeno_umax").set_value(0.8).run()
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception and len(at.session_state.ws.experiments) == 1


def test_optimization_bench_history_duplicate_and_study():
    at, m = _lab()
    _open(at, 3)
    at.selectbox(key="m2b_optimizacion_cond").set_value(at.selectbox(key="m2b_optimizacion_cond").options[2]).run()
    at.selectbox(key="m2b_optimizacion_obj").set_value("max_eficiencia").run()
    at.number_input(key="m2b_optimizacion_pmin").set_value(1000.0).run()
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    ws = at.session_state.ws
    (ex,) = ws.experiments.values()
    assert abs(ex.result["context"]["selected"]["P_W"] - 1000.0) < 1e-6
    _btn(at, "← Bancadas").click().run()
    at.session_state.m2 = {**at.session_state.m2, "tab": "Historial"}
    at.session_state["m2_tab_sel"] = "Historial"
    at.run()
    _btn(at, "Duplicar configuración").click().run()
    assert not at.exception and at.session_state.m2["bench"] == "optimizacion"
    assert at.number_input(key="m2b_optimizacion_pmin").value == 1000.0
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert len(ws.experiments) == 2 and any(e.duplicated_from == ex.id for e in ws.experiments.values())
    _btn(at, "← Bancadas").click().run()
    at.session_state["m2_tab_sel"] = "Estudio completo"
    at.run()
    _btn(at, "▶ Ejecutar estudio completo").click().run()
    assert not at.exception, at.exception
    st_ = at.session_state.m2_study
    assert {ws.experiments[i].bench for i in st_["done"]} == {"reproduccion", "optimizacion"}
    assert {s["bench"] for s in st_["skipped"]} == {"carga", "hidrogeno"}   # sin configuración → omitidas
