"""Construcción, exportación, reimportación y verificación de perfiles PEMFC.

Un perfil solo puede construirse a partir de un FitResult obtenido con al
menos una curva V–I de calibración. No existe ruta "datasheet → perfil".
"""
from __future__ import annotations

import hashlib
import json
import math
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import scipy

from pemfc_core import model as core
from pemfc_core.parameters import (
    FITTABLE_PARAMETERS, ORIGIN_ASSUMED, ORIGIN_FIXED, PARAMETER_INFO, ModelParameters,
)
from pemfc_core.schemas import (
    APP_NAME, APP_VERSION, PROFILE_SCHEMA_ID, PROFILE_SCHEMA_VERSION, ROLE_CALIBRATION,
    STATUS_DESCRIPTIONS, USABLE_STATUSES, DeviceInfo, SchemaReport, validate_profile_dict,
)

from .datasets import PolarizationCurve
from .optimizer import FitResult, parameter_origins

REPRODUCTION_TOLERANCE_V = 1e-9
MODEL_SOURCE = Path(core.__file__)

# Origen de los parámetros que nunca se ajustan.
NON_FITTABLE_ORIGINS = {
    "E0": ORIGIN_FIXED, "R": ORIGIN_FIXED, "F": ORIGIN_FIXED, "T_ref": ORIGIN_FIXED,
    "t_m": ORIGIN_ASSUMED, "D_H": ORIGIN_ASSUMED, "p_h2": ORIGIN_ASSUMED, "p_h2o": ORIGIN_ASSUMED,
    "oxygen_fraction_air": ORIGIN_ASSUMED, "current_density_floor_A_cm2": ORIGIN_FIXED,
}
NON_FITTABLE_NOTES = {
    "t_m": "No afecta a V–I en esta parametrización (se cancela en R_mem). Valor OTEKON, solo trazabilidad.",
    "D_H": "No afecta a V–I en esta parametrización (se cancela en R_mem). Valor OTEKON, solo trazabilidad.",
    "p_h2": "Valor global; una curva puede declarar su propia p_H2 en sus condiciones.",
    "p_h2o": "Hipótesis OTEKON; su efecto es colineal con el intercepto ξ1/ξ2.",
    "oxygen_fraction_air": "Aire seco; una curva puede declarar su propia fracción de O2.",
    "current_density_floor_A_cm2": "Regularización numérica del logaritmo (código original).",
}


class ProfileError(ValueError):
    def __init__(self, report: SchemaReport | None = None, message: str = ""):
        self.report = report
        super().__init__(message or "; ".join(report.errors if report else []))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def model_source_sha256() -> str:
    return hashlib.sha256(MODEL_SOURCE.read_bytes()).hexdigest()


def _clean(obj):
    """Convierte a tipos JSON (NaN/inf -> None)."""
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        return x if math.isfinite(x) else None
    if isinstance(obj, np.ndarray):
        return _clean(obj.tolist())
    if isinstance(obj, pd.DataFrame):
        return _clean(obj.to_dict(orient="records"))
    return obj


def _domain(curves: list[PolarizationCurve]) -> dict | None:
    if not curves:
        return None
    return {
        "j_A_cm2": [float(min(c.j_A_cm2.min() for c in curves)), float(max(c.j_A_cm2.max() for c in curves))],
        "temperature_K": [float(min(c.conditions.temperature_K for c in curves)),
                          float(max(c.conditions.temperature_K for c in curves))],
        "cathode_pressure_atm": [float(min(c.conditions.cathode_pressure_atm for c in curves)),
                                 float(max(c.conditions.cathode_pressure_atm for c in curves))],
        "conditions": [c.conditions.to_dict() for c in curves],
    }


