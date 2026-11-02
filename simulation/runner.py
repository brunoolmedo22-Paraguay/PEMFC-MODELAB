"""Ejecución de bancadas a partir de una configuración serializable (bancada, estudio completo y duplicación)."""
from __future__ import annotations

from .benches import BenchResult, run_hydrogen, run_load_following, run_optimization, run_reproduction
from .stack import OperatingLimits, SimulationError, StackModel
from .timeseries import TimeSeries

REQUIRED = {"reproduccion": [], "carga": ["cond", "demand"], "hidrogeno": ["cond", "feed", "policy"],
            "optimizacion": ["cond", "objective"], "sensibilidad": ["mode"], "mapa": ["x_axis", "y_axis", "fixed"]}
MODE_REQUIRED = {"escenarios": ["scenarios", "reference", "j_ref"], "sensibilidad": ["cond", "variables", "response"],
                 "incertidumbre": ["cond", "j_ref"]}


def missing(bench: str, config: dict | None) -> list[str]:
    if config is None:
        return ["configuración de la bancada"]
    miss = [k for k in REQUIRED[bench] if config.get(k) in (None, "", {}, [])]
    if bench == "sensibilidad" and not miss:
        miss = [k for k in MODE_REQUIRED.get(config["mode"], ["mode"]) if config.get(k) in (None, "", {}, [])]
    return miss


def model_for(profile: dict, cond: dict) -> StackModel:
    if cond.get("p_h2_atm") is not None or cond.get("oxygen_fraction") is not None:
        from .scenarios import build_model
        return build_model(profile, cond, None, cond.get("j_max_extrapolated"))
    return StackModel.from_profile(profile, cond.get("temperature_K"), cond.get("cathode_pressure_atm"),
                                   cond.get("j_max_extrapolated"))


def run(bench: str, profile: dict, config: dict) -> BenchResult:
    miss = missing(bench, config)
    if miss:
        raise SimulationError("Faltan datos para ejecutar la bancada: " + ", ".join(miss) + ".")
    if bench == "reproduccion":
        r = run_reproduction(profile, config.get("curve_ids") or None)
    elif bench in ("sensibilidad", "mapa"):
        lim = OperatingLimits.from_dict(config.get("limits"))
        basis = config.get("basis", "LHV")
        r = _explore(bench, profile, config, lim, basis)
    else:
        m = model_for(profile, config["cond"])
        lim = OperatingLimits.from_dict(config.get("limits"))
        basis = config.get("basis", "LHV")
        if bench == "carga":
            r = run_load_following(m, TimeSeries.from_dict(config["demand"]), lim, config.get("dt_s"), basis)
        elif bench == "hidrogeno":
            r = run_hydrogen(m, TimeSeries.from_dict(config["feed"]), config["policy"], config.get("value"),
                             config.get("u_max"), lim, config.get("dt_s"), basis)
        elif bench == "optimizacion":
            r = run_optimization(m, config["objective"], lim, config.get("p_min_useful_W"), config.get("p_target_W"),
                                 config.get("h2_feed_max_mol_s"), config.get("u_max"), basis)
        else:
            raise SimulationError(f"Bancada desconocida: {bench}")
    r.inputs["config"] = config
    return r


def _explore(bench: str, profile: dict, config: dict, lim, basis):
    if bench == "sensibilidad":
        from .scenarios import run_scenarios, run_sensitivity, run_uncertainty
        mode = config["mode"]
        if mode == "escenarios":
            return run_scenarios(profile, config["scenarios"], config["reference"], config["j_ref"], lim, basis,
                                 config.get("n", 300), (config.get("cond") or {}).get("j_max_extrapolated"))
        if mode == "sensibilidad":
            return run_sensitivity(profile, config["cond"], config["variables"], config["response"], config.get("j_eval"),
                                   lim, basis, config.get("n_points", 21))
        return run_uncertainty(profile, config["cond"], config["j_ref"], config.get("n_samples", 400),
                               config.get("seed", 20260720), lim, basis)
    from .maps import run_map
    return run_map(profile, config["x_axis"], config["y_axis"], config["x_range"], config["y_range"], config["nx"],
                   config["ny"], config["fixed"], lim, basis, config.get("objective"), config.get("p_min_useful_W"),
                   config.get("optimum_calibrated_only", True))
