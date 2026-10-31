"""Identificador generalizado (A04, A05, A06) y estados del ajuste."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import FIXTURES
from identification import examples as ex
from identification.datasets import build_curve, ConditionInput
from identification.optimizer import (
    FitConfigError, preset_generic, preset_otekon, run_identification, structural_checks,
)
from pemfc_core import model as core
from pemfc_core.parameters import FITTABLE_PARAMETERS, OTEKON_REFERENCE_PARAMS as P
from pemfc_core.schemas import CurveMetadata, DeviceInfo

# Tolerancias de reproducción OTEKON (justificación en docs/VERIFICACION.md):
# mismo modelo y mismo algoritmo => diferencias solo de redondeo. 1 µV es 3000 veces
# menor que la incertidumbre de digitalización OTEKON (3 mV) y 0,07 % del RMSE.
RMSE_TOL_V = 1e-6
CURVE_TOL_V = 1e-5


def test_otekon_reproduces_original_execution(otekon_result):
    curves, r = otekon_result
    base = json.loads((FIXTURES / "otekon_baseline" / "optimization_summary.json").read_text())
    assert r.status == "AJUSTADO_A_CURVA"
    assert abs(r.metrics_global["rmse_V"] - base["voltage_rmse_V"]) <= RMSE_TOL_V
    assert r.identifiability["condition_number"] == pytest.approx(base["jacobian_condition_number_scaled"], rel=0.01)
    ident = pd.read_csv(FIXTURES / "otekon_baseline" / "identified_parameters.csv").set_index("parameter")
    ref = P.copy_with(**{n: ident.loc[n, "identified_value"] for n in FITTABLE_PARAMETERS})
    for c in curves:
        diff = core.cell_voltage(c.j_A_cm2, r.params, c.conditions) - core.cell_voltage(c.j_A_cm2, ref, c.conditions)
        assert np.max(np.abs(diff)) <= CURVE_TOL_V
    runs = pd.read_csv(FIXTURES / "otekon_baseline" / "optimization_runs.csv")
    assert len(r.runs) == len(runs) == 16
    assert np.allclose(r.runs.rmse_V, runs.rmse_voltage_V, atol=RMSE_TOL_V)


def test_otekon_original_residuals_reproduced(otekon_result):
    _, r = otekon_result
    base = pd.read_csv(FIXTURES / "otekon_baseline" / "optimization_residuals.csv")
    assert np.allclose(r.residuals.residual_V.to_numpy(), base.residual_V.to_numpy(), atol=CURVE_TOL_V)


def test_otekon_diagnostics_flag_concentration_correlation(otekon_result):
    _, r = otekon_result
    rows = r.identifiability["parameters"].set_index("parameter")
    assert rows.loc["concentration_a_ref_V", "identifiability"] != "IDENTIFICADO_LOCALMENTE"
    assert rows.loc["xi1", "identifiability"] == "IDENTIFICADO_LOCALMENTE"


def test_synthetic_known_parameters():
    """Caso sintético (NO validación experimental): reproduce la curva verdadera y avisa
    que a_ref y b no se separan con una sola curva."""
    c = ex.synthetic_curve(noise_sigma_V=0.002, seed=7)
    r = run_identification([c], preset_generic([c]))
    assert r.status == "AJUSTADO_A_CURVA"
    assert 0.001 < r.metrics_global["rmse_V"] < 0.003
    truth = core.cell_voltage(c.j_A_cm2, P, c.conditions)
    fit = core.cell_voltage(c.j_A_cm2, r.params, c.conditions)
    assert np.max(np.abs(fit - truth)) < 0.004
    weak = set(r.identifiability["parameters"].query("identifiability != 'IDENTIFICADO_LOCALMENTE'").parameter)
    assert {"concentration_a_ref_V", "concentration_b_cm2_A"} <= weak
    assert any("Una sola curva" in w for w in r.warnings)


def test_synthetic_noise_free_recovers_curve_exactly():
    c = ex.synthetic_curve(noise_sigma_V=1e-12, seed=1)
    r = run_identification([c], preset_generic([c]))
    assert r.metrics_global["rmse_V"] < 1e-6


def test_single_curve_cannot_free_all_nine():
    c = ex.synthetic_curve()
    with pytest.raises(FitConfigError) as e:
        run_identification([c], preset_otekon())
    msgs = " ".join(i.message for i in e.value.issues)
    for sym in ("ξ2", "ξ4", "n_R", "a_T"):
        assert sym in msgs


def test_more_free_parameters_than_points_rejected():
    c = ex.synthetic_curve(j=[0.1, 0.4, 0.8])
    cfg = preset_generic([c])
    for n in ("xi1", "xi3", "R_mem_ref_ohm_cm2", "concentration_b_cm2_A"):
        cfg.settings[n].free = True
    with pytest.raises(FitConfigError, match="indeterminado"):
        run_identification([c], cfg)


def test_priors_require_declared_sigma():
    c = ex.synthetic_curve()
    cfg = preset_generic([c])
    cfg.settings["xi1"].prior_mean, cfg.settings["xi1"].prior_sigma = -0.67, 0.05
    assert any("σ_V" in i.message for i in structural_checks([c], cfg) if i.level == "error")
    c2 = ex.synthetic_curve(declare_sigma=True)
    r = run_identification([c2], cfg)
    assert r.sigma_declared and r.status == "AJUSTADO_A_CURVA"


def test_prior_makes_structurally_weak_parameter_admissible():
    c = ex.synthetic_curve(declare_sigma=True)
    cfg = preset_generic([c])
    cfg.settings["xi2"].free = True
    with pytest.raises(FitConfigError):
        run_identification([c], cfg)
    cfg.settings["xi2"].prior_mean, cfg.settings["xi2"].prior_sigma = P.xi2, 1e-4
    r = run_identification([c], cfg)
    row = r.identifiability["parameters"].set_index("parameter").loc["xi2"]
    assert row["identifiability"] != "IDENTIFICADO_LOCALMENTE"


def test_65kw_stack_fit_and_weak_resistance():
    k = ex.load_65kw_curve()
    cfg = preset_generic([k])
    assert len(cfg.free_names()) == 3 and "xi1" in cfg.free_names()
    r = run_identification([k], cfg)
    assert r.status == "AJUSTADO_A_CURVA"
    assert r.metrics_global["rmse_V"] < 0.010
    rows = r.identifiability["parameters"]
    assert (rows.identifiability != "IDENTIFICADO_LOCALMENTE").any()


def test_insufficient_fit_reported():
    c = ex.synthetic_curve(noise_sigma_V=0.002)
    cfg = preset_generic([c])
    cfg.rmse_threshold_V = 0.0005
    r = run_identification([c], cfg)
    assert r.status == "AJUSTE_INSUFICIENTE"


def test_wrong_model_structure_insufficient():
    c = ex.synthetic_curve()
    cfg = preset_generic([c])
    for n in FITTABLE_PARAMETERS:
        cfg.settings[n].free = n == "xi1"
    cfg.settings["R_mem_ref_ohm_cm2"].value = 1.5
    r = run_identification([c], cfg)
    assert r.status == "AJUSTE_INSUFICIENTE"


def test_non_convergence_reported():
    curves = ex.load_otekon_curves()
    cfg = preset_otekon()
    cfg.n_starts, cfg.max_nfev = 1, 50
    r = run_identification(curves, cfg)
    assert r.status == "NO_CONVERGIDO"
    assert not r.runs.success.any()


def test_validation_with_synthetic_data_cannot_validate_experimentally():
    dev = DeviceInfo(name="s")
    cal = ex.synthetic_curve(device=dev)
    val = ex.synthetic_curve(device=dev, temperature_K=343.15, seed=99, curve_id="v", role="validación",
                             j=[0.05, 0.3, 0.6, 0.9])
    r = run_identification([cal, val], preset_generic([cal, val]))
    assert r.validation["status"] == "VALIDACION_CON_DATOS_NO_EXPERIMENTALES"
    assert r.status == "AJUSTADO_A_CURVA"


def test_holdout_at_same_condition_does_not_validate():
    """pressao_5atm repite la condición (y la curva publicada) de tensao_373K: no es independiente."""
    curves = ex.load_otekon_curves()
    curves[3].meta.role = "validación"
    r = run_identification(curves, preset_generic(curves))
    assert r.validation["status"] == "VALIDACION_SOLO_MISMA_CONDICION"
    assert r.status == "AJUSTADO_A_CURVA"
    assert any("misma condición" in n for n in r.validation["notes"])


def test_holdout_validation_at_new_condition():
    """Verifica el MECANISMO de validación. No es una validación científica de OTEKON: los
    parámetros fijados (p. ej. ξ4) toman valores de referencia identificados con las 4 curvas,
    incluida la reservada aquí."""
    curves = ex.load_otekon_curves()
    curves[2].meta.role = "validación"  # 373,15 K y 1 atm: condición ausente en la calibración
    cfg = preset_generic(curves)
    assert "xi4" not in cfg.free_names()  # una sola presión en calibración
    r = run_identification(curves, cfg)
    assert r.validation["status"] == "VALIDACION_SUPERADA", r.validation
    assert r.status == "VALIDADO_EXPERIMENTALMENTE"
    cfg.validation_rmse_threshold_V = 1e-4
    r2 = run_identification(curves, cfg)
    assert r2.validation["status"] == "VALIDACION_NO_SUPERADA" and r2.status == "AJUSTADO_A_CURVA"


def test_determinism_with_seed():
    c = ex.synthetic_curve()
    a = run_identification([c], preset_generic([c]))
    b = run_identification([c], preset_generic([c]))
    assert np.array_equal(a.x_best, b.x_best)


def test_multi_curve_preset_frees_temperature_terms():
    dev = DeviceInfo(name="s")
    curves = [ex.synthetic_curve(device=dev, temperature_K=T, curve_id=f"T{T}", seed=s)
              for T, s in ((323.15, 1), (343.15, 2), (363.15, 3))]
    cfg = preset_generic(curves)
    assert {"xi2", "R_mem_temperature_exponent"} <= set(cfg.free_names())
    assert "xi4" not in cfg.free_names()
