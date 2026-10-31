"""Núcleo físico: equivalencia con el código original y propiedades estructurales."""
import json

import numpy as np
import pandas as pd
import pytest

from conftest import FIXTURES
from pemfc_core import model as core
from pemfc_core.parameters import OTEKON_REFERENCE_PARAMS as P, ModelParameters


def test_equivalence_with_original_pemfc_model():
    """El fixture se generó ejecutando PEM-FC@a533432 (tools/generate_reference_fixture.py)."""
    ref = pd.read_csv(FIXTURES / "head_reference_curves.csv")
    meta = json.loads((FIXTURES / "head_reference_params.json").read_text())
    worst = 0.0
    for (vec, T, Pa), g in ref.groupby(["vector", "T_K", "P_atm"]):
        params = ModelParameters().copy_with(**meta["vectors"][vec])
        v = core.cell_voltage(g.j_A_cm2.to_numpy(), params, core.OperatingConditions(T, Pa))
        worst = max(worst, float(np.abs(v - g.V_cell_V.to_numpy()).max()))
    assert len(ref) > 2000
    assert worst < 1e-12


def test_membrane_thickness_and_diffusivity_do_not_affect_voltage():
    j = np.linspace(0, 1.2, 40)
    c = core.OperatingConditions(353.15, 2.0)
    a = core.cell_voltage(j, P, c)
    b = core.cell_voltage(j, P.copy_with(t_m=0.02, D_H=3e-6), c)
    assert np.max(np.abs(a - b)) < 1e-14  # igualdad salvo redondeo de coma flotante


def test_nernst_is_pressure_independent_in_original_formulation():
    assert core.nernst_voltage(P, core.OperatingConditions(353.15, 1.0)) == pytest.approx(
        core.nernst_voltage(P, core.OperatingConditions(353.15, 5.0)), abs=1e-15)


def test_membrane_resistance_closed_form():
    T = 373.15
    expected = P.R_mem_ref_ohm_cm2 * (T / P.T_ref) ** P.R_mem_temperature_exponent
    assert core.membrane_resistance(P, T) == pytest.approx(expected, rel=1e-12)


def test_pressure_raises_voltage_through_activation_term():
    j = [0.6]
    v1 = core.cell_voltage(j, P, core.OperatingConditions(373.15, 1.0))[0]
    v5 = core.cell_voltage(j, P, core.OperatingConditions(373.15, 5.0))[0]
    assert 0 < v5 - v1 < 0.03


def test_per_curve_hydrogen_pressure_override():
    c1 = core.OperatingConditions(353.15, 2.0)
    c2 = core.OperatingConditions(353.15, 2.0, p_h2_atm=P.p_h2)
    assert core.nernst_voltage(P, c1) == core.nernst_voltage(P, c2)
    c3 = core.OperatingConditions(353.15, 2.0, p_h2_atm=2.0)
    assert core.nernst_voltage(P, c3) > core.nernst_voltage(P, c1)


def test_stack_quantities():
    st = core.stack_quantities([0.5, 1.0], [0.7, 0.6], 210, 300.0)
    assert np.allclose(st["current_A"], [150, 300])
    assert np.allclose(st["V_stack_V"], [147, 126])
    assert np.allclose(st["P_stack_W"], [147 * 150, 126 * 300])
    assert core.stack_quantities([1.0], [0.6], None, None)["V_stack_V"] is None


def test_evaluate_flags_and_finite_outputs():
    ev = core.evaluate(np.linspace(0, 1.4, 50), P, core.OperatingConditions(298.15, 5.0))
    assert ev["flag_below_current_floor"][0]
    for k in ("V_act_V", "V_ohm_V", "V_conc_V", "V_cell_V"):
        assert np.isfinite(ev[k]).all() and (ev[k] >= 0).all()


@pytest.mark.parametrize("kwargs", [dict(temperature_K=-1, cathode_pressure_atm=1),
                                    dict(temperature_K=300, cathode_pressure_atm=0),
                                    dict(temperature_K=300, cathode_pressure_atm=1, oxygen_fraction=1.5)])
def test_invalid_conditions_rejected(kwargs):
    with pytest.raises(ValueError):
        core.OperatingConditions(**kwargs)


def test_unknown_parameter_rejected():
    with pytest.raises(KeyError):
        P.copy_with(alpha_H=1.0)
