"""Motor 2: verificaciones numéricas y casos de referencia (perfil real OTEKON exportado por v0.2.0)."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from simulation import timeseries as ts
from simulation.benches import (BENCHES, OBJECTIVES, run_hydrogen, run_load_following, run_optimization,
                                run_reproduction)
from simulation.stack import F, M_H2, VM_NORMAL, OperatingLimits, SimulationError, StackModel, flow_to_mol_s

PROFILE = json.loads((Path(__file__).parent / "fixtures" / "compat" / "profile_v020.json").read_text())
N, A = 41, 232.0


@pytest.fixture(scope="module")
def model():
    return StackModel.from_profile(PROFILE, 343.15, 1.0)


def test_reproduction_identical_to_motor1_metrics():
    r = run_reproduction(PROFILE)
    stored = {m["curve_id"]: m for m in PROFILE["fit"]["metrics_by_curve"]}
    for m in r.tables["por_curva"]:
        assert m["rmse_V"] == stored[m["curve_id"]]["rmse_V"] and m["bias_V"] == stored[m["curve_id"]]["bias_V"]
    assert r.kpi("rmse_V") == PROFILE["fit"]["metrics_calibration"]["rmse_V"]
    assert r.kpi("max_delta_motor1_V") == 0.0 and r.context["consistent_with_motor1"]
    assert r.context["evaluation_kind"] == "REPRODUCCIÓN DE CALIBRACIÓN"
    assert any("NO demuestra capacidad predictiva" in h for h in r.hypotheses)
    s = r.series["tensao_298K"]
    assert np.allclose(np.array(s["P_obs_W"]), N * np.array(s["V_obs"]) * np.array(s["j_obs"]) * A)


def test_unit_conventions_faraday_and_power(model):
    assert float(model.h2_mol_s(100.0)) == pytest.approx(N * 100 / (2 * F), rel=1e-15)
    op = model.operating_point(0.5)
    assert op["I_A"] == pytest.approx(0.5 * A) and op["P_W"] == pytest.approx(N * op["V_cell_V"] * op["I_A"])
    assert op["eta"] == pytest.approx(op["V_cell_V"] / 1.25325, rel=2e-4)                # LHV/2F ≈ 1,2532 V
    assert op["SFC_g_kWh"] == pytest.approx(M_H2 * 1e3 * 3600 * 1000 / (2 * F * op["V_cell_V"]), rel=1e-12)
    assert float(flow_to_mol_s(VM_NORMAL * 60, "NL/min")) == pytest.approx(1.0)
    assert float(flow_to_mol_s(M_H2 * 1e3, "g/s")) == pytest.approx(1.0)


def test_capacity_interior_maximum_and_power_inversion(model):
    cap = model.capacity()
    g = np.linspace(model.j_lo, model.j_hi, 200001)
    assert cap["P_max_W"] == pytest.approx(float(np.max(model.power(g))), rel=1e-9) and cap["interior_max"]
    j = model.j_for_power(3000.0)
    assert float(model.power(j)) == pytest.approx(3000.0, rel=1e-12) and j < cap["j_at_Pmax"]
    lim = model.capacity(OperatingLimits(current_max_A=150.0))
    assert lim["I_at_Pmax_A"] == pytest.approx(150.0) and "corriente máxima" in lim["binding"]


def _seq(levels, durs, interp="escalonado"):
    t, v = ts.sequence(levels, durs)
    return ts.validate(t, v, "potencia", "s", "W", "prueba", interp)


def test_load_following_energy_balance_and_deficit(model):
    d = _seq([500, 2000, 9000, 0, 4000], [60, 60, 60, 30, 60])
    r = run_load_following(model, d)
    t = np.array(r.series["t_s"])
    dem, dl, df = (np.array(r.series[k]) for k in ("P_dem_W", "P_del_W", "deficit_W"))
    assert r.kpi("E_dem") == pytest.approx(0.930e6 / 3.6e6, rel=2e-3)      # 930 kJ exactos salvo discretización del escalón
    assert np.allclose(dl + df, dem, atol=1e-6) and np.all(dl <= r.kpi("P_avail") + 1e-6)
    assert r.kpi("E_del") + r.kpi("E_uns") == pytest.approx(r.kpi("E_dem"), rel=1e-12)
    ev = [e for e in r.events if e["type"] == "incumplimiento_demanda"]
    assert len(ev) == 1 and ev[0]["cause"] == "capacidad" and 120 <= ev[0]["t_start_s"] <= 121
    assert ev[0]["max_magnitude"] == pytest.approx(9000 - r.kpi("P_avail"), rel=1e-6)
    h2 = np.trapezoid(N * np.array(r.series["I_A"]) / (2 * F), t) * M_H2 * 1e3
    assert r.kpi("H2_g") == pytest.approx(h2, rel=1e-12)
    assert any("Sin restricción de rampa evaluada" in w for w in r.warnings)
    assert r.kpi("n_ramp_events") is None                                 # no se inventa información de rampa
    i = np.array(r.series["I_A"])
    assert np.all(i[dem == 0] == 0)                                       # P = 0 → stack sin carga, sin consumo


def test_ramp_limit_applied_and_reported(model):
    d = _seq([0, 4000], [10, 100])
    r = run_load_following(model, d, OperatingLimits(ramp_up_W_s=100.0, source="ensayo"))
    t, p = np.array(r.series["t_s"]), np.array(r.series["P_del_W"])
    assert np.max(np.diff(p) / np.diff(t)) <= 100.0 + 1e-6
    assert r.kpi("n_ramp_events") >= 1 and any(e["cause"] == "rampa" for e in r.events if e["type"] == "incumplimiento_demanda")
    ideal = np.array(r.series["P_del_W_ideal"])
    assert ideal[np.searchsorted(t, 11)] == pytest.approx(4000)           # el ideal no tiene rampa


def test_hydrogen_feed_vs_consumption_and_policies(model):
    feed = ts.validate([0, 100, 200], [30, 30, 5], "caudal_H2", "s", "NL/min", "prueba", "escalonado")
    with pytest.raises(SimulationError, match="utilización máxima"):
        run_hydrogen(model, feed, "max_potencia")
    r = run_hydrogen(model, feed, "max_potencia", u_max=0.8)
    fed, cons = np.array(r.series["H2_fed_g_s"]), np.array(r.series["H2_cons_g_s"])
    assert np.all(cons <= 0.8 * fed + 1e-12)
    low = np.array(r.series["t_s"]) > 100.5
    assert np.allclose(cons[low], 0.8 * fed[low]) and any(e["type"] == "limitado_por_combustible" for e in r.events)
    u = run_hydrogen(model, feed, "utilizacion", value=0.6)
    assert np.allclose(np.array(u.series["H2_cons_g_s"]), 0.6 * np.array(u.series["H2_fed_g_s"]))
    c = run_hydrogen(model, feed, "corriente", value=50.0)
    assert np.allclose(np.array(c.series["I_A"])[~low], 50.0)
    assert c.kpi("eta_fed") == pytest.approx(c.kpi("eta_cons") * c.kpi("u_mean") / 100, rel=1e-9)
    with pytest.raises(SimulationError):
        run_hydrogen(model, feed, "utilizacion", value=1.2)


def test_optimization_objectives_feasible_and_explained(model):
    pmax = run_optimization(model, "max_potencia")
    assert pmax.context["selected"]["P_W"] == pytest.approx(model.capacity()["P_max_W"], rel=1e-9)
    triv = run_optimization(model, "max_eficiencia")
    assert any("trivial" in w for w in triv.warnings)
    e = run_optimization(model, "max_eficiencia", p_min_useful_W=1000.0)
    assert e.context["selected"]["P_W"] == pytest.approx(1000.0, rel=1e-9) and "potencia mínima útil" in e.context["active_constraints"]
    s = run_optimization(model, "min_consumo", p_min_useful_W=1000.0)
    assert s.context["selected"]["j_A_cm2"] == pytest.approx(e.context["selected"]["j_A_cm2"], rel=1e-9)
    assert any("EQUIVALENTE" in h for h in s.hypotheses)
    tg = run_optimization(model, "potencia_objetivo", p_target_W=5000.0)
    assert tg.context["selected"]["P_W"] == pytest.approx(5000.0, rel=1e-9) and tg.context["selected"]["j_A_cm2"] < pmax.context["selected"]["j_A_cm2"]
    with pytest.raises(SimulationError, match="supera la máxima"):
        run_optimization(model, "potencia_objetivo", p_target_W=1e5)
    lim = run_optimization(model, "max_potencia", OperatingLimits(current_max_A=150.0))
    assert lim.context["selected"]["I_A"] == pytest.approx(150.0) and lim.context["active_constraints"]
    par = run_optimization(model, "compromiso")
    fr = par.series["frontier_idx"]
    P, eta = np.array(par.series["P_W"])[fr], np.array(par.series["eta"])[fr]
    assert np.all(np.diff(P) > 0) and np.all(np.diff(eta) < 0)            # frontera: ningún punto domina a otro


def test_inputs_never_invented():
    bad = dict(PROFILE, device=dict(PROFILE["device"], n_cells=None))
    with pytest.raises(SimulationError, match="N_celdas"):
        StackModel.from_profile(bad, 343.15, 1.0)
    with pytest.raises(SimulationError, match="varias condiciones"):
        StackModel.from_profile(PROFILE)
    m = StackModel.from_profile(PROFILE, 330.0, 2.0)
    assert any("no coinciden" in w for w in m.warnings)
    m = StackModel.from_profile(PROFILE, 400.0, 2.0)
    assert any("EXTRAPOLACIÓN" in w for w in m.warnings)
    for t, v, msg in (([0, 1, 1], [1, 2, 3], "duplicados"), ([0, 2, 1], [1, 2, 3], "creciente"),
                      ([0, 1, 2], [1, None, 3], "ausentes"), ([0, 1], [-1, 2], "negativos")):
        with pytest.raises(SimulationError, match=msg):
            ts.validate(t, v, "potencia", "s", "W", "x")


def test_generators_and_units():
    s = ts.validate(*ts.constant(2.0, 10.0), "potencia", "min", "kW", "x")
    assert s.duration_s == 600 and s.values[0] == 2000.0
    t, v = ts.ramp(0, 10, 2, 8, 10)
    assert v[0] == 0 and v[-1] == 10
    t, v = ts.periodic(5, 2, 10, 30, "cuadrada")
    assert max(v) == 7 and min(v) == 3
    assert set(BENCHES) == {"reproduccion", "carga", "hidrogeno", "optimizacion"} and len(OBJECTIVES) == 5


def test_experiments_persist_sealed_and_travel_with_device():
    from workspace.model import Workspace, WorkspaceError
    from workspace.project_io import export_device, import_project, import_v020_profile
    ws = Workspace()
    m = import_v020_profile(ws, json.dumps(PROFILE).encode(), "p.json")
    res = run_reproduction(ws.calibrations[m.calibration_id].profile).to_dict()
    ex = ws.add_experiment(m.device_id, m.calibration_id, "reproduccion", "Reproducción OTEKON", res)
    assert ws.device_experiments(m.device_id) == [ex] and ex.profile_id == PROFILE["profile_id"]
    recs = ws.all_records()
    ws2, problems = Workspace.from_records(recs)
    assert not problems and ws2.experiments[ex.id].result == ex.result
    bad = dict(recs)
    bad[f"experiment:{ex.id}"] = dict(recs[f"experiment:{ex.id}"], name="alterado")
    _, problems = Workspace.from_records(bad)
    assert any("alterado" in p for p in problems)
    name, data = export_device(ws, m.device_id)
    ws3 = Workspace()
    rep = import_project(ws3, data)
    assert f"experiment:{ex.id}" in rep.added and ws3.experiments[ex.id].content_sha256 == ex.content_sha256
    summary = ws.delete_device(m.device_id, ws.devices[m.device_id].name)
    assert summary["experiments"] == 1 and not ws.experiments
    with pytest.raises(WorkspaceError):
        ws3.add_experiment(m.device_id, "cal-inexistente", "carga", "x", {})


def test_exports_all_benches_zip_pdf_csv_consistent(model):
    import io as _io
    import zipfile as _zf
    import pandas as pd
    from simulation.report import experiment_zip, study_zip, to_csv
    from simulation.benches import BenchResult
    d = _seq([1000, 7000, 2000], [30, 30, 30])
    feed = ts.validate([0, 60], [25, 25], "caudal_H2", "s", "NL/min", "x")
    results = [run_reproduction(PROFILE), run_load_following(model, d), run_hydrogen(model, feed, "potencia", 3000.0),
               run_optimization(model, "compromiso")]
    recs = []
    for r in results:
        rec = {"id": f"exp-{r.bench}", "name": f"Prueba {r.bench}", "bench": r.bench, "profile_id": PROFILE["profile_id"],
               "device_id": "dev-x", "calibration_id": "cal-x", "created_utc": "2026-11-01T00:00:00Z",
               "content_sha256": "0" * 64, "result": r.to_dict()}
        recs.append(rec)
        data = experiment_zip(rec, PROFILE)
        z = _zf.ZipFile(_io.BytesIO(data))
        names = set(z.namelist())
        assert {"LEEME.txt", "experimento.json", "datos.csv", "datos.xlsx", "informe.pdf", "perfil.json"} <= names
        assert any(n.endswith(".png") for n in names) and any(n.endswith(".svg") for n in names)
        assert z.read("informe.pdf")[:5] == b"%PDF-" and len(z.read("informe.pdf")) > 20000
        assert z.read("datos.csv") == to_csv(BenchResult.from_dict(rec["result"]))
        js = json.loads(z.read("experimento.json"))
        assert js["result"]["kpis"] == json.loads(json.dumps(r.to_dict()["kpis"]))
        if r.bench == "carga":
            df = pd.read_csv(_io.BytesIO(z.read("datos.csv")))
            assert np.array_equal(df["P_del_W"].to_numpy(), np.array(r.series["P_del_W"]))
            x = pd.read_excel(_io.BytesIO(z.read("datos.xlsx")), sheet_name="Indicadores")
            assert "Energía demandada" in set(x["indicador"])
    s = _zf.ZipFile(_io.BytesIO(study_zip(recs, [{"bench": "hidrogeno", "reason": "sin caudal"}], {PROFILE["profile_id"]: PROFILE})))
    assert "resumen_estudio.csv" in s.namelist() and len([n for n in s.namelist() if n.endswith(".zip")]) == 4
    assert b"omitida" in s.read("resumen_estudio.csv")
