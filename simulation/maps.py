"""Bancada 06 — Mapas operacionales (mismas funciones del núcleo; óptimos con el algoritmo de la Bancada 04).

Categorías de cada celda (no equivalentes entre sí):
  0 NO CALCULABLE      el modelo no produce un valor válido (V_celda ≤ 0 recortada, no finito)
  1 INADMISIBLE        calculable, pero viola un límite operacional documentado (I, P, V mínima)
  2 EXTRAPOLADO        calculable y admisible, fuera del dominio calibrado (j o condiciones)
  3 DOMINIO CALIBRADO  calculable, admisible y dentro de los rangos de j y condiciones del perfil
«Dentro del dominio calibrado» significa dentro del RANGO de la calibración (interpolación entre condiciones ensayadas),
no que cada celda haya sido medida: las condiciones realmente ensayadas se superponen como referencia.
"""
from __future__ import annotations

import math
import time

import numpy as np
from scipy.optimize import minimize_scalar

from pemfc_core import model as core

from .benches import V_EXTRA, V_OK, V_WARN, BenchResult, _k, _lst, run_optimization
from .scenarios import base_values, build_model
from .stack import HEATING, M_H2, F, OperatingLimits, SimulationError

AXES = {"j": ("Densidad de corriente", "A/cm²"), "T": ("Temperatura", "K"), "P": ("Presión de cátodo (abs.)", "atm"),
        "pH2": ("Presión parcial de H₂", "atm"), "yO2": ("Fracción molar de O₂", "–")}
COND = {"T": "temperature_K", "P": "cathode_pressure_atm", "pH2": "p_h2_atm", "yO2": "oxygen_fraction"}
PAIRS = [("j", "T"), ("j", "P"), ("j", "pH2"), ("j", "yO2"), ("T", "P")]
QUANTITIES = {"V_cell": ("Tensión de celda", "V"), "V_stack": ("Tensión de stack", "V"), "P": ("Potencia del stack", "W"),
              "eta": ("Eficiencia", "%"), "SFC": ("Consumo específico de H₂", "g/kWh"), "H2": ("Consumo de H₂", "g/s"),
              "margin": ("Margen a restricciones", "–"), "category": ("Categoría de factibilidad y respaldo", "")}
TP_EXTRA = {"P_max": ("Potencia máxima sobre j", "W"), "j_at_Pmax": ("j en la potencia máxima", "A/cm²")}
CATEGORY = {0: "No calculable", 1: "Inadmisible (restricción)", 2: "Extrapolado", 3: "Dominio calibrado"}
MAX_CELLS = {"j": 40000, "TP": 4900}


def estimate(x: str, nx: int, ny: int) -> dict:
    cells = nx * ny
    evals = cells if x == "j" else cells * 801
    sec = 0.002 * ny + 2.5e-7 * evals if x == "j" else 2.5e-4 * cells + 1.5e-8 * evals
    lim = MAX_CELLS["j" if x == "j" else "TP"]
    return {"cells": cells, "evaluations": evals, "seconds": sec, "allowed": cells <= lim, "limit": lim}


def _calib(profile: dict) -> dict:
    d = profile["domain"]["calibration"]
    bv = base_values(profile, d["conditions"][0])
    return {"j": d["j_A_cm2"], "T": d["temperature_K"], "P": d["cathode_pressure_atm"], "pH2": [bv["p_h2_atm"]] * 2,
            "yO2": [bv["oxygen_fraction"]] * 2, "conditions": d["conditions"]}


def _in(v, rng, tol=1e-9):
    return (rng[0] - tol * max(1, abs(rng[0]))) <= v <= (rng[1] + tol * max(1, abs(rng[1])))


def _margin(i, p, v, limits: OperatingLimits):
    terms = []
    if limits.current_max_A:
        terms.append((limits.current_max_A - i) / limits.current_max_A)
    if limits.power_max_W:
        terms.append((limits.power_max_W - p) / limits.power_max_W)
    if limits.v_cell_min_V:
        terms.append((v - limits.v_cell_min_V) / limits.v_cell_min_V)
    return np.minimum.reduce(terms) if terms else None


