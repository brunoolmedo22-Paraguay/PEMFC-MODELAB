"""Perfiles: contenido, reimportación, ZIP y seguridad científica (A08, A09, A10, A12)."""
import copy
import io
import json
import zipfile

import numpy as np
import pytest

from identification import examples as ex
from identification.optimizer import preset_generic, preset_otekon, run_identification
from identification.profiles import ProfileError, build_profile, evaluate_profile, load_profile, profile_to_json
from identification.reporting import experiment_zip
from pemfc_core import model as core
from pemfc_core.schemas import validate_profile_dict


@pytest.fixture(scope="module")
def stack_case():
    dev = ex.equivalent_65kw_device()
    curves = [ex.load_65kw_curve(dev)]
    r = run_identification(curves, preset_generic(curves))
    return curves, dev, r, build_profile(r, curves, dev)


def test_profile_contents(stack_case):
    curves, dev, r, prof = stack_case
    assert validate_profile_dict(prof).ok
    assert prof["engine"]["model_id"] == core.MODEL_ID and prof["engine"]["equations"]
    assert prof["engine"]["units"]["current_density"] == "A/cm²"
    origins = {p["name"]: p["origin"] for p in prof["parameters"]}
    assert {origins[n] for n in r.free_names} == {"IDENTIFICADO"}
    assert origins["xi2"] == "ASUMIDO"
    d = prof["datasets"][0]
    assert d["source_sha256"] == ex.sha256_bytes((ex.EXAMPLES / "equivalent_65kw" / "curve_raw.csv").read_bytes())
    assert len(d["points"]["j_A_cm2"]) == 4 and d["transformations"]
    assert prof["device"]["n_cells"] == 210 and prof["fit"]["metrics_stack_V"]["rmse_V"] > 0
    assert prof["provenance"]["datasheet_used_in_objective"] is False
    assert prof["status"]["predictive_capability"] == "NO DEMOSTRADA"
    assert prof["fit"]["config"]["seed"] == 20260720
    json.dumps(prof)  # serializable


def test_roundtrip_reproduces_curve(stack_case):
    curves, dev, r, prof = stack_case
    loaded = load_profile(profile_to_json(prof))
    assert loaded.reproduction_ok and loaded.max_reproduction_error_V <= 1e-12 and loaded.engine_match
    c = curves[0]
    assert np.array_equal(core.cell_voltage(c.j_A_cm2, loaded.params, c.conditions),
                          core.cell_voltage(c.j_A_cm2, r.params, c.conditions))


def test_tampered_profile_detected(stack_case):
    prof = copy.deepcopy(stack_case[3])
    next(p for p in prof["parameters"] if p["name"] == "xi1")["value"] += 0.01
    loaded = load_profile(prof)
    assert not loaded.reproduction_ok


def test_schema_rejections(stack_case):
    prof = stack_case[3]
    bad = copy.deepcopy(prof); bad["datasets"] = []
    assert any("sin curva" in e for e in validate_profile_dict(bad).errors)
    bad = copy.deepcopy(prof); bad["status"]["code"] = "VALIDADO_EXPERIMENTALMENTE"
    assert not validate_profile_dict(bad).ok
    bad = copy.deepcopy(prof); bad["schema"] = "otro"
    with pytest.raises(ProfileError):
        load_profile(bad)
    with pytest.raises(ProfileError):
        load_profile("{no es json")
    bad = copy.deepcopy(prof); bad["engine"]["model_id"] = "otro_modelo"
    with pytest.raises(ProfileError):
        load_profile(bad)


def test_no_profile_without_calibration_curve(stack_case):
    curves, dev, r, _ = stack_case
    val = copy.deepcopy(curves)
    val[0].meta.role = "validación"
    with pytest.raises(ProfileError, match="sin curva"):
        build_profile(r, val, dev)


def test_nonconverged_profile_not_usable():
    curves = ex.load_otekon_curves()
    cfg = preset_otekon(); cfg.n_starts, cfg.max_nfev = 1, 50
    r = run_identification(curves, cfg)
    prof = build_profile(r, curves, ex.otekon_device())
    assert prof["status"]["code"] == "NO_CONVERGIDO" and prof["status"]["usable_for_simulation"] is False
    assert any("no es utilizable" in m for m in load_profile(prof).messages)


def test_experiment_zip(stack_case):
    curves, dev, r, prof = stack_case
    z = zipfile.ZipFile(io.BytesIO(experiment_zip(prof, r, curves, dev, {"curve_raw.csv": b"a,b"})))
    names = {n.split("/", 1)[1] for n in z.namelist()}
    for required in ("profile.json", "report.md", "manifest.json", "data/original/curve_raw.csv",
                     "data/normalized/chen2024_65kW.csv", "results/fit_points.csv", "results/model_curves.csv",
                     "results/parameters.csv", "results/optimization_runs.csv", "figures/polarization.png",
                     "figures/residuals.png", "figures/losses.png", "figures/multistart.png"):
        assert required in names, required
    root = z.namelist()[0].split("/")[0]
    assert z.read(f"{root}/figures/polarization.png")[:4] == b"\x89PNG"
    report = z.read(f"{root}/report.md").decode()
    assert "AJUSTADO_A_CURVA" in report and "Stack equivalente 65 kW" in report
    assert "capacidad predictiva NO está demostrada" in report
    assert json.loads(z.read(f"{root}/profile.json"))["profile_id"] == prof["profile_id"]


def test_evaluate_profile_flags_extrapolation(stack_case):
    loaded = load_profile(stack_case[3])
    c = loaded.conditions("chen2024_65kW")
    out = evaluate_profile(loaded, [1.0, 2.5], c)
    assert list(out["extrapolated"]) == [False, True]
    out = evaluate_profile(loaded, [1.0], core.OperatingConditions(300.0, c.cathode_pressure_atm, c.p_h2_atm))
    assert bool(out["extrapolated"][0])


def test_profile_id_deterministic(stack_case):
    curves, dev, r, prof = stack_case
    assert build_profile(r, curves, dev)["profile_id"] == prof["profile_id"]
