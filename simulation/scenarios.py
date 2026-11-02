"""Bancada 05 — Sensibilidad y comparación de escenarios (reutiliza StackModel; sin ecuaciones nuevas).

Variables OPERACIONALES (condiciones externas que entran en OperatingConditions y que pueden modificarse físicamente):
temperatura, presión absoluta del cátodo, presión parcial de H₂ y fracción molar de O₂ del oxidante.
Nota del modelo implementado: en el término de Nernst la presión de cátodo se cancela
(ln[p_H₂·√(y_O₂·P) / (p_H₂O·√P)] = ln[p_H₂·√y_O₂ / p_H₂O]); P actúa solo a través de c_O₂ en la activación.

PARÁMETROS DEL MODELO: coeficientes del perfil. Perturbarlos es un análisis MATEMÁTICO de sensibilidad, no un cambio
físico realizable; se marca siempre así.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from pemfc_core import model as core

from .benches import V_EXTRA, V_OK, V_WARN, BenchResult, _k, _lst
from .stack import F, HEATING, M_H2, OperatingLimits, SimulationError, StackModel

OPER_VARS = {"temperature_K": ("Temperatura", "K"), "cathode_pressure_atm": ("Presión de cátodo (abs.)", "atm"),
             "p_h2_atm": ("Presión parcial de H₂", "atm"), "oxygen_fraction": ("Fracción molar de O₂", "–")}
RESPONSES = {"V_cell": ("Tensión de celda en j_eval", "V"), "P": ("Potencia del stack en j_eval", "W"),
             "eta": ("Eficiencia en j_eval", "–"), "P_max": ("Potencia máxima en el dominio", "W"),
             "j_at_Pmax": ("j en la potencia máxima", "A/cm²")}
MODES = {"escenarios": "Comparación de escenarios", "sensibilidad": "Sensibilidad", "incertidumbre": "Incertidumbre estadística"}


# ===================================================================================================== variantes
def base_values(profile: dict, cond: dict) -> dict:
    """Valores efectivos de las variables operacionales (los que el modelo usa realmente)."""
    p = {q["name"]: q["value"] for q in profile.get("parameters", [])}
    return {"temperature_K": cond["temperature_K"], "cathode_pressure_atm": cond["cathode_pressure_atm"],
            "p_h2_atm": cond.get("p_h2_atm") if cond.get("p_h2_atm") is not None else p.get("p_h2"),
            "oxygen_fraction": cond.get("oxygen_fraction") if cond.get("oxygen_fraction") is not None else p.get("oxygen_fraction_air")}


def param_info(profile: dict) -> dict:
    """Parámetros perturbables con su estado de identificación (del perfil)."""
    diag = {d["parameter"]: d for d in (profile.get("diagnostics") or {}).get("parameters", [])}
    weak = " ".join((profile.get("diagnostics") or {}).get("warnings", []))
    out = {}
    for q in profile.get("parameters", []):
        if q["name"] in ("R", "F", "E0", "T_ref", "t_m", "D_H"):
            continue                                                   # constantes o sin efecto en V–I
        d = diag.get(q["name"], {})
        out[q["name"]] = {"value": q["value"], "unit": q.get("unit", ""), "symbol": q.get("symbol", q["name"]),
                          "free": bool(q.get("free")), "identifiability": q.get("identifiability"),
                          "std_error": d.get("std_error"), "at_bound": d.get("at_bound"),
                          "weak": q["name"] in weak}
    return out


def build_model(profile: dict, cond: dict, params: dict | None = None, j_max_extrapolated: float | None = None) -> StackModel:
    """StackModel con condiciones (incluidas p_H₂ e y_O₂) y, opcionalmente, parámetros perturbados."""
    m = StackModel.from_profile(profile, cond["temperature_K"], cond["cathode_pressure_atm"], j_max_extrapolated)
    base = base_values(profile, {"temperature_K": m.cond.temperature_K, "cathode_pressure_atm": m.cond.cathode_pressure_atm,
                                 "p_h2_atm": m.cond.p_h2_atm, "oxygen_fraction": m.cond.oxygen_fraction})
    ph2, yo2 = cond.get("p_h2_atm"), cond.get("oxygen_fraction")
    if ph2 is not None or yo2 is not None:
        m.cond = core.OperatingConditions(m.cond.temperature_K, m.cond.cathode_pressure_atm,
                                          ph2 if ph2 is not None else m.cond.p_h2_atm,
                                          yo2 if yo2 is not None else m.cond.oxygen_fraction)
        for name, v, b in (("p_H₂", ph2, base["p_h2_atm"]), ("y_O₂", yo2, base["oxygen_fraction"])):
            if v is not None and b is not None and abs(v - b) > 1e-12 * max(abs(b), 1):
                m.warnings.append(f"EXTRAPOLACIÓN de condiciones: {name} = {v:g} distinto del valor de calibración ({b:g}); "
                                  "el perfil no contiene ensayos con otro valor.")
    if params:
        info = param_info(profile)
        bad = [k for k in params if k not in info]
        if bad:
            raise SimulationError(f"Parámetros no perturbables: {bad}.")
        m.loaded = replace(m.loaded, params=replace(m.loaded.params, **{k: float(v) for k, v in params.items()}))
        m.hypotheses.append("Parámetros PERTURBADOS (análisis matemático, no cambio físico realizable): "
                            + ", ".join(f"{k} = {v:.6g}" for k, v in params.items()) + ".")
        for k in params:
            if info[k]["weak"] or info[k]["identifiability"] not in ("IDENTIFICABLE", None) and info[k]["free"]:
                m.warnings.append(f"{k}: identificación débil o no robusta en el perfil; su perturbación tiene interpretación limitada.")
            if not info[k]["free"]:
                m.warnings.append(f"{k}: parámetro FIJADO (no identificado con estos datos).")
    return m


def _response(m: StackModel, name: str, j_eval: float | None, limits: OperatingLimits | None, basis: str) -> float:
    if name in ("V_cell", "P", "eta"):
        if j_eval is None:
            raise SimulationError("La respuesta requiere el punto de evaluación j_eval.")
        op = m.operating_point(j_eval, basis)
        return {"V_cell": op["V_cell_V"], "P": op["P_W"], "eta": op["eta"]}[name]
    cap = m.capacity(limits)
    return cap["P_max_W"] if name == "P_max" else cap["j_at_Pmax"]


# ===================================================================================================== escenarios
def run_scenarios(profile: dict, scenarios: list[dict], reference: str, j_ref: float, limits: OperatingLimits | None = None,
                  basis: str = "LHV", n: int = 300, j_max_extrapolated: float | None = None) -> BenchResult:
    act = [s for s in scenarios if s.get("active", True)]
    if not act:
        raise SimulationError("No hay escenarios activos.")
    names = [s["name"] for s in act]
    if len(set(names)) != len(names):
        raise SimulationError("Los nombres de escenario deben ser únicos.")
    if reference not in names:
        raise SimulationError("El escenario de referencia debe estar activo.")
    models, warnings, events = {}, [], []
    for s in act:
        if s.get("temperature_K") is None or s.get("cathode_pressure_atm") is None:
            raise SimulationError(f"Escenario «{s['name']}»: indique temperatura y presión de cátodo.")
        models[s["name"]] = build_model(profile, s, s.get("params") or None, j_max_extrapolated)
        warnings += [f"«{s['name']}»: {w}" for w in models[s["name"]].warnings]
    ref = models[reference]
    j = np.linspace(ref.j_lo, ref.j_hi, n)                                   # dominio COMÚN (mismo perfil)
    if not (ref.j_lo <= j_ref <= ref.j_hi):
        raise SimulationError(f"j_ref = {j_ref:g} A/cm² fuera del dominio común [{ref.j_lo:.4g}, {ref.j_hi:.4g}].")
    vr, pr = ref.v_cell(j), ref.power(j)
    series = {"j_A_cm2": _lst(j), "I_A": _lst(j * ref.area), "scenarios": names, "reference": reference}
    rows = []
    op_ref = ref.operating_point(j_ref, basis)
    cap_ref = ref.capacity(limits)
    for s in act:
        m = models[s["name"]]
        v, p = m.v_cell(j), m.power(j)
        clamp = m.flags(j)["flag_cell_voltage_clamped"]
        eta = np.where(p > 0, m.efficiency_from_vcell(v, basis), np.nan)
        series[s["name"]] = {"V_cell_V": _lst(np.where(clamp, np.nan, v)), "P_W": _lst(np.where(clamp, np.nan, p)),
                             "dV_V": _lst(np.where(clamp, np.nan, v - vr)), "dP_W": _lst(np.where(clamp, np.nan, p - pr)),
                             "eta": _lst(np.where(clamp, np.nan, eta))}
        if clamp.any():
            warnings.append(f"«{s['name']}»: V_celda ≤ 0 en j ≥ {j[np.argmax(clamp)]:.4g} A/cm² (fuera del dominio físico "
                            "del modelo; no se representa).")
        cap = m.capacity(limits)
        op = m.operating_point(j_ref, basis)

        def pct(a, b):
            return None if b is None or a is None or not math.isfinite(b) or abs(b) < 1e-12 else 100.0 * (a - b) / abs(b)
        rows.append({"escenario": s["name"], "T_K": m.cond.temperature_K, "P_catodo_atm": m.cond.cathode_pressure_atm,
                     "p_H2_atm": base_values(profile, s)["p_h2_atm"], "y_O2": base_values(profile, s)["oxygen_fraction"],
                     "parametros_perturbados": ", ".join(f"{k}={v:.4g}" for k, v in (s.get("params") or {}).items()) or "—",
                     "P_max_W": cap["P_max_W"], "j_Pmax_A_cm2": cap["j_at_Pmax"], "I_Pmax_A": cap["I_at_Pmax_A"],
                     "restriccion_Pmax": cap["binding"], f"V_celda_jref_V": op["V_cell_V"], f"P_jref_W": op["P_W"],
                     "H2_jref_g_s": op["H2_g_s"], "eta_jref": op["eta"],
                     "dP_max_pct": pct(cap["P_max_W"], cap_ref["P_max_W"]), "dV_jref_pct": pct(op["V_cell_V"], op_ref["V_cell_V"]),
                     "dP_jref_pct": pct(op["P_W"], op_ref["P_W"]),
                     "validez": "EXTRAPOLADO" if any("EXTRAPOLACIÓN" in w for w in m.warnings) else
                                ("CONDICIONES NO ENSAYADAS (interpolación)" if any("no coinciden" in w for w in m.warnings)
                                 else "CONDICIÓN CALIBRADA"),
                     "perturbacion_matematica": bool(s.get("params"))})
    hyp = list(ref.hypotheses[:3]) + [
        f"Todas las curvas se evalúan en el MISMO dominio j ∈ [{ref.j_lo:.4g}, {ref.j_hi:.4g}] A/cm² ({n} puntos).",
        f"Comparación puntual en j_ref = {j_ref:g} A/cm² (misma densidad de corriente para todos los escenarios). Las "
        "potencias máximas se alcanzan en corrientes DISTINTAS en cada escenario (se indica j en cada caso).",
        "Diferencias ΔV y ΔP respecto al escenario de referencia «" + reference + "» a igual j.",
        f"η = V_celda/{HEATING[basis] / (2 * F):.4f} V ({basis}, H₂ consumido, stack sin BoP).",
        "En este modelo la presión de cátodo no afecta al término de Nernst (se cancela); actúa vía c_O₂ en la activación."]
    if any(s.get("params") for s in act):
        hyp.append("Los escenarios con parámetros perturbados son un análisis MATEMÁTICO: no representan un cambio físico "
                   "realizable del dispositivo.")
    kpis = [_k("n_scen", "Escenarios comparados", float(len(act)), "", "Escenarios activos."),
            _k("Pmax_ref", "P máx. (referencia)", cap_ref["P_max_W"], "W", "Máximo de P(j) en el dominio admisible."),
            _k("best_Pmax", "Mayor P máx.", max(r["P_max_W"] for r in rows), "W", "Entre los escenarios activos."),
            _k("j_ref", "Punto de comparación j_ref", j_ref, "A/cm²", "Densidad de corriente común de comparación.")]
    validity = V_EXTRA if any(r["validez"] == "EXTRAPOLADO" for r in rows) else (V_WARN if warnings else V_OK)
    return BenchResult("sensibilidad", {"mode": "escenarios", "scenarios": scenarios, "reference": reference, "j_ref": j_ref,
                                        "limits": (limits or OperatingLimits()).to_dict(), "basis": basis, "n": n},
                       hyp, warnings, events, kpis, series, {"indicadores": rows}, validity,
                       ["Escenarios fuera del dominio calibrado."] if validity == V_EXTRA else [],
                       {"mode": "escenarios", "model": ref.summary()})


# ===================================================================================================== sensibilidad
def run_sensitivity(profile: dict, cond: dict, variables: list[dict], response: str, j_eval: float | None = None,
                    limits: OperatingLimits | None = None, basis: str = "LHV", n_points: int = 21) -> BenchResult:
    """Barrido uno-a-uno (OAT) + derivada por diferencias centrales en el valor base.

    variables: [{"kind": "oper"|"param", "name": str, "lo": float, "hi": float}]
    """
    if response not in RESPONSES:
        raise SimulationError(f"Respuesta no admitida: {response}.")
    if not variables:
        raise SimulationError("Seleccione al menos una variable.")
    base_model = build_model(profile, cond)
    r0 = _response(base_model, response, j_eval, limits, basis)
    bvals = base_values(profile, cond)
    pinfo = param_info(profile)
    rows, series, warnings = [], {"response": response}, list(base_model.warnings)
    for var in variables:
        kind, name, lo, hi = var["kind"], var["name"], float(var["lo"]), float(var["hi"])
        if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
            raise SimulationError(f"{name}: intervalo inválido [{lo}, {hi}].")
        if kind == "oper":
            if name not in OPER_VARS:
                raise SimulationError(f"Variable operacional desconocida: {name}.")
            x0 = bvals[name]
            if name in ("temperature_K", "cathode_pressure_atm", "p_h2_atm") and lo <= 0:
                raise SimulationError(f"{name}: el intervalo debe ser positivo.")
            if name == "oxygen_fraction" and not (0 < lo and hi <= 1):
                raise SimulationError("y_O₂ debe estar en (0, 1].")

            def model_at(x, name=name):
                c = dict(cond, **{name: x})
                return build_model(profile, c)
            label, unit = OPER_VARS[name]
        else:
            if name not in pinfo:
                raise SimulationError(f"Parámetro no perturbable: {name}.")
            x0 = float(pinfo[name]["value"])

            def model_at(x, name=name):
                return build_model(profile, cond, {name: x})
            label, unit = f"{pinfo[name]['symbol']} (parámetro)", pinfo[name]["unit"]
            if pinfo[name]["weak"]:
                warnings.append(f"{name}: identificación no robusta en el perfil; su sensibilidad describe el modelo, no una "
                                "propiedad física.")
        xs = np.linspace(lo, hi, n_points)
        ys, invalid = [], 0
        for x in xs:
            try:
                ys.append(_response(model_at(x), response, j_eval, limits, basis))
            except (SimulationError, ValueError):
                ys.append(math.nan)
                invalid += 1
        ys = np.asarray(ys, float)
        inside = lo <= x0 <= hi
        xd = x0 if inside else 0.5 * (lo + hi)
        h = 1e-4 * (hi - lo)
        try:
            d = (_response(model_at(xd + h), response, j_eval, limits, basis)
                 - _response(model_at(xd - h), response, j_eval, limits, basis)) / (2 * h)
        except (SimulationError, ValueError):
            d = math.nan
        rd = _response(model_at(xd), response, j_eval, limits, basis) if inside else r0
        scale_r = max(np.nanmax(np.abs(ys)) if np.isfinite(ys).any() else 0.0, abs(r0), 1e-300)
        elas, note = None, ""
        if not inside:
            note = "valor base fuera del intervalo: derivada en el punto medio; elasticidad no calculada"
        elif abs(x0) < 1e-12 * max(abs(lo), abs(hi), 1.0):
            note = "valor base ≈ 0: sensibilidad relativa no definida (denominador nulo)"
        elif abs(rd) < 1e-6 * scale_r:
            note = "respuesta ≈ 0 en el valor base: sensibilidad relativa inestable, no se calcula"
        elif math.isfinite(d):
            elas = d * x0 / rd
        if note:
            warnings.append(f"{name}: {note}.")
        if invalid:
            warnings.append(f"{name}: {invalid} de {n_points} puntos del barrido no son calculables (se omiten).")
        series[name] = {"x": _lst(xs), "y": _lst(ys), "x0": x0, "label": label, "unit": unit, "kind": kind}
        y_lo, y_hi = float(ys[0]), float(ys[-1])
        rows.append({"variable": name, "tipo": "operacional (física)" if kind == "oper" else "parámetro (matemática)",
                     "etiqueta": label, "unidad": unit, "x_base": x0, "x_min": lo, "x_max": hi,
                     "R_en_x_min": y_lo, "R_en_x_max": y_hi, "rango_R": (np.nanmax(ys) - np.nanmin(ys)) if np.isfinite(ys).any() else None,
                     "dR_dx": d if math.isfinite(d) else None, "elasticidad": elas, "nota": note})
    ranked = sorted([r for r in rows if r["rango_R"] is not None], key=lambda r: -r["rango_R"])
    dom = ranked[0]["variable"] if ranked else None
    rlab, runit = RESPONSES[response]
    hyp = list(base_model.hypotheses[:2]) + [
        f"Respuesta: {rlab} [{runit}]" + (f", j_eval = {j_eval:g} A/cm²" if response in ("V_cell", "P", "eta") else "") + ".",
        f"Método: barrido uno-a-uno (OAT, {n_points} puntos por variable) manteniendo el resto en su valor base; derivada "
        "por diferencias centrales (paso 1e-4 del intervalo) en el valor base.",
        "Sensibilidad absoluta dR/dx [unidad de R por unidad de x]; elasticidad (dR/dx)·x₀/R₀ [adimensional] solo si x₀ y R₀ "
        "no son ≈ 0.",
        "Tornado: amplitud de R sobre el intervalo ELEGIDO para cada variable; la comparación depende de esos intervalos.",
        "Esto es un análisis de SENSIBILIDAD (determinista), no una cuantificación de incertidumbre estadística.",
        "Perturbar un parámetro del modelo es un análisis matemático; solo las variables operacionales representan cambios "
        "físicos realizables."]
    kpis = [_k("R0", f"{rlab} (base)", r0, runit, "Respuesta con todas las variables en su valor base."),
            _k("n_vars", "Variables analizadas", float(len(rows)), "", "")]
    return BenchResult("sensibilidad", {"mode": "sensibilidad", "cond": cond, "variables": variables, "response": response,
                                        "j_eval": j_eval, "limits": (limits or OperatingLimits()).to_dict(), "basis": basis,
                                        "n_points": n_points},
                       hyp, warnings, [], kpis, series, {"sensibilidades": rows},
                       V_EXTRA if any("EXTRAPOLACIÓN" in w for w in warnings) else (V_WARN if warnings else V_OK), [],
                       {"mode": "sensibilidad", "dominant": dom, "ranking": [r["variable"] for r in ranked],
                        "model": base_model.summary()})


# ===================================================================================================== incertidumbre
def uncertainty_available(profile: dict) -> tuple[bool, str, dict]:
    diag = profile.get("diagnostics") or {}
    plist = diag.get("parameters") or []
    corr = diag.get("correlation") or {}
    names = corr.get("names") or []
    se = {d["parameter"]: d.get("std_error") for d in plist}
    if not names or not plist:
        return False, "El perfil no contiene matriz de correlación ni errores estándar de los parámetros.", {}
    if any(se.get(n) is None or not math.isfinite(se.get(n)) or se.get(n) <= 0 for n in names):
        return False, "Algún parámetro libre no tiene error estándar finito y positivo.", {}
    c = np.asarray(corr["matrix"], float)
    s = np.array([se[n] for n in names])
    cov = c * np.outer(s, s)
    ev = np.linalg.eigvalsh(0.5 * (cov + cov.T))
    if ev.min() < -1e-10 * ev.max():
        return False, "La matriz de covarianza reconstruida no es semidefinida positiva.", {}
    return True, diag.get("covariance_basis", ""), {"names": names, "mean": None, "cov": cov}


def run_uncertainty(profile: dict, cond: dict, j_ref: float, n_samples: int = 400, seed: int = 20260720,
                    limits: OperatingLimits | None = None, basis: str = "LHV", n: int = 200) -> BenchResult:
    ok, basis_txt, st_ = uncertainty_available(profile)
    if not ok:
        raise SimulationError("Incertidumbre NO disponible: " + basis_txt + " Solo puede hacerse un análisis de "
                              "perturbación determinista (sensibilidad).")
    if not (50 <= n_samples <= 5000):
        raise SimulationError("Número de muestras entre 50 y 5000.")
    m0 = build_model(profile, cond)
    names = st_["names"]
    theta0 = np.array([getattr(m0.loaded.params, k) for k in names], float)
    rng = np.random.default_rng(seed)
    w, vec = np.linalg.eigh(0.5 * (st_["cov"] + st_["cov"].T))
    Lm = vec * np.sqrt(np.clip(w, 0, None))
    samples = theta0 + rng.standard_normal((n_samples, len(names))) @ Lm.T
    j = np.linspace(m0.j_lo, m0.j_hi, n)
    V = np.full((n_samples, n), np.nan)
    pmax, jmax, vref, invalid = [], [], [], 0
    for k in range(n_samples):
        p = replace(m0.loaded.params, **dict(zip(names, samples[k])))
        mk = replace(m0, loaded=replace(m0.loaded, params=p))
        v = mk.v_cell(j)
        if np.any(m0.flags(j)["flag_cell_voltage_clamped"]) or np.any(v <= 0) or not np.all(np.isfinite(v)):
            invalid += 1
        V[k] = np.where(v > 0, v, np.nan)
        cap = mk.capacity(limits)
        pmax.append(cap["P_max_W"])
        jmax.append(cap["j_at_Pmax"])
        vref.append(float(mk.v_cell(j_ref)))
    P = m0.n_cells * V * j * m0.area
    q = lambda a: np.nanpercentile(a, [2.5, 50, 97.5], axis=0)  # noqa: E731
    qv, qp = q(V), q(P)
    pmax, jmax, vref = np.array(pmax), np.array(jmax), np.array(vref)
    diag = profile.get("diagnostics") or {}
    warnings = list(m0.warnings) + list(diag.get("warnings", []))
    sysres = [m["curve_id"] for m in (profile.get("fit") or {}).get("metrics_by_curve", []) if m.get("systematic_residual")]
    if sysres:
        warnings.append("Residuos sistemáticos en " + ", ".join(sysres) + ": la covarianza lineal SUBESTIMA la incertidumbre "
                        "real (error de modelo no aleatorio).")
    if invalid:
        warnings.append(f"{invalid} de {n_samples} muestras producen V ≤ 0 en parte del dominio (se excluyen esos puntos).")
    hyp = [f"Base estadística del perfil: {basis_txt}.",
           "Covarianza Σ = diag(σ)·R·diag(σ) a partir de los errores estándar y la correlación de los parámetros LIBRES "
           "(aproximación lineal local del ajuste, gaussiana).",
           f"Propagación por Monte Carlo: {n_samples} muestras θ ~ N(θ̂, Σ), semilla {seed}; bandas = percentiles 2,5–97,5 %.",
           "Los parámetros FIJADOS no aportan incertidumbre (se tratan como exactos).",
           "Esto es INCERTIDUMBRE ESTADÍSTICA de los parámetros identificados, distinta de la sensibilidad determinista.",
           "No incluye incertidumbre de las condiciones, de N_celdas/A ni el error estructural del modelo."]
    kpis = [_k("Pmax_med", "P máx. (mediana)", float(np.median(pmax)), "W", "Mediana de la distribución de P máx."),
            _k("Pmax_lo", "P máx. percentil 2,5 %", float(np.percentile(pmax, 2.5)), "W", ""),
            _k("Pmax_hi", "P máx. percentil 97,5 %", float(np.percentile(pmax, 97.5)), "W", ""),
            _k("Vref_sd", "Desv. típica de V(j_ref)", float(np.std(vref)), "V", f"j_ref = {j_ref:g} A/cm²."),
            _k("n_samples", "Muestras", float(n_samples), "", "")]
    series = {"j_A_cm2": _lst(j), "V_p025": _lst(qv[0]), "V_p50": _lst(qv[1]), "V_p975": _lst(qv[2]),
              "P_p025": _lst(qp[0]), "P_p50": _lst(qp[1]), "P_p975": _lst(qp[2]), "V_nominal": _lst(m0.v_cell(j)),
              "P_nominal": _lst(m0.power(j)), "Pmax_samples": _lst(pmax), "jmax_samples": _lst(jmax), "Vref_samples": _lst(vref)}
    return BenchResult("sensibilidad", {"mode": "incertidumbre", "cond": cond, "j_ref": j_ref, "n_samples": n_samples,
                                        "seed": seed, "limits": (limits or OperatingLimits()).to_dict(), "basis": basis},
                       hyp, warnings, [], kpis, series, {"parametros": [{"parametro": k, "valor": float(t),
                                                                          "error_estandar": float(math.sqrt(st_["cov"][i, i]))}
                                                                         for i, (k, t) in enumerate(zip(names, theta0))]},
                       V_WARN if warnings else V_OK, [], {"mode": "incertidumbre", "model": m0.summary()})