def _fixed_value(profile: dict, fixed_cond: dict, k: str) -> float:
    if fixed_cond.get(COND[k]) is not None:
        return float(fixed_cond[COND[k]])
    return float(base_values(profile, {"temperature_K": 1, "cathode_pressure_atm": 1})[COND[k]])


def run_map(profile: dict, x_axis: str, y_axis: str, x_range: list, y_range: list, nx: int, ny: int, fixed: dict,
            limits: OperatingLimits | None = None, basis: str = "LHV", objective: str | None = "max_potencia",
            p_min_useful_W: float | None = None, optimum_calibrated_only: bool = True) -> BenchResult:
    if (x_axis, y_axis) not in PAIRS:
        raise SimulationError(f"Combinación de ejes no admitida: {x_axis}–{y_axis}. Admitidas: {PAIRS}.")
    est = estimate(x_axis, nx, ny)
    if not est["allowed"]:
        raise SimulationError(f"Resolución {nx}×{ny} = {est['cells']} celdas supera el máximo ({est['limit']}).")
    if nx < 5 or ny < 3:
        raise SimulationError("Resolución mínima 5×3.")
    (x0, x1), (y0, y1) = map(float, x_range), map(float, y_range)
    if not (x1 > x0 and y1 > y0):
        raise SimulationError("Intervalos de los ejes inválidos.")
    for ax, (a, b) in ((x_axis, (x0, x1)), (y_axis, (y0, y1))):
        if a <= 0 or (ax == "yO2" and b > 1):
            raise SimulationError(f"Intervalo físico inválido para {AXES[ax][0]}.")
    limits = limits or OperatingLimits()
    cal = _calib(profile)
    t0 = time.perf_counter()
    xs, ys = np.linspace(x0, x1, nx), np.linspace(y0, y1, ny)
    shape = (ny, nx)
    M = {k: np.full(shape, np.nan) for k in ("V_cell", "V_stack", "P", "eta", "SFC", "H2", "margin", "I")}
    if x_axis == "T":
        M.update({"P_max": np.full(shape, np.nan), "j_at_Pmax": np.full(shape, np.nan)})
    cat = np.zeros(shape, int)
    warns, hyp = set(), []
    fixed_cond = {COND[k]: fixed.get(COND[k]) for k in COND}
    j_fixed = fixed.get("j_A_cm2")
    if x_axis == "T" and (j_fixed is None or j_fixed <= 0):
        raise SimulationError("El mapa temperatura–presión necesita una densidad de corriente fija (j_A_cm2) para las "
                              "magnitudes puntuales.")
    for a in (x_axis, y_axis):
        if a != "j":
            fixed_cond[COND[a]] = None
    if fixed_cond["temperature_K"] is None and "T" not in (x_axis, y_axis):
        raise SimulationError("Indique la temperatura fija.")
    if fixed_cond["cathode_pressure_atm"] is None and "P" not in (x_axis, y_axis):
        raise SimulationError("Indique la presión de cátodo fija.")
    rows_models = []
    for r, yv in enumerate(ys):
        for c_, xv in enumerate(xs if x_axis == "T" else [None]):
            cond = dict(fixed_cond)
            cond[COND[y_axis]] = float(yv)
            if x_axis == "T":
                cond["temperature_K"] = float(xv)
            m = build_model(profile, cond)
            warns.update(w for w in m.warnings if "EXTRAPOLACIÓN" not in w and "no coinciden" not in w)
            jj = xs if x_axis == "j" else np.array([j_fixed])
            ev = core.evaluate(jj, m.loaded.params, m.cond)
            v = np.where(ev["flag_cell_voltage_clamped"], np.nan, ev["V_cell_V"])
            i = jj * m.area
            p = m.n_cells * v * i
            n = m.h2_mol_s(i)
            sl = (r, slice(None)) if x_axis == "j" else (r, c_)
            fit = (lambda a: a) if x_axis == "j" else (lambda a: np.asarray(a).ravel()[0])
            with np.errstate(invalid="ignore", divide="ignore"):
                eta = 100 * np.where(p > 0, m.efficiency_from_vcell(v, basis), np.nan)
                sfc = np.where(p > 0, n * M_H2 * 1e3 * 3600 / (p / 1000), np.nan)
            M["V_cell"][sl], M["V_stack"][sl], M["P"][sl], M["I"][sl] = fit(v), fit(v * m.n_cells), fit(p), fit(i)
            M["eta"][sl], M["H2"][sl], M["SFC"][sl] = fit(eta), fit(n * M_H2 * 1e3), fit(sfc)
            mg = _margin(i, p, v, limits)
            if mg is not None:
                M["margin"][sl] = fit(mg)
            calc = np.isfinite(v) & (v > 0)
            adm = calc & (np.nan_to_num(mg, nan=-1) >= 0 if mg is not None else True)
            cond_ok = all(_in(base_values(profile, cond)[COND[k]], cal[k]) for k in COND)
            supp = adm & cond_ok & np.array([_in(q, cal["j"]) for q in jj])
            cat[sl] = fit(np.where(~calc, 0, np.where(~adm, 1, np.where(supp, 3, 2))))
            if x_axis == "T":
                g = np.linspace(m.j_lo, m.j_hi, 801)
                pg = m.power(g)
                k = int(np.argmax(pg))
                if 0 < k < len(g) - 1:                                   # refinamiento parabólico
                    y_ = pg[k - 1:k + 2]
                    den = y_[0] - 2 * y_[1] + y_[2]
                    dx = 0.5 * (y_[0] - y_[2]) / den if den != 0 else 0.0
                    jm = g[k] + dx * (g[1] - g[0])
                else:
                    jm = g[k]
                M["P_max"][sl], M["j_at_Pmax"][sl] = float(m.power(jm)), float(jm)
            else:
                rows_models.append((float(yv), cond))
    # ------------------------------------------------------------------ óptimos (algoritmo de la Bancada 04)
    locus, optimum, opt_note = [], None, ""
    if objective:
        if x_axis == "j":
            def solve(yv):
                cond = dict(fixed_cond)
                cond[COND[y_axis]] = float(yv)
                m = build_model(profile, cond)
                return m, run_optimization(m, objective, limits, p_min_useful_W, basis=basis)
            key = {"max_potencia": ("P_W", 1), "max_eficiencia": ("eta", 1), "min_consumo": ("SFC_g_kWh", -1)}[objective]
            best = None
            for yv, cond in rows_models:
                ok_row = all(_in(base_values(profile, cond)[COND[k]], cal[k]) for k in COND)
                try:
                    m, res = solve(yv)
                except SimulationError:
                    locus.append({"y": yv, "j": None, "value": None})
                    continue
                s = res.context["selected"]
                locus.append({"y": yv, "j": s["j_A_cm2"], "value": s[key[0]]})
                if (ok_row or not optimum_calibrated_only) and (best is None or key[1] * s[key[0]] > key[1] * best[1]):
                    best = (yv, s[key[0]])
            if best is None:
                opt_note = ("Sin óptimo dentro del dominio calibrado: el eje " + AXES[y_axis][0] + " no tiene filas dentro "
                            "de los rangos de calibración." if optimum_calibrated_only else "No se encontró punto admisible.")
            else:
                k = [r[0] for r in rows_models].index(best[0])
                lo_ = rows_models[max(k - 1, 0)][0]
                hi_ = rows_models[min(k + 1, len(rows_models) - 1)][0]
                if optimum_calibrated_only:
                    lo_, hi_ = max(lo_, cal[y_axis][0]), min(hi_, cal[y_axis][1])
                y_star = best[0]
                if hi_ > lo_:
                    rr = minimize_scalar(lambda yv: -key[1] * solve(yv)[1].context["selected"][key[0]], bounds=(lo_, hi_),
                                         method="bounded", options={"xatol": 1e-6 * max(abs(hi_), 1)})
                    if -key[1] * rr.fun >= key[1] * best[1] - 1e-12 * abs(best[1]):
                        y_star = float(rr.x)
                m, res = solve(y_star)
                optimum = dict(res.context["selected"], x=res.context["selected"]["j_A_cm2"], y=y_star,
                               active_constraints=res.context["active_constraints"], explanation=res.context["explanation"])
                edge = abs(y_star - y0) < 1e-9 * max(1, abs(y0)) or abs(y_star - y1) < 1e-9 * max(1, abs(y1))
                opt_note = (f"Óptimo en j EXACTO (mismo algoritmo que la Bancada 04 para la condición {AXES[y_axis][0]} = "
                            f"{y_star:.6g}); en {AXES[y_axis][0]} refinado por búsqueda acotada entre filas vecinas"
                            + (" — situado en el BORDE del intervalo explorado: no es un máximo del dispositivo." if edge else "."))
        else:
            if objective != "max_potencia":
                opt_note = "En el mapa T–P solo se destaca la máxima potencia sobre j."
            else:
                pm = np.where(cat >= (3 if optimum_calibrated_only else 2), M["P_max"], np.nan)
                if np.isfinite(pm).any():
                    r_, c_ = np.unravel_index(np.nanargmax(pm), pm.shape)
                    cond = dict(fixed_cond, temperature_K=float(xs[c_]), cathode_pressure_atm=float(ys[r_]))
                    m = build_model(profile, cond)
                    res = run_optimization(m, "max_potencia", limits, basis=basis)
                    optimum = dict(res.context["selected"], x=float(xs[c_]), y=float(ys[r_]),
                                   active_constraints=res.context["active_constraints"], explanation=res.context["explanation"])
                    opt_note = (f"Óptimo APROXIMADO a la resolución de la malla en T y P (ΔT = {xs[1] - xs[0]:.3g} K, "
                                f"ΔP = {ys[1] - ys[0]:.3g} atm); exacto en j para esa celda (algoritmo de la Bancada 04).")
                    if c_ in (0, nx - 1) or r_ in (0, ny - 1):
                        opt_note += " En el BORDE del intervalo explorado: no es un máximo del dispositivo."
                else:
                    opt_note = "Ninguna celda admisible dentro del dominio requerido."
    elapsed = time.perf_counter() - t0
    counts = {CATEGORY[k]: int((cat == k).sum()) for k in CATEGORY}
    tested = [{"T": c["temperature_K"], "P": c["cathode_pressure_atm"]} for c in cal["conditions"]]
    hyp += [f"Ejes: {AXES[x_axis][0]} [{AXES[x_axis][1]}] × {AXES[y_axis][0]} [{AXES[y_axis][1]}]; malla {nx}×{ny} "
            f"(cálculo {elapsed:.2f} s).",
            "Condiciones fijas: " + (", ".join(f"{AXES[k][0]} = {_fixed_value(profile, fixed_cond, k):g} {AXES[k][1]}"
                                               for k in COND if k not in (x_axis, y_axis)) or "ninguna")
            + (f"; j = {j_fixed:g} A/cm²" if x_axis == "T" else "") + ".",
            "Cada celda se evalúa con pemfc_core (mismas ecuaciones y parámetros del perfil); no se interpola entre celdas.",
            "Categorías: no calculable (V ≤ 0 o no finito) · inadmisible (viola límites documentados) · extrapolado (fuera "
            "de los rangos calibrados) · dominio calibrado (dentro de los rangos; interpolación entre condiciones ensayadas).",
            "Las regiones no calculables o inadmisibles NO se rellenan: quedan vacías en el mapa.",
            "En este modelo la presión de cátodo no entra en el término de Nernst; actúa vía c_O₂ en la activación."]
    if not limits.any_static():
        hyp.append("Sin límites documentados: la categoría «inadmisible» y el margen a restricciones no se evalúan.")
    warnings = sorted(warns)
    if counts["Extrapolado"]:
        warnings.append(f"{counts['Extrapolado']} celdas están fuera del dominio calibrado (extrapolación).")
    if counts["No calculable"]:
        warnings.append(f"{counts['No calculable']} celdas no son calculables (V_celda ≤ 0): se dejan vacías.")
    if opt_note:
        hyp.append("Óptimo: " + opt_note)
    kpis = [_k("cells", "Celdas", float(nx * ny), "", f"Malla {nx}×{ny}."),
            _k("pct_cal", "Celdas en dominio calibrado", 100 * counts["Dominio calibrado"] / (nx * ny), "%", "Categoría 3."),
            _k("pct_extra", "Celdas extrapoladas", 100 * counts["Extrapolado"] / (nx * ny), "%", "Categoría 2."),
            _k("pct_nocalc", "Celdas no calculables", 100 * counts["No calculable"] / (nx * ny), "%", "Categoría 0."),
            _k("seconds", "Tiempo de cálculo", elapsed, "s", "")]
    if optimum:
        kpis += [_k("opt_P", "Óptimo: potencia", optimum["P_W"], "W", opt_note),
                 _k("opt_eta", "Óptimo: eficiencia", 100 * optimum["eta"], "%", ""),
                 _k("opt_j", "Óptimo: j", optimum["j_A_cm2"], "A/cm²", "")]
    series = {"x": _lst(xs), "y": _lst(ys), "category": cat.tolist(), "tested": tested,
              "calibrated_ranges": {k: cal[k] for k in ("j", "T", "P", "pH2", "yO2")}, "locus": locus}
    for k, mat in M.items():
        series[k] = [_lst(row) for row in mat]
    if np.all(np.isnan(M["margin"])):
        series["margin"] = None
    validity = V_EXTRA if counts["Extrapolado"] else (V_WARN if warnings else V_OK)
    return BenchResult("mapa", {"x_axis": x_axis, "y_axis": y_axis, "x_range": [x0, x1], "y_range": [y0, y1], "nx": nx,
                                "ny": ny, "fixed": fixed, "limits": limits.to_dict(), "basis": basis, "objective": objective,
                                "p_min_useful_W": p_min_useful_W, "optimum_calibrated_only": optimum_calibrated_only},
                       hyp, warnings, [], kpis, series, {"categorias": [{"categoría": k, "celdas": v} for k, v in counts.items()]},
                       validity, [], {"optimum": optimum, "optimum_note": opt_note, "elapsed_s": elapsed,
                                      "estimate": est, "model": build_model(profile, {**fixed_cond,
                                      "temperature_K": fixed_cond["temperature_K"] or float(xs[0]),
                                      "cathode_pressure_atm": fixed_cond["cathode_pressure_atm"] or float(ys[0])}).summary()})