def build_profile(result: FitResult, curves: list[PolarizationCurve], device: DeviceInfo) -> dict:
    """Construye el perfil autocontenido. Exige curvas de calibración."""
    cal = [c for c in curves if c.meta.role == ROLE_CALIBRATION]
    if not cal:
        raise ProfileError(message="No se puede crear un perfil sin curva V–I de calibración.")
    if result.x_best is None:
        raise ProfileError(message="El ajuste no produjo una solución: no hay perfil que exportar.")
    if [c.curve_id for c in curves] != result.curve_ids:
        raise ProfileError(message="Las curvas no corresponden al resultado del ajuste.")
    device_errors = device.validate()
    if device_errors:
        raise ProfileError(message="; ".join(device_errors))

    params = result.params
    origins = parameter_origins(result.config)
    ident = result.identifiability or {}
    ident_rows = {r["parameter"]: r for r in _clean(ident.get("parameters", pd.DataFrame()))}
    param_list = []
    for name in params.to_dict():
        info = PARAMETER_INFO[name]
        entry = {"name": name, "symbol": info.symbol, "value": float(getattr(params, name)), "unit": info.unit,
                 "category": info.category, "description": info.description}
        if name in FITTABLE_PARAMETERS:
            s = result.config.settings[name]
            entry.update({
                "origin": origins[name], "free": s.free, "initial": s.value if s.free else None,
                "lower": s.lower if s.free else None, "upper": s.upper if s.free else None,
                "scale": s.scale if s.free else None,
                "prior": ({"mean": s.prior_mean, "sigma": s.prior_sigma} if s.has_prior else None),
                "rationale": s.rationale,
                "identifiability": ident_rows.get(name, {}).get("identifiability", "NO_AJUSTADO"),
                "identifiability_reasons": ident_rows.get(name, {}).get("reasons", []),
                "std_error": ident_rows.get(name, {}).get("std_error"),
                "reference_origin": info.reference_origin,
            })
        else:
            entry.update({"origin": NON_FITTABLE_ORIGINS[name], "free": False,
                          "identifiability": "NO_AJUSTADO", "reference_origin": info.reference_origin,
                          "note": NON_FITTABLE_NOTES.get(name, "")})
        param_list.append(entry)

    datasets = []
    for c in curves:
        datasets.append({
            "curve_id": c.curve_id, "role": c.meta.role, "metadata": c.meta.to_dict(),
            "conditions": c.conditions.to_dict(), "conditions_input": _clean(c.conditions_input),
            "n_points": c.n_points,
            "domain": {"j_A_cm2": [float(c.j_A_cm2.min()), float(c.j_A_cm2.max())],
                       "V_cell_V": [float(c.v_cell_V.min()), float(c.v_cell_V.max())]},
            "source_file": c.source_file, "source_sha256": c.source_sha256,
            "normalized_sha256": c.normalized_sha256, "mapping": _clean(c.mapping),
            "transformations": c.transformations, "warnings": c.warnings,
            "points": {"j_A_cm2": [float(x) for x in c.j_A_cm2], "V_cell_V": [float(x) for x in c.v_cell_V]},
        })

    repro = []
    for c in curves:
        v = core.cell_voltage(c.j_A_cm2, params, c.conditions)
        repro.append({"curve_id": c.curve_id, "V_model_V": [float(x) for x in v]})

    ident_json = {k: v for k, v in ident.items() if k not in ("correlation", "parameters")}
    if "correlation" in ident:
        ident_json["correlation"] = {"names": list(ident["correlation"].columns),
                                     "matrix": _clean(ident["correlation"].to_numpy())}
    ident_json["parameters"] = list(ident_rows.values())

    runs = result.runs.drop(columns=[c for c in result.runs.columns if c.startswith("x_")])
    status_usable = result.status in USABLE_STATUSES
    profile = {
        "schema": PROFILE_SCHEMA_ID,
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_id": "",
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": {
            "code": result.status, "description": STATUS_DESCRIPTIONS[result.status],
            "reasons": result.status_reasons, "usable_for_simulation": status_usable,
            "predictive_capability": ("DEMOSTRADA SOLO EN LAS CONDICIONES VALIDADAS"
                                      if result.validation["status"] == "VALIDACION_SUPERADA" else "NO DEMOSTRADA"),
        },
        "engine": {
            "app": APP_NAME, "app_version": APP_VERSION, "model_id": core.MODEL_ID,
            "model_version": core.MODEL_VERSION, "model_label": core.MODEL_LABEL,
            "equations": core.MODEL_EQUATIONS,
            "numerical_constants": {"nernst_temperature_coeff_V_K": core.NERNST_TEMPERATURE_COEFF_V_K,
                                    "henry_prefactor_atm_cm3_mol": core.HENRY_PREFACTOR_ATM_CM3_MOL,
                                    "henry_energy_K": core.HENRY_ENERGY_K},
            "model_source_sha256": model_source_sha256(),
            "units": {"current_density": "A/cm²", "cell_voltage": "V", "temperature": "K",
                      "pressure": "atm absolutas", "area": "cm²"},
            "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                        "pandas": pd.__version__},
        },
        "device": device.to_dict(),
        "parameters": param_list,
        "datasets": datasets,
        "fit": {
            "algorithm": "Mínimos cuadrados no lineales acotados, multistart (scipy.optimize.least_squares, "
                         "method='trf', jac='3-point', loss='linear') — generalización del identificador OTEKON",
            "objective": "Σ [w_c (V_mod − V_obs)/σ_c]² sobre curvas de calibración (tensión por celda) "
                         "+ Σ [(θ − μ_prior)/σ_prior]² si hay priors. Potencia y eficiencia no se ajustan.",
            "config": _clean(result.config.to_dict()), "free_parameters": result.free_names,
            "sigma_declared": result.sigma_declared, "best_start": result.best_start,
            "optimizer_message": result.optimizer_message, "elapsed_s": result.elapsed_s,
            "runs": _clean(runs), "metrics_calibration": _clean(result.metrics_global),
            "metrics_by_curve": _clean(result.metrics_by_curve),
            "metrics_stack_V": (_clean({k: v * device.n_cells for k, v in result.metrics_global.items()
                                        if k.endswith("_V")}) if device.n_cells else None),
        },
        "diagnostics": _clean(ident_json),
        "validation": _clean(result.validation),
        "domain": {
            "calibration": _domain(cal),
            "validated": _domain([c for c in curves if c.meta.role != ROLE_CALIBRATION])
            if result.validation["status"] == "VALIDACION_SUPERADA" else None,
            "policy": "Fuera del dominio de calibración el perfil extrapola: toda evaluación fuera de rango "
                      "debe marcarse como extrapolación.",
        },
        "provenance": {
            "derived_from": [
                "github.com/brunoolmedo22-Paraguay/PEM-FC @ a533432 (modelo e identificador OTEKON)",
                "github.com/brunoolmedo22-Paraguay/EnergyMultimodelv1.5 @ 761f032 (concepto de perfil)",
            ],
            "datasheet_used_in_objective": False,
            "datasheet_reference": device.datasheet_reference,
        },
        "reproduction_check": {"tolerance_V": REPRODUCTION_TOLERANCE_V, "points": repro},
        "intended_use": {
            "engine_scope": "Motor 1 (identificación paramétrica). Motor 2 no implementado.",
            "future_consumer_contract": "Entradas: j [A/cm²] (o I [A] con device.active_area_cm2) y condiciones "
                                        "(T_K, cathode_pressure_atm, p_h2_atm opcional, oxygen_fraction opcional). "
                                        "Salidas: V_cell [V], V_stack = N·V_cell si device.n_cells. Respetar domain.",
        },
        "warnings": result.warnings + [w for c in curves for w in (f"[{c.curve_id}] {x}" for x in c.warnings)],
    }
    profile = _clean(profile)
    identity = json.dumps({"p": profile["parameters"], "d": [d["normalized_sha256"] for d in datasets],
                           "c": profile["fit"]["config"], "m": core.MODEL_VERSION}, sort_keys=True)
    profile["profile_id"] = "pml-" + _sha256_text(identity)[:16]
    report = validate_profile_dict(profile)
    if not report.ok:
        raise ProfileError(report)
    return profile


