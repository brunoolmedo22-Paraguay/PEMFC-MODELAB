"""Bancadas 05 y 06: verificaciones analíticas, máscaras, coherencia con la Bancada 04 y exportación."""
import copy
import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pytest

from simulation import runner
from simulation.benches import run_optimization
from simulation.maps import point_details, run_map
from simulation.report import experiment_zip, to_xlsx
from simulation.scenarios import build_model, run_scenarios, run_sensitivity, run_uncertainty, uncertainty_available
from simulation.stack import OperatingLimits, SimulationError

PROFILE = json.loads((Path(__file__).parent / "fixtures" / "compat" / "profile_v020.json").read_text())
BASE = {"temperature_K": 343.15, "cathode_pressure_atm": 1.5}
PV = {q["name"]: q["value"] for q in PROFILE["parameters"]}


def test_sensitivities_match_analytic_derivatives():
    j, T = 0.5, BASE["temperature_K"]
    r = run_sensitivity(PROFILE, BASE, [
        {"kind": "param", "name": "xi1", "lo": PV["xi1"] - 0.01, "hi": PV["xi1"] + 0.01},
        {"kind": "param", "name": "R_mem_ref_ohm_cm2", "lo": 0.9 * PV["R_mem_ref_ohm_cm2"], "hi": 1.1 * PV["R_mem_ref_ohm_cm2"]},
        {"kind": "oper", "name": "oxygen_fraction", "lo": 0.19, "hi": 0.23}], "V_cell", j)
    d = {x["variable"]: x for x in r.tables["sensibilidades"]}
    assert d["xi1"]["dR_dx"] == pytest.approx(1.0, abs=1e-8)                                   # ∂V/∂ξ1 = 1
    assert d["R_mem_ref_ohm_cm2"]["dR_dx"] == pytest.approx(-j * (T / PV["T_ref"]) ** PV["R_mem_temperature_exponent"], rel=1e-8)
    y = PV["oxygen_fraction_air"]
    assert d["oxygen_fraction"]["dR_dx"] == pytest.approx(PV["R"] * T / (4 * PV["F"] * y) + PV["xi4"] * T / y, rel=1e-7)
    v0 = r.kpi("R0")
    assert d["xi1"]["elasticidad"] == pytest.approx(PV["xi1"] / v0, rel=1e-7)
    assert d["xi1"]["tipo"].startswith("parámetro") and d["oxygen_fraction"]["tipo"].startswith("operacional")
    assert any("NO" in h or "no una cuantificación" in h for h in r.hypotheses)


def test_sensitivity_guards_and_dominant_variable():
    r = run_sensitivity(PROFILE, BASE, [{"kind": "oper", "name": "temperature_K", "lo": 350, "hi": 360},
                                        {"kind": "param", "name": "concentration_b_cm2_A", "lo": 7, "hi": 8}], "P_max")
    d = {x["variable"]: x for x in r.tables["sensibilidades"]}
    assert d["temperature_K"]["elasticidad"] is None and "fuera del intervalo" in d["temperature_K"]["nota"]
    assert any("no robusta" in w for w in r.warnings)                        # parámetro débilmente identificado
    assert r.context["dominant"] == r.context["ranking"][0]
    with pytest.raises(SimulationError, match="intervalo"):
        run_sensitivity(PROFILE, BASE, [{"kind": "oper", "name": "temperature_K", "lo": 360, "hi": 350}], "P_max")


def test_scenarios_common_domain_reference_and_consistency():
    sc = [dict(name="Ref", **BASE), dict(name="T+10", temperature_K=353.15, cathode_pressure_atm=1.5),
          dict(name="yO2", **BASE, oxygen_fraction=0.30),
          dict(name="Rmem", **BASE, params={"R_mem_ref_ohm_cm2": 1.2 * PV["R_mem_ref_ohm_cm2"]}),
          dict(name="off", active=False, **BASE)]
    r = run_scenarios(PROFILE, sc, "Ref", 0.5)
    assert r.series["scenarios"] == ["Ref", "T+10", "yO2", "Rmem"]                    # inactivos fuera
    assert all(v == 0 for v in r.series["Ref"]["dV_V"] if v is not None)
    ind = {x["escenario"]: x for x in r.tables["indicadores"]}
    m = build_model(PROFILE, BASE)
    assert ind["Ref"]["P_max_W"] == pytest.approx(m.capacity()["P_max_W"], rel=1e-12)    # = Bancada 04 / capacidad
    b4 = run_optimization(m, "max_potencia")
    assert ind["Ref"]["P_max_W"] == pytest.approx(b4.context["selected"]["P_W"], rel=1e-9)
    assert ind["Ref"]["validez"] == "CONDICIÓN CALIBRADA" and ind["yO2"]["validez"] == "EXTRAPOLADO"
    assert ind["Rmem"]["perturbacion_matematica"] and ind["Rmem"]["P_max_W"] < ind["Ref"]["P_max_W"]
    assert ind["Rmem"]["V_celda_jref_V"] == pytest.approx(ind["Ref"]["V_celda_jref_V"]
                                                          - 0.5 * 0.2 * PV["R_mem_ref_ohm_cm2"] * (343.15 / PV["T_ref"]) ** PV["R_mem_temperature_exponent"], rel=1e-9)
    with pytest.raises(SimulationError, match="únicos"):
        run_scenarios(PROFILE, [dict(name="A", **BASE), dict(name="A", **BASE)], "A", 0.5)