def point_details(profile: dict, x_axis: str, y_axis: str, x: float, y: float, fixed: dict,
                  limits: OperatingLimits | None = None, basis: str = "LHV") -> dict:
    """Evaluación EXACTA de un punto del mapa (no interpolada) con su categoría y restricciones activas."""
    limits = limits or OperatingLimits()
    cond = {COND[k]: fixed.get(COND[k]) for k in COND}
    cond[COND[y_axis]] = y
    j = x if x_axis == "j" else fixed["j_A_cm2"]
    if x_axis == "T":
        cond["temperature_K"] = x
    m = build_model(profile, cond)
    op = m.operating_point(j, basis)
    ev = core.evaluate(np.array([j]), m.loaded.params, m.cond)
    calc = not bool(ev["flag_cell_voltage_clamped"][0]) and op["V_cell_V"] > 0
    act = []
    if limits.current_max_A is not None and op["I_A"] > limits.current_max_A:
        act.append("corriente máxima")
    if limits.power_max_W is not None and op["P_W"] > limits.power_max_W:
        act.append("potencia máxima")
    if limits.v_cell_min_V is not None and op["V_cell_V"] < limits.v_cell_min_V:
        act.append("tensión mínima de celda")
    cal = _calib(profile)
    inside = all(_in(base_values(profile, cond)[COND[k]], cal[k]) for k in COND) and _in(j, cal["j"])
    category = 0 if not calc else (1 if act else (3 if inside else 2))
    return {"conditions": {**base_values(profile, cond)}, **op, "violated_limits": act, "category": CATEGORY[category],
            "warnings": m.warnings}