def profile_to_json(profile: dict) -> str:
    return json.dumps(profile, indent=2, ensure_ascii=False)


@dataclass
class LoadedProfile:
    profile: dict
    params: ModelParameters
    device: DeviceInfo
    curves: list[dict]
    max_reproduction_error_V: float
    reproduction_ok: bool
    engine_match: bool
    messages: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.profile["status"]["code"]

    def conditions(self, curve_id: str) -> core.OperatingConditions:
        d = next(c for c in self.curves if c["curve_id"] == curve_id)
        return core.OperatingConditions(**d["conditions"])


def load_profile(source: str | bytes | dict) -> LoadedProfile:
    """Carga un perfil, valida su esquema y verifica que reproduce la curva guardada."""
    if isinstance(source, (bytes, bytearray)):
        source = source.decode("utf-8")
    if isinstance(source, str):
        try:
            source = json.loads(source)
        except json.JSONDecodeError as exc:
            raise ProfileError(message=f"JSON inválido: {exc}") from exc
    report = validate_profile_dict(source)
    if not report.ok:
        raise ProfileError(report)
    prof = source
    messages = []
    eng = prof["engine"]
    if eng.get("model_id") != core.MODEL_ID:
        raise ProfileError(message=f"Modelo {eng.get('model_id')!r} no soportado por este motor ({core.MODEL_ID}).")
    engine_match = eng.get("model_version") == core.MODEL_VERSION
    if not engine_match:
        messages.append(f"El perfil se creó con el modelo v{eng.get('model_version')}; este motor es v{core.MODEL_VERSION}.")
    if eng.get("model_source_sha256") != model_source_sha256():
        messages.append("El código fuente del modelo difiere del usado al crear el perfil (hash distinto); "
                        "la reproducción numérica se comprueba a continuación.")
    try:
        params = ModelParameters.from_dict({p["name"]: p["value"] for p in prof["parameters"]})
    except (KeyError, TypeError, ValueError) as exc:
        raise ProfileError(message=f"Parámetros inválidos: {exc}") from exc
    device = DeviceInfo(**prof["device"])
    stored = {r["curve_id"]: r["V_model_V"] for r in prof["reproduction_check"]["points"]}
    worst = 0.0
    for d in prof["datasets"]:
        cond = core.OperatingConditions(**d["conditions"])
        v = core.cell_voltage(np.asarray(d["points"]["j_A_cm2"]), params, cond)
        ref = np.asarray(stored.get(d["curve_id"], []), float)
        if ref.shape != v.shape:
            raise ProfileError(message=f"Datos de reproducción incompletos para {d['curve_id']!r}.")
        worst = max(worst, float(np.max(np.abs(v - ref))))
    tol = float(prof["reproduction_check"].get("tolerance_V", REPRODUCTION_TOLERANCE_V))
    ok = worst <= tol
    if not ok:
        messages.append(f"La curva recalculada difiere de la guardada en {worst:.3e} V (> {tol:.0e} V).")
    if not prof["status"].get("usable_for_simulation", False):
        messages.append(f"Estado {prof['status']['code']}: el perfil no es utilizable para simulación.")
    return LoadedProfile(profile=prof, params=params, device=device, curves=prof["datasets"],
                         max_reproduction_error_V=worst, reproduction_ok=ok, engine_match=engine_match,
                         messages=messages)


def evaluate_profile(loaded: LoadedProfile, j, conditions: core.OperatingConditions) -> dict:
    """Evalúa el perfil marcando explícitamente la extrapolación."""
    j = np.asarray(j, float)
    out = core.evaluate(j, loaded.params, conditions)
    dom = loaded.profile["domain"]["calibration"]
    jmin, jmax = dom["j_A_cm2"]
    tmin, tmax = dom["temperature_K"]
    pmin, pmax = dom["cathode_pressure_atm"]
    out["extrapolated"] = ((j < jmin) | (j > jmax) |
                           (not tmin <= conditions.temperature_K <= tmax) |
                           (not pmin <= conditions.cathode_pressure_atm <= pmax))
    return out
