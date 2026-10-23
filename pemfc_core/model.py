"""Núcleo electroquímico único de PEMFC ModelLab.

Reimplementación, ecuación por ecuación, de ``PEM-FC/models/pemfc_model.py``
(commit a533432; modelo semiempírico reconstruido de Altıntaş & Ertan,
OTEKON 2024). La equivalencia numérica con el código original se verifica en
``tests/test_model.py`` contra ``tests/fixtures/head_reference_curves.csv``.

Diferencias de interfaz (no de ecuaciones):
* Las condiciones de operación se pasan como :class:`OperatingConditions`
  (temperatura, presión absoluta de cátodo y, opcionalmente, p_H2 e y_O2 por
  curva). Si p_H2 e y_O2 no se dan, se usan los valores globales de los
  parámetros, exactamente como en el código original.
* Se exponen indicadores de recortes no suaves (``max(·,0)``) para que el
  identificador pueda avisar cuando el Jacobiano pierde información.

Unidades: j [A/cm²], tensiones [V/celda], T [K], presiones [atm absolutas].
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from .parameters import ModelParameters

MODEL_ID = "pemfc_semiempirical_otekon2024_reconstructed"
MODEL_VERSION = "1.0.0"
MODEL_LABEL = "Modelo semiempírico PEMFC (estructura OTEKON 2024 reconstruida)"

# Constantes numéricas fijas del código original (no son parámetros ajustables).
NERNST_TEMPERATURE_COEFF_V_K = 0.85e-3
HENRY_PREFACTOR_ATM_CM3_MOL = 5.08e6
HENRY_ENERGY_K = 498.0

MODEL_EQUATIONS = {
    "nernst": "E = E0 - 0.85e-3 (T - T_ref) + (R T / 2F) ln[ p_H2 sqrt(y_O2 P) / (p_H2O sqrt(P)) ]",
    "oxygen_concentration": "C_O2 = y_O2 P / (5.08e6 exp(-498/T))",
    "activation": "V_act = max(-[xi1 + xi2 T + xi3 T ln(1000 max(j, j_floor)) + xi4 T ln(C_O2)], 0)",
    "ohmic": "V_ohm = j R_mem(T); R_mem = t_m / sigma; sigma = F^2 D_H C_H(T) / (R T); "
             "C_H(T) = C_H,ref (T/T_ref)^(1 - n_R); equivalente a R_mem = R_mem,ref (T/T_ref)^n_R",
    "concentration": "V_conc = max(a_ref + a_T (T - T_ref), 0) exp(b j)",
    "cell": "V_cell = max(E - V_act - V_ohm - V_conc, 0)",
    "stack": "V_stack = N_cells V_cell; I = j A_active; P = V_stack I",
}


@dataclass(frozen=True)
class OperatingConditions:
    """Condiciones de una curva de polarización.

    temperature_K: temperatura de la celda [K].
    cathode_pressure_atm: presión absoluta del cátodo/aire [atm].
    p_h2_atm: presión parcial de H2 [atm abs]; None => parámetro global p_h2.
    oxygen_fraction: fracción molar de O2 del oxidante; None => parámetro global.
    """

    temperature_K: float
    cathode_pressure_atm: float
    p_h2_atm: float | None = None
    oxygen_fraction: float | None = None

    def __post_init__(self) -> None:
        if not (math.isfinite(self.temperature_K) and self.temperature_K > 0):
            raise ValueError("La temperatura debe ser finita y positiva (K).")
        if not (math.isfinite(self.cathode_pressure_atm) and self.cathode_pressure_atm > 0):
            raise ValueError("La presión de cátodo debe ser finita y positiva (atm abs).")
        if self.p_h2_atm is not None and not (math.isfinite(self.p_h2_atm) and self.p_h2_atm > 0):
            raise ValueError("p_H2 debe ser finita y positiva (atm abs).")
        if self.oxygen_fraction is not None and not (0 < self.oxygen_fraction <= 1):
            raise ValueError("La fracción de O2 debe estar en (0, 1].")

    def to_dict(self) -> dict:
        return asdict(self)

    def key(self) -> tuple:
        return (round(self.temperature_K, 6), round(self.cathode_pressure_atm, 6),
                self.p_h2_atm, self.oxygen_fraction)


def _arr(value) -> np.ndarray:
    return np.asarray(value, dtype=float)


def _p_h2(params: ModelParameters, cond: OperatingConditions) -> float:
    return params.p_h2 if cond.p_h2_atm is None else float(cond.p_h2_atm)


def _y_o2(params: ModelParameters, cond: OperatingConditions) -> float:
    return params.oxygen_fraction_air if cond.oxygen_fraction is None else float(cond.oxygen_fraction)


def oxygen_partial_pressure(params: ModelParameters, cond: OperatingConditions) -> float:
    return _y_o2(params, cond) * float(cond.cathode_pressure_atm)


def nernst_voltage(params: ModelParameters, cond: OperatingConditions) -> float:
    """Eq. (3) tal como está implementada en PEM-FC HEAD."""
    T = float(cond.temperature_K)
    P = float(cond.cathode_pressure_atm)
    numerator = _p_h2(params, cond) * np.sqrt(oxygen_partial_pressure(params, cond))
    denominator = params.p_h2o * np.sqrt(P)
    return float(
        params.E0
        - NERNST_TEMPERATURE_COEFF_V_K * (T - params.T_ref)
        + (params.R * T) / (2.0 * params.F) * np.log(numerator / denominator)
    )


def oxygen_concentration(params: ModelParameters, cond: OperatingConditions) -> float:
    """Eq. (5): concentración de O2 en la interfaz [mol/cm³]."""
    T = float(cond.temperature_K)
    return float(oxygen_partial_pressure(params, cond)
                 / (HENRY_PREFACTOR_ATM_CM3_MOL * np.exp(-HENRY_ENERGY_K / T)))


def activation_argument(j, params: ModelParameters, cond: OperatingConditions) -> np.ndarray:
    """Expresión entre corchetes de la Eq. (4); V_act = max(-arg, 0)."""
    T = float(cond.temperature_K)
    j_safe = np.maximum(_arr(j), params.current_density_floor_A_cm2)
    i_mA_cm2 = 1000.0 * j_safe
    c_o2 = oxygen_concentration(params, cond)
    return (params.xi1 + params.xi2 * T + params.xi3 * T * np.log(i_mA_cm2)
            + params.xi4 * T * np.log(c_o2))


def activation_overpotential(j, params: ModelParameters, cond: OperatingConditions) -> np.ndarray:
    return np.maximum(-activation_argument(j, params, cond), 0.0)


def proton_concentration_ref(params: ModelParameters) -> float:
    """C_H,ref derivada de R_mem,ref por la cadena Eq. (10)-(12)."""
    sigma_ref = params.t_m / params.R_mem_ref_ohm_cm2
    return sigma_ref * params.R * params.T_ref / (params.F ** 2 * params.D_H)


def effective_proton_concentration(params: ModelParameters, temperature_K: float) -> float:
    exponent = 1.0 - params.R_mem_temperature_exponent
    return float(proton_concentration_ref(params) * (temperature_K / params.T_ref) ** exponent)


def membrane_conductivity(params: ModelParameters, temperature_K: float) -> float:
    c_h = effective_proton_concentration(params, temperature_K)
    return float((params.F ** 2 / (params.R * temperature_K)) * params.D_H * c_h)


def membrane_resistance(params: ModelParameters, temperature_K: float) -> float:
    """Eq. (10): R_mem [Ω·cm²]."""
    return float(params.t_m / membrane_conductivity(params, temperature_K))


def ohmic_overpotential(j, params: ModelParameters, cond: OperatingConditions) -> np.ndarray:
    return _arr(j) * membrane_resistance(params, float(cond.temperature_K))


def concentration_coefficient_raw(params: ModelParameters, temperature_K: float) -> float:
    return float(params.concentration_a_ref_V
                 + params.concentration_a_temperature_V_K * (temperature_K - params.T_ref))


def concentration_overpotential(j, params: ModelParameters, cond: OperatingConditions) -> np.ndarray:
    a = max(concentration_coefficient_raw(params, float(cond.temperature_K)), 0.0)
    return a * np.exp(params.concentration_b_cm2_A * _arr(j))


def cell_voltage(j, params: ModelParameters, cond: OperatingConditions) -> np.ndarray:
    """Eq. (2): V_cell = max(E - V_act - V_ohm - V_conc, 0) [V/celda]."""
    j = _arr(j)
    v = (nernst_voltage(params, cond)
         - activation_overpotential(j, params, cond)
         - ohmic_overpotential(j, params, cond)
         - concentration_overpotential(j, params, cond))
    return np.maximum(v, 0.0)


def evaluate(j, params: ModelParameters, cond: OperatingConditions) -> dict[str, np.ndarray]:
    """Todas las magnitudes del modelo en los puntos j, con indicadores de recorte."""
    j = _arr(j)
    e = nernst_voltage(params, cond)
    act_arg = activation_argument(j, params, cond)
    v_act = np.maximum(-act_arg, 0.0)
    v_ohm = ohmic_overpotential(j, params, cond)
    a_raw = concentration_coefficient_raw(params, float(cond.temperature_K))
    v_conc = concentration_overpotential(j, params, cond)
    v_raw = e - v_act - v_ohm - v_conc
    return {
        "j_A_cm2": j,
        "E_nernst_V": np.full_like(j, e),
        "V_act_V": v_act,
        "V_ohm_V": v_ohm,
        "V_conc_V": v_conc,
        "V_cell_V": np.maximum(v_raw, 0.0),
        "R_mem_ohm_cm2": np.full_like(j, membrane_resistance(params, float(cond.temperature_K))),
        "flag_activation_clamped": act_arg >= 0.0,
        "flag_concentration_a_clamped": np.full(j.shape, a_raw < 0.0),
        "flag_cell_voltage_clamped": v_raw <= 0.0,
        "flag_below_current_floor": j < params.current_density_floor_A_cm2,
    }


def stack_quantities(j, v_cell, n_cells: int | None, area_cm2: float | None) -> dict[str, np.ndarray | None]:
    """Conversión celda -> stack. Devuelve None donde falta geometría."""
    j = _arr(j)
    v_cell = _arr(v_cell)
    current = j * area_cm2 if area_cm2 else None
    v_stack = v_cell * n_cells if n_cells else None
    power = v_stack * current if (current is not None and v_stack is not None) else None
    return {"current_A": current, "V_stack_V": v_stack, "P_stack_W": power,
            "power_density_W_cm2": v_cell * j}


class PEMFCModel:
    """Envoltorio orientado a objetos sobre las funciones puras."""

    model_id = MODEL_ID
    model_version = MODEL_VERSION

    def __init__(self, params: ModelParameters) -> None:
        self.params = params

    def cell_voltage(self, j, cond: OperatingConditions) -> np.ndarray:
        return cell_voltage(j, self.params, cond)

    def evaluate(self, j, cond: OperatingConditions) -> dict[str, np.ndarray]:
        return evaluate(j, self.params, cond)
