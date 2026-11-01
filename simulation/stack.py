"""Modelo de stack para el Motor 2, construido EXCLUSIVAMENTE a partir de un perfil calibrado del Motor 1.

No introduce ecuaciones electroquímicas nuevas: la tensión de celda es ``pemfc_core.model.cell_voltage`` con los
parámetros del perfil. Lo que se añade aquí son relaciones de conservación y definiciones operacionales:

* corriente de stack            I = j · A_activa                       [A]
* potencia eléctrica del stack  P = N_celdas · V_celda(j) · I          [W]
* consumo faradaico de H₂       ṅ_H₂ = N_celdas · I / (2 F)            [mol/s]  (2 e⁻ por molécula, una
                                 reacción por celda en serie: todas las celdas conducen la misma corriente I)
* eficiencia eléctrica referida al H₂ CONSUMIDO (poder calorífico inferior, LHV):
                                 η = P / (ṅ_H₂ · LHV) = V_celda / (LHV / 2F) = V_celda / 1,2532 V
  (análogamente con HHV, 1,4811 V). Es la eficiencia electroquímica del stack: sin auxiliares (BoP),
  sin purgas ni pérdidas de combustible no reaccionado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from identification.profiles import LoadedProfile, load_profile
from pemfc_core import model as core

F = 96485.33212            # C/mol (CODATA 2018)
M_H2 = 2.01588e-3          # kg/mol
VM_NORMAL = 22.413969      # L/mol a 0 °C y 101,325 kPa («normal litro», NL)
LHV_H2 = 241.83e3          # J/mol, H₂O vapor, 25 °C
HHV_H2 = 285.83e3          # J/mol, H₂O líquida, 25 °C
HEATING = {"LHV": LHV_H2, "HHV": HHV_H2}


class SimulationError(ValueError):
    """Entrada insuficiente o inválida: la simulación no se ejecuta (nunca se rellenan datos)."""


@dataclass
class OperatingLimits:
    """Límites operacionales DOCUMENTADOS por el usuario. ``None`` = no evaluado (no significa «ilimitado»)."""
    current_max_A: float | None = None
    power_max_W: float | None = None
    v_cell_min_V: float | None = None
    ramp_up_W_s: float | None = None
    ramp_down_W_s: float | None = None
    source: str = ""                      # procedencia declarada (datasheet, ensayo, criterio de diseño…)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("current_max_A", "power_max_W", "v_cell_min_V", "ramp_up_W_s",
                                              "ramp_down_W_s", "source")}

    @classmethod
    def from_dict(cls, d: dict | None) -> "OperatingLimits":
        d = d or {}
        return cls(**{k: d.get(k) for k in ("current_max_A", "power_max_W", "v_cell_min_V", "ramp_up_W_s",
                                             "ramp_down_W_s")}, source=d.get("source", "") or "")

    def any_static(self) -> bool:
        return any(v is not None for v in (self.current_max_A, self.power_max_W, self.v_cell_min_V))


@dataclass
class StackModel:
    loaded: LoadedProfile
    cond: core.OperatingConditions
    j_lo: float                              # densidad mínima del dominio admisible [A/cm²]
    j_hi: float                              # densidad máxima del dominio admisible [A/cm²]
    extrapolate: bool = False
    hypotheses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ construcción
    @classmethod
    def from_profile(cls, profile: dict, temperature_K: float | None = None, pressure_atm: float | None = None,
                     j_max_extrapolated: float | None = None) -> "StackModel":
        loaded = load_profile(profile)
        st = profile.get("status", {})
        if not st.get("usable_for_simulation", False):
            raise SimulationError(f"El perfil {profile.get('profile_id')} tiene estado {st.get('code')} y no es "
                                  "utilizable para simulación.")
        dev = loaded.device
        if not dev.n_cells or not dev.active_area_cm2:
            raise SimulationError("El dispositivo no declara N_celdas y área activa: sin ellos no se pueden calcular "
                                  "corriente, potencia ni consumo de H₂ del stack. Complételos en el Motor 1 (etapa 01) "
                                  "y vuelva a calibrar.")
        dom = (profile.get("domain") or {}).get("calibration") or {}
        jr = dom.get("j_A_cm2")
        if not jr:
            raise SimulationError("El perfil no declara su dominio de densidad de corriente calibrado.")
        conds = dom.get("conditions") or []
        hyp, warn = [], []
        if temperature_K is None or pressure_atm is None:
            if len(conds) != 1:
                raise SimulationError("El perfil se calibró con varias condiciones: indique temperatura y presión.")
            temperature_K = conds[0]["temperature_K"] if temperature_K is None else temperature_K
            pressure_atm = conds[0]["cathode_pressure_atm"] if pressure_atm is None else pressure_atm
        c0 = next((c for c in conds if abs(c["temperature_K"] - temperature_K) < 1e-9
                   and abs(c["cathode_pressure_atm"] - pressure_atm) < 1e-9), None)
        cond = core.OperatingConditions(temperature_K=float(temperature_K), cathode_pressure_atm=float(pressure_atm),
                                        p_h2_atm=(c0 or {}).get("p_h2_atm"), oxygen_fraction=(c0 or {}).get("oxygen_fraction"))
        trange, prange = dom.get("temperature_K") or [None, None], dom.get("cathode_pressure_atm") or [None, None]
        if c0 is None:
            inside = (trange[0] is not None and trange[0] - 1e-9 <= temperature_K <= trange[1] + 1e-9
                      and prange[0] - 1e-9 <= pressure_atm <= prange[1] + 1e-9)
            warn.append(("Condiciones no ensayadas" if inside else "EXTRAPOLACIÓN de condiciones")
                        + f": T = {temperature_K:.2f} K, P = {pressure_atm:.3g} atm no coinciden con ninguna curva de "
                        f"calibración (T {trange[0]}–{trange[1]} K, P {prange[0]}–{prange[1]} atm). "
                        + ("Interpolación del modelo entre condiciones calibradas." if inside else
                           "El modelo se evalúa fuera del rango de condiciones identificado."))
        else:
            hyp.append(f"Condiciones de operación iguales a una curva de calibración (T = {temperature_K:.2f} K, "
                       f"P_cátodo = {pressure_atm:.3g} atm abs).")
        j_lo, j_hi = float(jr[0]), float(jr[1])
        ext = False
        if j_max_extrapolated is not None and j_max_extrapolated > j_hi:
            j_hi, ext = float(j_max_extrapolated), True
            warn.append(f"EXTRAPOLACIÓN en corriente autorizada por el usuario hasta j = {j_hi:.4g} A/cm² (dominio "
                        f"calibrado hasta {jr[1]:.4g} A/cm²). Los resultados por encima no están respaldados por datos.")
        hyp += [f"Modelo cuasiestacionario: cada instante se evalúa con la curva de polarización estacionaria "
                f"identificada ({core.MODEL_ID} {core.MODEL_VERSION}).",
                f"N_celdas = {dev.n_cells} ({dev.n_cells_origin}); A_activa = {dev.active_area_cm2:g} cm² "
                f"({dev.active_area_origin}).",
                f"Dominio admisible de densidad de corriente: {j_lo:.4g}–{j_hi:.4g} A/cm²"
                + (" (incluye extrapolación)." if ext else " (dominio calibrado).")]
        for o, n in ((dev.n_cells_origin, "N_celdas"), (dev.active_area_origin, "A_activa")):
            if o in ("ASUMIDO", "SUPUESTO"):
                warn.append(f"{n} tiene origen {o}: corrientes, potencias y H₂ dependen de esa hipótesis.")
        if st.get("code") != "VALIDADO_CON_DATOS_INDEPENDIENTES" and "VALIDADO" not in str(st.get("code")):
            hyp.append(f"Perfil {st.get('code')}: capacidad predictiva {st.get('predictive_capability', 'NO DEMOSTRADA')}.")
        return cls(loaded, cond, j_lo, j_hi, ext, hyp, warn)

    # ------------------------------------------------------------------ magnitudes
    @property
    def n_cells(self) -> int:
        return int(self.loaded.device.n_cells)

    @property
    def area(self) -> float:
        return float(self.loaded.device.active_area_cm2)

    @property
    def profile_id(self) -> str:
        return self.loaded.profile["profile_id"]

    def v_cell(self, j) -> np.ndarray:
        return core.cell_voltage(np.asarray(j, float), self.loaded.params, self.cond)

    def flags(self, j) -> dict:
        ev = core.evaluate(np.atleast_1d(np.asarray(j, float)), self.loaded.params, self.cond)
        return {k: ev[k] for k in ev if k.startswith("flag_")}

    def current(self, j):
        return np.asarray(j, float) * self.area

    def power(self, j) -> np.ndarray:
        j = np.asarray(j, float)
        return self.n_cells * self.v_cell(j) * j * self.area

    def h2_mol_s(self, current_A) -> np.ndarray:
        return self.n_cells * np.asarray(current_A, float) / (2.0 * F)

    @staticmethod
    def efficiency_from_vcell(v_cell, basis: str = "LHV") -> np.ndarray:
        return np.asarray(v_cell, float) / (HEATING[basis] / (2.0 * F))

    # ------------------------------------------------------------------ envolvente admisible
    def admissible_upper(self, limits: OperatingLimits | None) -> tuple[float, str]:
        """Densidad máxima admisible y restricción que la fija."""
        limits = limits or OperatingLimits()
        j_up, why = self.j_hi, "dominio de validez del modelo" + (" (extrapolado)" if self.extrapolate else "")
        if limits.current_max_A is not None:
            jc = limits.current_max_A / self.area
            if jc < j_up:
                j_up, why = jc, f"corriente máxima documentada ({limits.current_max_A:g} A)"
        if limits.v_cell_min_V is not None:
            g = np.linspace(self.j_lo, j_up, 4001)
            bad = np.nonzero(self.v_cell(g) < limits.v_cell_min_V)[0]
            if bad.size:
                k = bad[0]
                if k == 0:
                    return self.j_lo, f"tensión mínima de celda ({limits.v_cell_min_V:g} V) ya violada en j mínimo"
                j_up = brentq(lambda x: float(self.v_cell(x)) - limits.v_cell_min_V, g[k - 1], g[k], xtol=1e-12)
                why = f"tensión mínima de celda documentada ({limits.v_cell_min_V:g} V)"
        return float(j_up), why

    def capacity(self, limits: OperatingLimits | None = None) -> dict:
        """Máxima potencia estacionaria disponible en el dominio admisible (y restricción activa)."""
        j_up, why = self.admissible_upper(limits)
        g = np.linspace(self.j_lo, j_up, 4001)
        p = self.power(g)
        k = int(np.argmax(p))
        j_star = float(g[k])
        if 0 < k < len(g) - 1:                       # refinamiento local (máximo interior)
            from scipy.optimize import minimize_scalar
            r = minimize_scalar(lambda x: -float(self.power(x)), bounds=(g[k - 1], g[k + 1]), method="bounded",
                                options={"xatol": 1e-12})
            j_star = float(r.x)
        p_star = float(self.power(j_star))
        active = "máximo interior de la curva P–j del modelo" if 0 < k < len(g) - 1 else why
        if limits and limits.power_max_W is not None and limits.power_max_W < p_star:
            p_star, active = float(limits.power_max_W), f"potencia máxima documentada ({limits.power_max_W:g} W)"
            j_star = self.j_for_power(p_star, j_up)
        return {"P_max_W": p_star, "j_at_Pmax": j_star, "I_at_Pmax_A": j_star * self.area, "j_upper": j_up,
                "binding": active, "interior_max": 0 < k < len(g) - 1}

    def j_for_power(self, p_target: float, j_upper: float | None = None) -> float:
        """Menor densidad de corriente que entrega ``p_target`` (rama de mayor eficiencia). P=0 → j=0 (parado)."""
        if p_target <= 0:
            return 0.0
        j_upper = self.j_hi if j_upper is None else j_upper
        g = np.linspace(0.0, j_upper, 2001)
        p = self.power(g)
        idx = np.nonzero(p >= p_target)[0]
        if idx.size == 0:
            raise SimulationError(f"P = {p_target:g} W no es alcanzable en el dominio admisible.")
        k = int(idx[0])
        if k == 0:
            return 0.0
        return float(brentq(lambda x: float(self.power(x)) - p_target, g[k - 1], g[k], xtol=1e-14, rtol=1e-13))

    def operating_point(self, j: float, basis: str = "LHV") -> dict:
        v = float(self.v_cell(j))
        i = j * self.area
        p = self.n_cells * v * i
        n = float(self.h2_mol_s(i))
        return {"j_A_cm2": j, "I_A": i, "V_cell_V": v, "V_stack_V": v * self.n_cells, "P_W": p,
                "H2_mol_s": n, "H2_g_s": n * M_H2 * 1e3, "H2_NL_min": n * VM_NORMAL * 60.0,
                "eta": float(self.efficiency_from_vcell(v, basis)) if p > 0 else math.nan,
                "SFC_g_kWh": (n * M_H2 * 1e3 * 3600.0) / (p / 1000.0) if p > 0 else math.nan,
                "in_calibrated_domain": (j == 0) or (self.j_lo - 1e-12 <= j <= float(self.loaded.profile["domain"]["calibration"]["j_A_cm2"][1]) + 1e-12)}

    def summary(self) -> dict:
        p = self.loaded.profile
        return {"profile_id": self.profile_id, "status": p["status"]["code"], "device": p["device"],
                "conditions": {"temperature_K": self.cond.temperature_K,
                               "cathode_pressure_atm": self.cond.cathode_pressure_atm,
                               "p_h2_atm": self.cond.p_h2_atm, "oxygen_fraction": self.cond.oxygen_fraction},
                "j_domain_A_cm2": [self.j_lo, self.j_hi], "extrapolated": self.extrapolate,
                "model": {"id": core.MODEL_ID, "version": core.MODEL_VERSION},
                "parameters": [{k: q.get(k) for k in ("name", "symbol", "value", "unit", "origin")}
                               for q in p.get("parameters", [])]}


# ---------------------------------------------------------------------- conversión de unidades de H₂
FLOW_UNITS = {"NL/min": 1.0 / (VM_NORMAL * 60.0), "SLPM (0 °C, 1 atm)": 1.0 / (VM_NORMAL * 60.0),
              "mol/s": 1.0, "g/s": 1e-3 / M_H2, "g/min": 1e-3 / (M_H2 * 60.0), "kg/h": 1.0 / (M_H2 * 3600.0)}


def flow_to_mol_s(values, unit: str) -> np.ndarray:
    if unit not in FLOW_UNITS:
        raise SimulationError(f"Unidad de caudal no admitida: {unit!r}. Use una de {list(FLOW_UNITS)}.")
    return np.asarray(values, float) * FLOW_UNITS[unit]
