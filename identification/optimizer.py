"""Identificación paramétrica generalizada (algoritmo OTEKON generalizado).

Conserva del identificador original (PEM-FC/calibration/identify_parameters.py):
mínimos cuadrados no lineales acotados ``least_squares(method='trf',
jac='3-point', loss='linear')``, escalas ``x_scale``, inicios deterministas
(inicio publicado + mezclas aleatorias con semilla), selección del mejor
inicio y función objetivo solo con tensiones.

Generaliza: subconjunto libre arbitrario, parámetros fijados con origen,
priors gaussianos explícitos, ponderación por punto o por curva, σ_V por
curva declarada por el usuario, inicio opcional informado por los datos,
reglas estructurales de identificabilidad y diagnóstico completo.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

from pemfc_core import model as core
from pemfc_core.parameters import (
    FITTABLE_PARAMETERS, ORIGIN_ASSUMED, ORIGIN_FIXED, ORIGIN_IDENTIFIED, ORIGINS, OTEKON_REFERENCE_J_MAX_A_CM2,
    OTEKON_REFERENCE_PARAMS, PARAMETER_INFO, ModelParameters,
)
from pemfc_core.schemas import (
    EXPERIMENTAL_QUALITIES, ROLE_CALIBRATION, ROLE_VALIDATION, STATUS_FITTED,
    STATUS_INSUFFICIENT, STATUS_NOT_CONVERGED, STATUS_VALIDATED, VALIDATION_FAILED,
    VALIDATION_NONE, VALIDATION_NOT_EXPERIMENTAL, VALIDATION_PASSED, VALIDATION_SAME_CONDITION,
)

from . import diagnostics as diag
from .datasets import PolarizationCurve, ValidationIssue

OTEKON_SEED = 20260720
MAX_STARTS = 64
MAX_NFEV_LIMIT = 20000
LINEAR_PARAMS = ("xi1", "xi2", "xi3", "xi4", "R_mem_ref_ohm_cm2",
                 "concentration_a_ref_V", "concentration_a_temperature_V_K")
SINGLE_CURVE_PRIORITY = ("xi1", "R_mem_ref_ohm_cm2", "concentration_a_ref_V", "xi3", "concentration_b_cm2_A")


class FitConfigError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues if i.level == "error"))


@dataclass
class ParameterSetting:
    name: str
    free: bool
    value: float
    lower: float
    upper: float
    scale: float
    prior_mean: float | None = None
    prior_sigma: float | None = None
    fixed_origin: str = ORIGIN_ASSUMED
    rationale: str = ""

    @property
    def has_prior(self) -> bool:
        return self.free and self.prior_mean is not None and self.prior_sigma is not None


@dataclass
class FitConfig:
    settings: dict[str, ParameterSetting]
    base_params: ModelParameters = OTEKON_REFERENCE_PARAMS
    n_starts: int = 16
    seed: int = OTEKON_SEED
    max_nfev: int = 2000
    tolerance: float = 1e-12
    weighting: str = "puntos"  # "puntos" | "curvas"
    data_informed_start: bool = True
    rmse_threshold_V: float = 0.010
    validation_rmse_threshold_V: float = 0.010
    preset: str = "personalizado"
    notes: list[str] = field(default_factory=list)

    def free_names(self) -> list[str]:
        return [n for n in FITTABLE_PARAMETERS if self.settings[n].free]

    def to_dict(self) -> dict:
        return {
            "preset": self.preset, "n_starts": self.n_starts, "seed": self.seed,
            "max_nfev": self.max_nfev, "tolerance": self.tolerance, "weighting": self.weighting,
            "data_informed_start": self.data_informed_start,
            "rmse_threshold_V": self.rmse_threshold_V,
            "validation_rmse_threshold_V": self.validation_rmse_threshold_V,
            "settings": {n: dict(s.__dict__) for n, s in self.settings.items()},
            "base_params": self.base_params.to_dict(), "notes": list(self.notes),
        }


# ----------------------------------------------------------------------------
# Presets
# ----------------------------------------------------------------------------
def _setting(name: str, free: bool, value: float, *, otekon_bounds: bool, fixed_origin=ORIGIN_ASSUMED,
             rationale: str = "") -> ParameterSetting:
    info = PARAMETER_INFO[name]
    lo, hi = (info.otekon_lower, info.otekon_upper) if otekon_bounds else (info.generic_lower, info.generic_upper)
    return ParameterSetting(name, free, float(value), float(lo), float(hi), float(info.otekon_scale),
                            fixed_origin=fixed_origin, rationale=rationale)


def preset_otekon() -> FitConfig:
    """Reproducción exacta de la configuración del identificador OTEKON original."""
    settings = {n: _setting(n, True, PARAMETER_INFO[n].otekon_initial, otekon_bounds=True,
                            rationale="Especificación de PARAMETER_SPECS (identificador OTEKON).")
                for n in FITTABLE_PARAMETERS}
    return FitConfig(settings=settings, base_params=OTEKON_REFERENCE_PARAMS, n_starts=16, seed=OTEKON_SEED,
                     max_nfev=10000, tolerance=1e-12, weighting="puntos", data_informed_start=False,
                     preset="OTEKON (reproducción, 9 parámetros)",
                     notes=["Configuración idéntica al identificador original: 9 libres, límites, escalas, "
                            "16 inicios, semilla 20260720, TRF, tolerancias 1e-12."])


def _distinct_temperatures(curves) -> int:
    return len({round(c.conditions.temperature_K, 2) for c in curves})


def _distinct_oxygen_pressures(curves, base: ModelParameters) -> int:
    return len({round(core.oxygen_partial_pressure(base, c.conditions), 6) for c in curves})


def preset_generic(curves: list[PolarizationCurve], base: ModelParameters = OTEKON_REFERENCE_PARAMS) -> FitConfig:
    """Preset recomendado según la diversidad de condiciones de las curvas de calibración.

    * Siempre candidatos: ξ1 (intercepto), R_mem,ref, a_ref, ξ3 (Tafel), b.
    * ≥ 2 temperaturas: también ξ2, n_R, a_T.  ≥ 2 presiones parciales de O2: también ξ4.
    * Se limita el número de libres a (puntos − 1) siguiendo el orden de prioridad.
    Los fijados toman el valor de referencia OTEKON con origen ASUMIDO.
    """
    cal = [c for c in curves if c.meta.role == ROLE_CALIBRATION]
    n_points = sum(c.n_points for c in cal)
    nT, nP = _distinct_temperatures(cal), _distinct_oxygen_pressures(cal, base)
    candidates = list(SINGLE_CURVE_PRIORITY)
    if nT >= 2:
        candidates += ["xi2", "R_mem_temperature_exponent", "concentration_a_temperature_V_K"]
    if nP >= 2:
        candidates += ["xi4"]
    max_free = max(n_points - 1, 0)
    notes = [f"{len(cal)} curva(s) de calibración, {n_points} puntos, {nT} temperatura(s), "
             f"{nP} presión(es) parcial(es) de O2 distintas."]
    j_max = max((c.j_A_cm2.max() for c in cal), default=0.0)
    if j_max > OTEKON_REFERENCE_J_MAX_A_CM2:
        notes.append(f"Los datos llegan a {j_max:.2f} A/cm², fuera del dominio (≤ {OTEKON_REFERENCE_J_MAX_A_CM2} A/cm²) "
                     "en que se identificaron los valores de referencia OTEKON: los parámetros de concentración "
                     "fijados en esos valores no son transferibles.")
    name = "Una curva (efectivo)" if len(cal) == 1 else "Múltiples curvas"

    def make(free: set[str]) -> FitConfig:
        settings = {n: _setting(
            n, n in free, getattr(base, n), otekon_bounds=False, fixed_origin=ORIGIN_ASSUMED,
            rationale=("Libre: identificable con las condiciones disponibles." if n in free else
                       "Fijado en el valor de referencia OTEKON (no medido en este dispositivo)."))
            for n in FITTABLE_PARAMETERS}
        return FitConfig(settings=settings, base_params=base, n_starts=12, seed=OTEKON_SEED, max_nfev=2000,
                         data_informed_start=True, preset=name, notes=list(notes))

    if len(candidates) <= max_free:
        return make(set(candidates))
    if max_free == 0:
        cfg = make(set())
        cfg.notes.append("No hay puntos suficientes para liberar ningún parámetro.")
        return cfg
    # Selección transparente: se evalúan los subconjuntos de tamaño max_free que contienen ξ1
    # (el intercepto absorbe E0 y las presiones parciales no medidas) con un ajuste rápido.
    # Usa los mismos datos de calibración: es una recomendación editable, no una validación.
    import itertools
    trials = []
    others = [c for c in candidates if c != "xi1"]
    for combo in itertools.combinations(others, max_free - 1):
        cfg = make({"xi1", *combo})
        cfg.n_starts, cfg.max_nfev = 4, 500
        try:
            r = run_identification(curves, cfg)
        except FitConfigError:
            continue
        if r.x_best is None or r.status == STATUS_NOT_CONVERGED:
            continue
        n_bound = int(r.identifiability["parameters"]["at_bound"].sum())
        trials.append((n_bound > 0, r.metrics_global["rmse_V"], n_bound, combo))
    if not trials:
        cfg = make(set(candidates[:max_free]))
        cfg.notes.append("La selección automática no encontró un subconjunto convergente; se usa el orden de prioridad.")
        return cfg
    rmse_best = min(t[1] for t in trials)
    # Preferir sin parámetros en límites si su RMSE no es mucho peor (≤ 1,5× el mejor).
    clean = [t for t in trials if not t[0] and t[1] <= 1.5 * rmse_best]
    chosen = min(clean or trials, key=lambda t: (t[1], t[2]))
    cfg = make({"xi1", *chosen[3]})
    summary = "; ".join(f"{{ξ1, {', '.join(PARAMETER_INFO[n].symbol for n in t[3])}}}: {1000 * t[1]:.1f} mV"
                        f"{' (límite activo)' if t[0] else ''}" for t in sorted(trials, key=lambda t: t[1]))
    cfg.notes.append(f"Solo caben {max_free} parámetros libres. Selección automática entre {len(trials)} subconjuntos "
                     f"(ajuste rápido sobre los mismos datos de calibración; recomendación editable): {summary}.")
    return cfg


# ----------------------------------------------------------------------------
# Reglas estructurales
# ----------------------------------------------------------------------------
def structural_checks(curves: list[PolarizationCurve], config: FitConfig) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    E = lambda m: issues.append(ValidationIssue("error", "", m))  # noqa: E731
    W = lambda m: issues.append(ValidationIssue("aviso", "", m))  # noqa: E731
    cal = [c for c in curves if c.meta.role == ROLE_CALIBRATION]
    if not cal:
        E("No hay curvas de calibración. La identificación exige al menos una curva V–I.")
        return issues
    if set(config.settings) != set(FITTABLE_PARAMETERS):
        E("La configuración debe incluir todos los parámetros ajustables.")
        return issues
    free = config.free_names()
    if not free:
        E("No hay parámetros libres: seleccione al menos uno.")
    if not (1 <= config.n_starts <= MAX_STARTS):
        E(f"Número de inicios fuera de [1, {MAX_STARTS}].")
    if not (50 <= config.max_nfev <= MAX_NFEV_LIMIT):
        E(f"Evaluaciones máximas por inicio fuera de [50, {MAX_NFEV_LIMIT}].")
    if config.weighting not in ("puntos", "curvas"):
        E("Ponderación inválida.")
    if not (config.rmse_threshold_V > 0 and config.validation_rmse_threshold_V > 0):
        E("Los criterios de RMSE deben ser positivos.")
    for n, s in config.settings.items():
        vals = (s.value, s.lower, s.upper, s.scale)
        if not all(math.isfinite(v) for v in vals):
            E(f"{n}: valores no finitos en la configuración.")
            continue
        if s.free:
            if not s.lower < s.upper:
                E(f"{n}: el límite inferior debe ser menor que el superior.")
            elif not s.lower <= s.value <= s.upper:
                E(f"{n}: el valor inicial {s.value:g} está fuera de [{s.lower:g}, {s.upper:g}].")
            if s.scale <= 0:
                E(f"{n}: la escala debe ser positiva.")
            if (s.prior_mean is None) != (s.prior_sigma is None):
                E(f"{n}: un prior necesita media y desviación.")
            if s.prior_sigma is not None and not (math.isfinite(s.prior_sigma) and s.prior_sigma > 0):
                E(f"{n}: la desviación del prior debe ser positiva.")
        elif s.fixed_origin not in ORIGINS or s.fixed_origin == ORIGIN_IDENTIFIED:
            E(f"{n}: un parámetro fijado necesita origen MEDIDO, DATASHEET, FIJADO o ASUMIDO.")
    if any(i.level == "error" for i in issues):
        return issues

    nT = _distinct_temperatures(cal)
    nP = _distinct_oxygen_pressures(cal, config.base_params)
    for n in free:
        s = config.settings[n]
        req = PARAMETER_INFO[n].requires
        if req == "temperaturas" and nT < 2 and not s.has_prior:
            E(f"{PARAMETER_INFO[n].symbol} ({n}) solo es identificable con curvas a ≥ 2 temperaturas distintas "
              f"(hay {nT}). Fíjelo o declare un prior explícito.")
        if req == "presiones" and nP < 2 and not s.has_prior:
            E(f"{PARAMETER_INFO[n].symbol} ({n}) solo es identificable con ≥ 2 presiones parciales de O2 distintas "
              f"(hay {nP}). Fíjelo o declare un prior explícito.")
    priors = [n for n in free if config.settings[n].has_prior]
    if priors and not all(c.meta.sigma_V is not None for c in cal):
        E("Los priors requieren declarar σ_V en todas las curvas de calibración, para que el peso relativo "
          "entre datos y prior tenga significado.")
    n_data = sum(c.n_points for c in cal)
    if n_data + len(priors) <= len(free):
        E(f"Puntos de calibración ({n_data}) + priors ({len(priors)}) ≤ parámetros libres ({len(free)}): "
          "el problema está indeterminado. Fije parámetros o añada datos.")
    elif n_data <= len(free):
        W(f"Puntos ({n_data}) ≤ libres ({len(free)}): la solución depende de los priors.")
    elif n_data < 3 * len(free):
        W(f"Pocos puntos por parámetro libre ({n_data} para {len(free)}).")
    if len(cal) == 1:
        W("Una sola curva de calibración: los parámetros son efectivos para esa condición y no representan "
          "propiedades físicas únicas. No se demuestra capacidad predictiva en otras condiciones.")
    declared = [c.meta.sigma_V is not None for c in cal]
    if any(declared) and not all(declared):
        W("σ_V declarada solo en algunas curvas: se ignora para ponderar (todas con peso unitario).")
    return issues


# ----------------------------------------------------------------------------
# Resultado
# ----------------------------------------------------------------------------
@dataclass
class FitResult:
    config: FitConfig
    status: str
    status_reasons: list[str]
    params: ModelParameters
    free_names: list[str]
    x_best: np.ndarray | None
    best_start: int | None
    runs: pd.DataFrame
    residuals: pd.DataFrame
    metrics_global: dict
    metrics_by_curve: pd.DataFrame
    validation: dict
    identifiability: dict | None
    sigma_declared: bool
    warnings: list[str]
    elapsed_s: float
    optimizer_message: str
    curve_ids: list[str]

    @property
    def converged(self) -> bool:
        return self.status != STATUS_NOT_CONVERGED


def build_start_vectors(initial: np.ndarray, lower: np.ndarray, upper: np.ndarray,
                        number_of_starts: int, seed: int) -> list[np.ndarray]:
    """Idéntico a `build_start_vectors` del identificador OTEKON, para cualquier subconjunto."""
    if number_of_starts < 1:
        raise ValueError("number_of_starts debe ser al menos 1")
    starts = [initial.copy()]
    rng = np.random.default_rng(seed)
    for _ in range(number_of_starts - 1):
        global_sample = rng.uniform(lower, upper)
        weight = rng.uniform(0.25, 0.75)
        candidate = weight * initial + (1.0 - weight) * global_sample
        starts.append(np.clip(candidate, lower + 1e-12, upper - 1e-12))
    return starts


def _params_from(base: ModelParameters, settings: dict[str, ParameterSetting],
                 free: list[str], x: np.ndarray) -> ModelParameters:
    values = {n: s.value for n, s in settings.items() if not s.free}
    values.update(dict(zip(free, (float(v) for v in x))))
    return replace(base, **values)


def _curve_sigmas_weights(cal, config) -> tuple[list[float], list[float], bool]:
    declared = all(c.meta.sigma_V is not None for c in cal)
    sig = [float(c.meta.sigma_V) if declared else 1.0 for c in cal]
    if config.weighting == "curvas":
        mean_n = np.mean([c.n_points for c in cal])
        w = [math.sqrt(mean_n / c.n_points) for c in cal]
    else:
        w = [1.0] * len(cal)
    return sig, w, declared


def data_informed_start(cal, config: FitConfig, free: list[str], lower, upper, sig, w) -> np.ndarray | None:
    """Inicio por proyección lineal: ξ1–ξ4, R_mem,ref, a_ref, a_T entran linealmente en V
    (ignorando recortes) para b y n_R dados; b se explora en una rejilla si es libre."""
    lin_free = [n for n in free if n in LINEAR_PARAMS]
    if not lin_free:
        return None
    s = config.settings
    b_grid = (np.geomspace(max(s["concentration_b_cm2_A"].lower, 0.05), s["concentration_b_cm2_A"].upper, 25)
              if s["concentration_b_cm2_A"].free else [s["concentration_b_cm2_A"].value])
    nR = s["R_mem_temperature_exponent"].value
    best, best_ssr = None, math.inf
    for b in b_grid:
        rows, rhs = [], []
        for c, sc, wc in zip(cal, sig, w):
            p0 = _params_from(config.base_params, s, free,
                              np.array([s[n].value for n in free])).copy_with(
                concentration_b_cm2_A=b, R_mem_temperature_exponent=nR)
            T = c.conditions.temperature_K
            j = c.j_A_cm2
            ln_i = np.log(1000.0 * np.maximum(j, p0.current_density_floor_A_cm2))
            ln_c = math.log(core.oxygen_concentration(p0, c.conditions))
            e_b = np.exp(b * j)
            cols = {
                "xi1": np.ones_like(j), "xi2": np.full_like(j, T), "xi3": T * ln_i,
                "xi4": np.full_like(j, T * ln_c), "R_mem_ref_ohm_cm2": -j * (T / p0.T_ref) ** nR,
                "concentration_a_ref_V": -e_b, "concentration_a_temperature_V_K": -(T - p0.T_ref) * e_b,
            }
            # Contribución de los parámetros lineales fijados (o no libres) al lado derecho.
            fixed_part = core.nernst_voltage(p0, c.conditions)
            fixed_part = fixed_part + sum(getattr(p0, n) * cols[n] for n in LINEAR_PARAMS if n not in lin_free)
            rows.append(np.column_stack([cols[n] for n in lin_free]) * (wc / sc))
            rhs.append((c.v_cell_V - fixed_part) * (wc / sc))
        A, y = np.vstack(rows), np.concatenate(rhs)
        theta, *_ = np.linalg.lstsq(A, y, rcond=None)
        x = np.array([s[n].value for n in free], dtype=float)
        for n, t in zip(lin_free, theta):
            x[free.index(n)] = t
        if "concentration_b_cm2_A" in free:
            x[free.index("concentration_b_cm2_A")] = b
        x = np.clip(x, lower + 1e-12, upper - 1e-12)
        p = _params_from(config.base_params, s, free, x)
        ssr = sum(float(np.sum(((core.cell_voltage(c.j_A_cm2, p, c.conditions) - c.v_cell_V) * wc / sc) ** 2))
                  for c, sc, wc in zip(cal, sig, w))
        if ssr < best_ssr:
            best, best_ssr = x, ssr
    return best


def _residual_table(curves, params) -> pd.DataFrame:
    frames = []
    for c in curves:
        ev = core.evaluate(c.j_A_cm2, params, c.conditions)
        frames.append(pd.DataFrame({
            "curve_id": c.curve_id, "role": c.meta.role,
            "T_K": c.conditions.temperature_K, "P_atm": c.conditions.cathode_pressure_atm,
            "j_A_cm2": c.j_A_cm2, "V_obs_V": c.v_cell_V, "V_model_V": ev["V_cell_V"],
            "residual_V": ev["V_cell_V"] - c.v_cell_V,
            "clamp_activation": ev["flag_activation_clamped"],
            "clamp_cell": ev["flag_cell_voltage_clamped"],
            "below_floor": ev["flag_below_current_floor"],
        }))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _metrics_by_curve(res: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (cid, role), g in res.groupby(["curve_id", "role"], sort=False):
        m = diag.voltage_metrics(g.residual_V.to_numpy(), g.V_obs_V.to_numpy())
        rt = diag.runs_test(g.sort_values("j_A_cm2").residual_V.to_numpy())
        rows.append({"curve_id": cid, "role": role, **m, "runs_z": rt["z"], "systematic_residual": rt["systematic"]})
    return pd.DataFrame(rows)


def run_identification(curves: list[PolarizationCurve], config: FitConfig,
                       progress: Callable[[int, int], None] | None = None) -> FitResult:
    """Ejecuta la identificación. Lanza FitConfigError si la configuración es inválida."""
    issues = structural_checks(curves, config)
    if any(i.level == "error" for i in issues):
        raise FitConfigError(issues)
    warnings = [str(i) for i in issues if i.level == "aviso"]
    t0 = time.perf_counter()
    cal = [c for c in curves if c.meta.role == ROLE_CALIBRATION]
    val = [c for c in curves if c.meta.role == ROLE_VALIDATION]
    free = config.free_names()
    s = config.settings
    x0 = np.array([s[n].value for n in free], float)
    lower = np.array([s[n].lower for n in free], float)
    upper = np.array([s[n].upper for n in free], float)
    scales = np.array([s[n].scale for n in free], float)
    prior_idx = [k for k, n in enumerate(free) if s[n].has_prior]
    prior_mu = np.array([s[free[k]].prior_mean for k in prior_idx], float)
    prior_sd = np.array([s[free[k]].prior_sigma for k in prior_idx], float)
    sig, w, declared = _curve_sigmas_weights(cal, config)
    n_data = sum(c.n_points for c in cal)

    def residuals(x: np.ndarray) -> np.ndarray:
        p = _params_from(config.base_params, s, free, x)
        parts = [(core.cell_voltage(c.j_A_cm2, p, c.conditions) - c.v_cell_V) / sc * wc
                 for c, sc, wc in zip(cal, sig, w)]
        if prior_idx:
            parts.append((x[prior_idx] - prior_mu) / prior_sd)
        r = np.concatenate(parts)
        return np.where(np.isfinite(r), r, 1e6)

    starts = build_start_vectors(x0, lower, upper, config.n_starts, config.seed)
    kinds = ["inicial"] + ["aleatorio"] * (len(starts) - 1)
    if config.data_informed_start and len(starts) >= 2:
        xi = data_informed_start(cal, config, free, lower, upper, sig, w)
        if xi is not None:
            starts = [starts[0], xi] + starts[1:-1]
            kinds = ["inicial", "informado por datos"] + ["aleatorio"] * (len(starts) - 2)

    run_rows, results = [], []
    for k, (x_start, kind) in enumerate(zip(starts, kinds)):
        row = {"start_id": k, "kind": kind}
        try:
            res = least_squares(residuals, x_start, bounds=(lower, upper), method="trf", jac="3-point",
                                x_scale=scales, loss="linear", max_nfev=config.max_nfev,
                                ftol=config.tolerance, xtol=config.tolerance, gtol=config.tolerance)
            p = _params_from(config.base_params, s, free, res.x)
            rv = np.concatenate([core.cell_voltage(c.j_A_cm2, p, c.conditions) - c.v_cell_V for c in cal])
            row.update(success=bool(res.success), status=int(res.status), cost=float(res.cost),
                       rmse_V=float(np.sqrt(np.mean(rv ** 2))), nfev=int(res.nfev),
                       optimality=float(res.optimality), message=str(res.message), error="")
            results.append(res)
        except Exception as exc:  # error numérico en un inicio: se registra, no se oculta
            row.update(success=False, status=-99, cost=math.inf, rmse_V=math.inf, nfev=0,
                       optimality=math.nan, message="", error=f"{type(exc).__name__}: {exc}")
            results.append(None)
        for n, v in zip(free, (results[-1].x if results[-1] is not None else np.full(len(free), np.nan))):
            row[f"x_{n}"] = float(v)
        run_rows.append(row)
        if progress:
            progress(k + 1, len(starts))
    runs = pd.DataFrame(run_rows)
    elapsed = time.perf_counter() - t0
    finite = runs[np.isfinite(runs["cost"])]
    if finite.empty:
        return _failed_result(config, free, runs, curves, warnings + ["Todos los inicios fallaron numéricamente."],
                              elapsed, declared)
    best = int(finite["cost"].idxmin())
    best_res = results[best]
    params = _params_from(config.base_params, s, free, best_res.x)
    res_table = _residual_table(cal + val, params)
    cal_res = res_table[res_table.role == ROLE_CALIBRATION]
    metrics_global = diag.voltage_metrics(cal_res.residual_V.to_numpy(), cal_res.V_obs_V.to_numpy())
    if declared:
        metrics_global["chi2_reduced"] = float(2 * best_res.cost / max(n_data - len(free), 1))
    by_curve = _metrics_by_curve(res_table)

    jac_full = best_res.jac
    ident = diag.identifiability(
        names=free, x=best_res.x, lower=lower, upper=upper, scales=scales,
        jac_data=jac_full[:n_data], jac_full=jac_full,
        ssr_weighted=float(np.sum(best_res.fun[:n_data] ** 2)), n_data=n_data, sigma_declared=declared,
        prior_sigma={free[k]: float(prior_sd[i]) for i, k in enumerate(prior_idx)},
        runs=runs, best_cost=float(best_res.cost))
    warnings += ident["warnings"]

    # Recortes no suaves activos en los datos.
    if cal_res.clamp_activation.any():
        warnings.append(f"La activación está recortada a 0 en {int(cal_res.clamp_activation.sum())} punto(s): "
                        "el modelo pierde sensibilidad allí.")
    if cal_res.clamp_cell.any():
        warnings.append("La tensión modelada llega a 0 V en algún punto de calibración.")
    if (params.concentration_a_ref_V + params.concentration_a_temperature_V_K *
            (np.array([c.conditions.temperature_K for c in cal]) - params.T_ref) < 0).any():
        warnings.append("a(T) es negativo en alguna temperatura de calibración y queda recortado a 0.")
    for _, r in by_curve.iterrows():
        if r["systematic_residual"] and r["role"] == ROLE_CALIBRATION:
            warnings.append(f"[{r['curve_id']}] residuos con estructura sistemática (test de rachas, z = {r['runs_z']:.2f}): "
                            "posible error de modelo o de datos aunque el RMSE sea bajo.")

    reasons = []
    if not best_res.success:
        status = STATUS_NOT_CONVERGED
        reasons.append(f"El mejor inicio terminó sin convergencia: {best_res.message}")
    elif metrics_global["rmse_V"] > config.rmse_threshold_V:
        status = STATUS_INSUFFICIENT
        reasons.append(f"RMSE de calibración {1000 * metrics_global['rmse_V']:.2f} mV/celda > criterio "
                       f"{1000 * config.rmse_threshold_V:.2f} mV/celda.")
    else:
        status = STATUS_FITTED
        reasons.append(f"Convergió; RMSE de calibración {1000 * metrics_global['rmse_V']:.3f} mV/celda ≤ criterio "
                       f"{1000 * config.rmse_threshold_V:.2f} mV/celda.")
    validation = _validation_summary(val, cal, res_table, config, status)
    if validation["status"] == VALIDATION_PASSED and status == STATUS_FITTED:
        status = STATUS_VALIDATED
        reasons.append("Validación independiente superada en las curvas declaradas como validación.")
    elif validation["status"] == VALIDATION_FAILED:
        warnings.append("La validación independiente NO se superó: el perfil no reproduce datos no usados "
                        "en el ajuste dentro del criterio.")
    if status in (STATUS_FITTED,) and validation["status"] == VALIDATION_NONE:
        reasons.append("Sin datos independientes: la capacidad predictiva NO está demostrada.")

    return FitResult(config=config, status=status, status_reasons=reasons, params=params, free_names=free,
                     x_best=best_res.x, best_start=best, runs=runs, residuals=res_table,
                     metrics_global=metrics_global, metrics_by_curve=by_curve, validation=validation,
                     identifiability=ident, sigma_declared=declared, warnings=_dedupe(warnings),
                     elapsed_s=elapsed, optimizer_message=str(best_res.message),
                     curve_ids=[c.curve_id for c in curves])


def _validation_summary(val, cal, res_table, config, fit_status) -> dict:
    if not val:
        return {"status": VALIDATION_NONE, "curves": [], "metrics": None,
                "criterion_rmse_V": config.validation_rmse_threshold_V, "notes": []}
    notes = []
    vr = res_table[res_table.role == ROLE_VALIDATION]
    m = diag.voltage_metrics(vr.residual_V.to_numpy(), vr.V_obs_V.to_numpy())
    cal_T = [c.conditions.temperature_K for c in cal]
    cal_j = (min(c.j_A_cm2.min() for c in cal), max(c.j_A_cm2.max() for c in cal))
    cal_keys = {c.conditions.key() for c in cal}
    for c in val:
        if c.conditions.key() in cal_keys:
            notes.append(f"{c.curve_id}: misma condición que una curva de calibración (validación de repetibilidad, "
                         "no de transferencia a otras condiciones).")
        if not (min(cal_T) <= c.conditions.temperature_K <= max(cal_T)):
            notes.append(f"{c.curve_id}: temperatura fuera del rango calibrado (extrapolación).")
        if c.j_A_cm2.max() > cal_j[1] or c.j_A_cm2.min() < cal_j[0]:
            notes.append(f"{c.curve_id}: corriente fuera del rango calibrado (extrapolación en j).")
    experimental = all(c.meta.quality in EXPERIMENTAL_QUALITIES for c in val)
    new_condition = any(c.conditions.key() not in cal_keys for c in val)
    passed = m["rmse_V"] <= config.validation_rmse_threshold_V and fit_status == STATUS_FITTED
    if not experimental:
        st = VALIDATION_NOT_EXPERIMENTAL
        notes.append("Las curvas de validación no son experimentales (sintéticas/ilustrativas): "
                     "no habilitan VALIDADO_EXPERIMENTALMENTE.")
    elif not passed:
        st = VALIDATION_FAILED
    elif not new_condition:
        st = VALIDATION_SAME_CONDITION
        notes.append("Todas las curvas de validación repiten condiciones de calibración: se comprueba "
                     "repetibilidad, no transferencia. No habilita VALIDADO_EXPERIMENTALMENTE.")
    else:
        st = VALIDATION_PASSED
    return {"status": st, "curves": [c.curve_id for c in val], "metrics": m,
            "criterion_rmse_V": config.validation_rmse_threshold_V, "notes": notes}


def _failed_result(config, free, runs, curves, warnings, elapsed, declared) -> FitResult:
    return FitResult(config=config, status=STATUS_NOT_CONVERGED,
                     status_reasons=["Ningún inicio produjo una solución finita."],
                     params=config.base_params, free_names=free, x_best=None, best_start=None, runs=runs,
                     residuals=pd.DataFrame(), metrics_global={"n": 0}, metrics_by_curve=pd.DataFrame(),
                     validation={"status": VALIDATION_NONE, "curves": [], "metrics": None,
                                 "criterion_rmse_V": config.validation_rmse_threshold_V, "notes": []},
                     identifiability=None, sigma_declared=declared, warnings=warnings, elapsed_s=elapsed,
                     optimizer_message="", curve_ids=[c.curve_id for c in curves])


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def parameter_origins(config: FitConfig) -> dict[str, str]:
    """Origen de cada parámetro ajustable tras la identificación."""
    return {n: (ORIGIN_IDENTIFIED if s.free else s.fixed_origin) for n, s in config.settings.items()}


__all__ = ["FitConfig", "ParameterSetting", "FitResult", "FitConfigError", "preset_otekon", "preset_generic",
           "structural_checks", "run_identification", "build_start_vectors", "parameter_origins", "ORIGIN_FIXED"]
