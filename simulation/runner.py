"""Ejecución de bancadas a partir de una configuración serializable (bancada, estudio completo y duplicación)."""
from __future__ import annotations

from .benches import BenchResult, run_hydrogen, run_load_following, run_optimization, run_reproduction
from .stack import OperatingLimits, SimulationError, StackModel
from .timeseries import TimeSeries

REQUIRED = {"reproduccion": [], "carga": ["cond", "demand"], "hidrogeno": ["cond", "feed", "policy"],
            "optimizacion": ["cond", "objective"]}


def missing(bench: str, config: dict | None) -> list[str]:
    if config is None:
        return ["configuración de la bancada"]
    return [k for k in REQUIRED[bench] if config.get(k) in (None, "", {})]


def model_for(profile: dict, cond: dict) -> StackModel:
    return StackModel.from_profile(profile, cond.get("temperature_K"), cond.get("cathode_pressure_atm"),
                                   cond.get("j_max_extrapolated"))


def run(bench: str, profile: dict, config: dict) -> BenchResult:
    miss = missing(bench, config)
    if miss:
        raise SimulationError("Faltan datos para ejecutar la bancada: " + ", ".join(miss) + ".")
    if bench == "reproduccion":
        r = run_reproduction(profile, config.get("curve_ids") or None)
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