def test_uncertainty_only_with_statistics_and_reproducible():
    ok, _, _ = uncertainty_available(PROFILE)
    assert ok
    a = run_uncertainty(PROFILE, BASE, 0.5, n_samples=150, seed=1)
    b = run_uncertainty(PROFILE, BASE, 0.5, n_samples=150, seed=1)
    assert a.series["Pmax_samples"] == b.series["Pmax_samples"]
    lo, hi, nom = (np.array(a.series[k], float) for k in ("V_p025", "V_p975", "V_nominal"))
    assert np.all(lo <= nom + 1e-9) and np.all(nom <= hi + 1e-9)
    assert any("INCERTIDUMBRE ESTADÍSTICA" in h for h in a.hypotheses) and any("SUBESTIMA" in w for w in a.warnings)
    bad = copy.deepcopy(PROFILE)
    bad["diagnostics"].pop("correlation")
    with pytest.raises(SimulationError, match="perturbación determinista"):
        run_uncertainty(bad, BASE, 0.5)


def test_map_masks_extrapolation_and_bench04_consistency():
    lim = OperatingLimits(current_max_A=250.0, source="prueba")
    r = run_map(PROFILE, "j", "T", [0.02, 1.6], [290, 380], 80, 25, {"cathode_pressure_atm": 1.5}, lim, objective="max_potencia")
    s = r.series
    x, y, cat = np.array(s["x"]), np.array(s["y"]), np.array(s["category"])
    I = np.array([[np.nan if v is None else v for v in row] for row in s["I"]])
    assert np.all(cat[I > 250 + 1e-9] <= 1)                                   # viola I_máx → inadmisible
    calc = cat >= 1
    assert np.all((cat[:, x > PROFILE["domain"]["calibration"]["j_A_cm2"][1]] != 3))   # j fuera de rango: nunca «calibrado»
    assert np.all(cat[(y < 298.15) | (y > 373.15), :] != 3)
    P = np.array([[np.nan if v is None else v for v in row] for row in s["P"]])
    assert np.all(np.isnan(P[cat == 0]))                                      # no calculables: sin valor inventado
    opt = r.context["optimum"]
    b4 = run_optimization(build_model(PROFILE, {"temperature_K": opt["y"], "cathode_pressure_atm": 1.5}), "max_potencia", lim)
    assert opt["P_W"] == b4.context["selected"]["P_W"] and opt["j_A_cm2"] == b4.context["selected"]["j_A_cm2"]
    assert opt["I_A"] == pytest.approx(250.0) and "corriente máxima" in " ".join(opt["active_constraints"])
    d = point_details(PROFILE, "j", "T", 0.7, 350.0, {"cathode_pressure_atm": 1.5}, lim)
    m = build_model(PROFILE, {"temperature_K": 350.0, "cathode_pressure_atm": 1.5})
    assert d["P_W"] == pytest.approx(float(m.power(0.7)), rel=1e-12) and d["category"] == "Dominio calibrado"


def test_tp_map_and_limits_of_resolution():
    r = run_map(PROFILE, "T", "P", [298.15, 373.15], [1, 5], 16, 9, {"j_A_cm2": 0.5})
    assert "APROXIMADO" in r.context["optimum_note"] and r.context["optimum"]["P_W"] > 0
    assert np.isfinite(np.array(r.series["P_max"], float)).all()
    with pytest.raises(SimulationError, match="supera el máximo"):
        run_map(PROFILE, "T", "P", [298, 373], [1, 5], 100, 100, {"j_A_cm2": 0.5})
    with pytest.raises(SimulationError, match="no admitida"):
        run_map(PROFILE, "T", "j", [298, 373], [0.1, 1], 10, 10, {})


def test_exports_runner_and_persistence_for_new_benches():
    from workspace.model import Workspace
    from workspace.project_io import import_v020_profile
    cfg = {"x_axis": "j", "y_axis": "P", "x_range": [0.02, 1.4], "y_range": [1, 5], "nx": 30, "ny": 8,
           "fixed": {"temperature_K": 343.15}, "objective": "max_potencia"}
    assert runner.missing("mapa", cfg) == [] and runner.missing("sensibilidad", {"mode": "sensibilidad"}) == ["cond", "variables", "response"]
    r = runner.run("mapa", PROFILE, cfg)
    rec = {"id": "exp-m", "name": "m", "bench": "mapa", "profile_id": PROFILE["profile_id"], "device_id": "d",
           "calibration_id": "c", "created_utc": "t", "content_sha256": "0", "result": r.to_dict()}
    import pandas as pd
    x = pd.ExcelFile(io.BytesIO(to_xlsx(r, rec)))
    assert {"Matriz P", "Matriz category", "Indicadores"} <= set(x.sheet_names)
    z = zipfile.ZipFile(io.BytesIO(experiment_zip(rec, PROFILE)))
    df = pd.read_csv(io.BytesIO(z.read("datos.csv")))
    assert len(df) == 30 * 8 and {"x", "y", "categoria", "P"} <= set(df.columns)
    assert {"figuras/mapa.png", "figuras/categorias.svg", "informe.pdf"} <= set(z.namelist())
    ws = Workspace()
    m = import_v020_profile(ws, json.dumps(PROFILE).encode(), "p.json")
    ex = ws.add_experiment(m.device_id, m.calibration_id, "mapa", "mapa", r.to_dict())
    ws2, problems = Workspace.from_records(ws.all_records())
    assert not problems and ws2.experiments[ex.id].result["series"]["category"] == r.series["category"]


def test_motor2_report_does_not_change_global_matplotlib_style():
    import matplotlib
    before = {k: matplotlib.rcParams[k] for k in ("axes.grid", "font.size", "axes.spines.top")}
    import simulation.report as rep
    r = runner.run("sensibilidad", PROFILE, {"mode": "escenarios", "scenarios": [dict(name="Ref", **BASE)], "reference": "Ref",
                                             "j_ref": 0.5})
    rep.figures(r)
    assert {k: matplotlib.rcParams[k] for k in before} == before        # Motor 1 y digitalizador no se ven afectados
