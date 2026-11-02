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
    assert "PRÓXIMAMENTE" not in html and "Sensibilidad y comparación de escenarios" in html and "Mapa operacional" in html
    assert len([b for b in at.button if b.label == "Abrir bancada"]) == 6           # v0.5.0: seis bancadas
    assert not [b for b in at.button if b.label == "Funcionalidad futura"]


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
    assert {s["bench"] for s in st_["skipped"]} == {"carga", "hidrogeno", "sensibilidad", "mapa"}   # sin configuración → omitidas


def test_bench05_scenarios_and_bench06_map_with_integrations():
    at, m = _lab()
    _open(at, 4)
    at.selectbox(key="m2b_sensibilidad_cond").set_value(at.selectbox(key="m2b_sensibilidad_cond").options[4]).run()
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    ws = at.session_state.ws
    (e5,) = ws.experiments.values()
    assert e5.bench == "sensibilidad" and e5.result["context"]["mode"] == "escenarios"
    _btn(at, "Generar mapa con él").click().run()                        # escenario → Bancada 06
    assert at.session_state.m2["bench"] == "mapa" and not at.exception
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    e6 = next(e for e in ws.experiments.values() if e.bench == "mapa")
    assert e6.result["context"]["optimum"] is not None
    _btn(at, "Guardar como escenario (Bancada 05)").click().run()        # mapa → Bancada 05
    assert at.session_state.m2_scen_add
    _btn(at, "Enviar a la Bancada 04 (potencia objetivo)").click().run()  # mapa → Bancada 04
    assert at.session_state.m2["bench"] == "optimizacion" and not at.exception
    assert at.selectbox(key="m2b_optimizacion_obj").value == "potencia_objetivo"
    _btn(at, "▶ Ejecutar experimento").click().run()
    e4 = next(e for e in ws.experiments.values() if e.bench == "optimizacion")
    assert e4.result["context"]["selected"]["P_W"] > 0 and not at.exception


def test_bench05_sensitivity_and_uncertainty_modes():
    at, m = _lab()
    _open(at, 4)
    at.segmented_control(key="m2b_sensibilidad_mode").set_value("sensibilidad").run()
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    at.segmented_control(key="m2b_sensibilidad_mode").set_value("incertidumbre").run()
    at.slider(key="m2b_sensibilidad_ns").set_value(100).run()
    _btn(at, "▶ Ejecutar experimento").click().run()
    assert not at.exception, at.exception
    modes = sorted(e.result["context"]["mode"] for e in at.session_state.ws.experiments.values())
    assert modes == ["incertidumbre", "sensibilidad"]
