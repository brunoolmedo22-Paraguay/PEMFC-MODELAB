"""Bancadas experimentales del Motor 2 (funciones puras, sin interfaz).

Cada bancada devuelve un ``BenchResult`` con entradas, hipótesis, advertencias, eventos, indicadores (con su
definición), series y estado de validez. Ninguna magnitud se rellena si no puede calcularse: se omite y se explica.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from identification.profiles import load_profile
from pemfc_core import model as core

from .stack import F, HEATING, M_H2, VM_NORMAL, OperatingLimits, SimulationError, StackModel
from .timeseries import TimeSeries

BENCHES = {"reproduccion": "Reproducción experimental", "carga": "Seguimiento de carga",
           "hidrogeno": "Alimentación de hidrógeno", "optimizacion": "Optimización operacional"}
V_OK, V_WARN, V_EXTRA, V_NO = "VALIDO", "VALIDO_CON_ADVERTENCIAS", "EXTRAPOLADO", "NO_EJECUTABLE"


@dataclass
class BenchResult:
    bench: str
    inputs: dict
    hypotheses: list[str]
    warnings: list[str]
    events: list[dict]
    kpis: list[dict]                 # {key, label, value, unit, definition}
    series: dict                     # nombre → lista
    tables: dict = field(default_factory=dict)
    validity: str = V_OK
    validity_reasons: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def kpi(self, key: str):
        return next((k["value"] for k in self.kpis if k["key"] == key), None)

    def to_dict(self) -> dict:
        return {"bench": self.bench, "inputs": self.inputs, "hypotheses": self.hypotheses, "warnings": self.warnings,
                "events": self.events, "kpis": self.kpis, "series": self.series, "tables": self.tables,
                "validity": self.validity, "validity_reasons": self.validity_reasons, "context": self.context}

    @classmethod
    def from_dict(cls, d: dict) -> "BenchResult":
        return cls(**{k: d.get(k) for k in ("bench", "inputs", "hypotheses", "warnings", "events", "kpis", "series")},
                   tables=d.get("tables") or {}, validity=d.get("validity", V_OK),
                   validity_reasons=d.get("validity_reasons") or [], context=d.get("context") or {})


def _k(key, label, value, unit, definition):
    v = None if value is None or (isinstance(value, float) and not math.isfinite(value)) else float(value)
    return {"key": key, "label": label, "value": v, "unit": unit, "definition": definition}


def _lst(a):
    return [None if not math.isfinite(float(x)) else float(x) for x in np.asarray(a, float)]


def _validity(model: StackModel | None, warnings: list[str], extra_flags: list[str]) -> tuple[str, list[str]]:
    reasons = list(extra_flags)
    if model is not None and model.extrapolate:
        reasons.append("Incluye extrapolación en corriente autorizada por el usuario.")
    if any("EXTRAPOLACIÓN" in w for w in warnings):
        return V_EXTRA, reasons + [w for w in warnings if "EXTRAPOLACIÓN" in w]
    if reasons or warnings:
        return V_WARN, reasons
    return V_OK, []


# =====================================================================================================================
# 01 — Reproducción experimental
# =====================================================================================================================
def run_reproduction(profile: dict, curve_ids: list[str] | None = None, n_curve_points: int = 200) -> BenchResult:
    loaded = load_profile(profile)
    params, dev = loaded.params, loaded.device
    sets = [d for d in profile.get("datasets", []) if curve_ids is None or d["curve_id"] in curve_ids]
    if not sets:
        raise SimulationError("No hay experimentos seleccionados en el perfil.")
    geometry = bool(dev.n_cells and dev.active_area_cm2)
    mbc = (profile.get("fit") or {}).get("metrics_by_curve") or []
    stored = {m["curve_id"]: m for m in mbc} if isinstance(mbc, list) else dict(mbc)
    series, rows, per_curve, warnings, hyp = {}, [], [], [], []
    all_r = []
    for d in sets:
        cid, c = d["curve_id"], d["conditions"]
        cond = core.OperatingConditions(**{k: c.get(k) for k in ("temperature_K", "cathode_pressure_atm",
                                                                  "p_h2_atm", "oxygen_fraction")})
        j = np.asarray(d["points"]["j_A_cm2"], float)
        v_obs = np.asarray(d["points"]["V_cell_V"], float)
        v_mod = core.cell_voltage(j, params, cond)
        r = v_mod - v_obs
        all_r.append(r)
        m = {"curve_id": cid, "role": d.get("role"), "n": int(len(j)), "rmse_V": float(np.sqrt(np.mean(r ** 2))),
             "mae_V": float(np.mean(np.abs(r))), "bias_V": float(np.mean(r)), "max_abs_V": float(np.max(np.abs(r))),
             "temperature_K": c["temperature_K"], "cathode_pressure_atm": c["cathode_pressure_atm"],
             "conditions_origin": (d.get("metadata") or {}).get("conditions_origin"),
             "quality": (d.get("metadata") or {}).get("quality")}
        sm = stored.get(cid) or {}
        if "rmse_V" in sm:
            m["rmse_motor1_V"] = sm["rmse_V"]
            m["delta_rmse_vs_motor1_V"] = m["rmse_V"] - sm["rmse_V"]
            if "bias_V" in sm:
                m["delta_bias_vs_motor1_V"] = m["bias_V"] - sm["bias_V"]
        per_curve.append(m)
        jj = np.linspace(float(j.min()), float(j.max()), n_curve_points)
        vv = core.cell_voltage(jj, params, cond)
        s = {"j_obs": _lst(j), "V_obs": _lst(v_obs), "V_mod_at_obs": _lst(v_mod), "residual_V": _lst(r),
             "j_curve": _lst(jj), "V_curve": _lst(vv)}
        if geometry:
            n, a = dev.n_cells, dev.active_area_cm2
            s.update({"I_obs_A": _lst(j * a), "P_obs_W": _lst(n * v_obs * j * a), "P_mod_at_obs_W": _lst(n * v_mod * j * a),
                      "I_curve_A": _lst(jj * a), "P_curve_W": _lst(n * vv * jj * a)})
        else:
            s.update({"pd_obs_W_cm2": _lst(v_obs * j), "pd_curve_W_cm2": _lst(vv * jj)})
        series[cid] = s
        for k in range(len(j)):
            rows.append({"curva": cid, "rol": d.get("role"), "j_A_cm2": float(j[k]), "V_exp_V": float(v_obs[k]),
                         "V_modelo_V": float(v_mod[k]), "residuo_V": float(r[k])})
        if (d.get("metadata") or {}).get("conditions_origin") in ("ASUMIDO", "SUPUESTO"):
            warnings.append(f"{cid}: condiciones del ensayo con origen {(d.get('metadata') or {}).get('conditions_origin')} "
                            "(no medidas): la reproducción hereda esa hipótesis.")
        if (d.get("metadata") or {}).get("quality") == "digitalizado":
            hyp.append(f"{cid}: datos digitalizados de una figura (incertidumbre de digitalización incluida en el residuo).")
    r = np.concatenate(all_r)
    roles = {m["role"] for m in per_curve}
    kind = ("VALIDACIÓN INDEPENDIENTE" if roles == {"validación"} else
            "REPRODUCCIÓN DE CALIBRACIÓN" if roles == {"calibración"} else "MIXTA (calibración y validación)")
    hyp = [f"Tipo de evaluación: {kind}. "
           + ("Las curvas evaluadas participaron en el ajuste: un RMSE pequeño NO demuestra capacidad predictiva."
              if "calibración" in roles else "Curvas declaradas como no usadas en el ajuste (rol «validación»).")] + hyp
    hyp.append("Mismas ecuaciones, parámetros y condiciones que el Motor 1 (pemfc_core.cell_voltage con el perfil).")
    deltas = [abs(m["delta_rmse_vs_motor1_V"]) for m in per_curve if "delta_rmse_vs_motor1_V" in m]
    consistent = bool(deltas) and max(deltas) <= 1e-9
    flags = []
    if not loaded.reproduction_ok:
        flags.append(f"El perfil no se reproduce a sí mismo (error {loaded.max_reproduction_error_V:.2e} V).")
    if deltas and not consistent:
        flags.append(f"Discrepancia con las métricas del Motor 1 (|ΔRMSE| máx {max(deltas):.2e} V).")
    validity, reasons = _validity(None, warnings, flags)
    kpis = [_k("rmse_V", "RMSE", float(np.sqrt(np.mean(r ** 2))), "V/celda", "√(media((V_modelo−V_exp)²)) sobre todos los puntos evaluados."),
            _k("mae_V", "MAE", float(np.mean(np.abs(r))), "V/celda", "media(|V_modelo−V_exp|)."),
            _k("bias_V", "Sesgo", float(np.mean(r)), "V/celda", "media(V_modelo−V_exp); positivo = el modelo sobreestima."),
            _k("max_abs_V", "Error máximo absoluto", float(np.max(np.abs(r))), "V/celda", "máx |V_modelo−V_exp|."),
            _k("n", "Puntos", float(len(r)), "", "Número de puntos experimentales evaluados."),
            _k("max_delta_motor1_V", "|ΔRMSE| frente al Motor 1", max(deltas) if deltas else None, "V",
               "Diferencia máxima entre el RMSE recalculado y el almacenado en el perfil por el Motor 1.")]
    ctx = {"profile_id": profile["profile_id"], "evaluation_kind": kind, "consistent_with_motor1": consistent,
           "geometry": geometry, "device": profile.get("device"),
           "parameters": [{k: q.get(k) for k in ("name", "symbol", "value", "unit", "origin")} for q in profile.get("parameters", [])]}
    return BenchResult("reproduccion", {"profile_id": profile["profile_id"], "curve_ids": [d["curve_id"] for d in sets]},
                       hyp, warnings, [], kpis, series, {"comparacion": rows, "por_curva": per_curve}, validity, reasons, ctx)


# =====================================================================================================================
# utilidades de inversión P → j vectorizada
# =====================================================================================================================
class _PowerInverse:
    def __init__(self, model: StackModel, j_upper: float):
        self.m = model
        g = np.linspace(0.0, j_upper, 20001)
        p = model.power(g)
        k = int(np.argmax(p))
        self.j_tab, self.p_tab = g[: k + 1], np.maximum.accumulate(p[: k + 1])
        self.p_max = float(self.p_tab[-1])

    def __call__(self, p) -> np.ndarray:
        p = np.asarray(p, float)
        j = np.interp(p, self.p_tab, self.j_tab)
        for _ in range(4):                                   # Newton vectorizado (derivada numérica)
            h = 1e-7
            f = self.m.power(j) - p
            dp = (self.m.power(j + h) - self.m.power(np.maximum(j - h, 0.0))) / (j + h - np.maximum(j - h, 0.0))
            step = np.where((dp > 0) & (p > 0), f / np.where(dp > 0, dp, 1.0), 0.0)
            j = np.clip(j - step, 0.0, self.j_tab[-1])
        return np.where(p <= 0, 0.0, j)


def _intervals(t: np.ndarray, mask: np.ndarray) -> list[tuple[int, int]]:
    out, start = [], None
    for i, m in enumerate(mask):
        if m and start is None:
            start = i
        if not m and start is not None:
            out.append((start, i - 1)); start = None
    if start is not None:
        out.append((start, len(mask) - 1))
    return out


def _cumtrapz(t, y):
    out = np.zeros_like(y)
    out[1:] = np.cumsum(0.5 * (y[1:] + y[:-1]) * np.diff(t))
    return out


def _operate(model: StackModel, t, p_del, inv: _PowerInverse, basis: str) -> dict:
    j = inv(p_del)
    v = model.v_cell(j)
    i = j * model.area
    p = model.n_cells * v * i
    n = model.h2_mol_s(i)
    eta = np.where(p > 0, model.efficiency_from_vcell(v, basis), np.nan)
    return {"j": j, "I": i, "V_cell": v, "V_stack": v * model.n_cells, "P": p, "H2_mol_s": n,
            "H2_g_s": n * M_H2 * 1e3, "H2_cum_g": _cumtrapz(t, n * M_H2 * 1e3), "eta": eta}


# =====================================================================================================================
# 02 — Seguimiento de carga
# =====================================================================================================================
def run_load_following(model: StackModel, demand: TimeSeries, limits: OperatingLimits | None = None,
                       dt_s: float | None = None, basis: str = "LHV") -> BenchResult:
    if demand.quantity != "potencia":
        raise SimulationError("El perfil de demanda debe ser de potencia.")
    limits = limits or OperatingLimits()
    t, p_dem, dt = demand.resample(dt_s)
    cap_i = model.capacity(None)
    cap_r = model.capacity(limits)
    inv_i, inv_r = _PowerInverse(model, cap_i["j_upper"]), _PowerInverse(model, cap_r["j_upper"])
    tol = 1e-6 * max(cap_i["P_max_W"], 1.0)
    # --- modo ideal: solo la capacidad estacionaria del modelo en su dominio
    p_ideal = np.minimum(p_dem, cap_i["P_max_W"])
    # --- modo restringido: límites documentados + rampa (si existe)
    target = np.minimum(p_dem, cap_r["P_max_W"])
    p_restr = target.copy()
    ramp_up = np.zeros_like(t, bool)
    ramp_dn = np.zeros_like(t, bool)
    ru, rd = limits.ramp_up_W_s, limits.ramp_down_W_s
    if ru is not None or rd is not None:
        for k in range(1, len(t)):
            h = t[k] - t[k - 1]
            lo = p_restr[k - 1] - (rd * h if rd is not None else math.inf)
            hi = p_restr[k - 1] + (ru * h if ru is not None else math.inf)
            val = min(max(target[k], lo), hi)
            ramp_up[k] = target[k] > hi + tol
            ramp_dn[k] = target[k] < lo - tol
            p_restr[k] = max(val, 0.0)
    out = {}
    for mode, pd_, inv, cap in (("ideal", p_ideal, inv_i, cap_i), ("restringido", p_restr, inv_r, cap_r)):
        op = _operate(model, t, pd_, inv, basis)
        op["deficit"] = np.maximum(p_dem - op["P"], 0.0)
        op["available"] = np.full_like(t, cap["P_max_W"])
        op["margin"] = np.maximum(cap["P_max_W"] - op["P"], 0.0)
        out[mode] = op
    r = out["restringido"]
    low = (r["j"] > 0) & (r["j"] < model.j_lo)
    cap_hit = p_dem > cap_r["P_max_W"] + tol
    def_mask = r["deficit"] > tol
    events, warnings = [], list(model.warnings)
    for a, b in _intervals(t, def_mask):
        e_wh = float(np.trapezoid(r["deficit"][a:b + 1], t[a:b + 1]) / 3600.0) if b > a else float(r["deficit"][a] * dt / 3600)
        cause = ("rampa" if (ramp_up[a:b + 1].any() or ramp_dn[a:b + 1].any()) and not cap_hit[a:b + 1].any()
                 else "capacidad" if cap_hit[a:b + 1].any() else "límite")
        events.append({"type": "incumplimiento_demanda", "t_start_s": float(t[a]), "t_end_s": float(t[b]),
                       "duration_s": float(t[b] - t[a]), "max_magnitude": float(np.max(r["deficit"][a:b + 1])),
                       "unit": "W", "energy_Wh": e_wh, "cause": cause,
                       "consequence": f"Demanda no atendida: déficit máximo {np.max(r['deficit'][a:b + 1]):.4g} W; "
                                      f"energía no servida {e_wh:.4g} Wh."})
    for a, b in _intervals(t, ramp_up | ramp_dn):
        events.append({"type": "restriccion_rampa", "t_start_s": float(t[a]), "t_end_s": float(t[b]),
                       "duration_s": float(t[b] - t[a]), "max_magnitude": float(np.max(np.abs(target[a:b + 1] - p_restr[a:b + 1]))),
                       "unit": "W", "cause": "rampa de subida" if ramp_up[a:b + 1].any() else "rampa de bajada",
                       "consequence": "La potencia entregada sigue la rampa máxima documentada, no la demanda."})
    for a, b in _intervals(t, low):
        events.append({"type": "baja_carga_fuera_de_dominio", "t_start_s": float(t[a]), "t_end_s": float(t[b]),
                       "duration_s": float(t[b] - t[a]), "max_magnitude": float(model.j_lo - np.min(r["j"][a:b + 1])),
                       "unit": "A/cm²", "cause": "j por debajo del mínimo calibrado",
                       "consequence": "Punto evaluado por extrapolación a baja corriente (sin datos de calibración)."})
    events.sort(key=lambda e: e["t_start_s"])
    if cap_hit.any():
        k = int(np.argmax(p_dem - cap_r["P_max_W"]))
        warnings.append(f"La demanda supera la potencia disponible ({cap_r['P_max_W']:.4g} W, limitada por "
                        f"{cap_r['binding']}) durante {float(np.sum(np.diff(t)[cap_hit[1:]])):.4g} s; exceso máximo "
                        f"{p_dem[k] - cap_r['P_max_W']:.4g} W en t = {t[k]:.4g} s. No se inventa respuesta: se registra déficit.")
    if ru is None and rd is None:
        warnings.append("Sin restricción de rampa evaluada: no se dispone de límites de rampa documentados. Esto NO "
                        "implica capacidad dinámica ilimitada; el resultado solo describe la capacidad estacionaria.")
    if not limits.any_static():
        warnings.append("Sin límites operacionales documentados (corriente, potencia o tensión mínima): el modo "
                        "restringido solo aplica el dominio de validez del modelo y coincide con el ideal salvo rampas.")
    if low.any():
        warnings.append(f"Hay {int(low.sum())} instantes con j por debajo del mínimo calibrado ({model.j_lo:g} A/cm²): "
                        "baja carga evaluada por extrapolación.")
    if not cap_i["interior_max"]:
        warnings.append(f"La potencia máxima del modelo no tiene máximo interior en el dominio: la capacidad "
                        f"({cap_i['P_max_W']:.4g} W) está fijada por el borde del dominio calibrado, no por el stack.")
    hyp = list(model.hypotheses) + [
        f"Perfil de demanda interpretado como {demand.interpolation}; evaluación en una rejilla uniforme de paso "
        f"{dt:.4g} s ({len(t)} instantes); integrales por regla del trapecio.",
        "Para cada potencia se elige la MENOR corriente que la entrega (rama de mayor eficiencia de la curva P–j).",
        "Potencia cero = stack sin carga (j = 0): sin consumo faradaico; la eficiencia no se define en P = 0.",
        f"Eficiencia: η = P / (ṅ_H₂,consumido · {basis}) = V_celda / {HEATING[basis] / (2 * F):.4f} V (stack, sin BoP).",
        "Consumo de H₂ teórico (faradaico): ṅ = N·I/(2F); no incluye purgas, fugas ni H₂ no reaccionado.",
        "Respuesta cuasiestacionaria: NO representa transitorios electroquímicos, dinámica de gases ni térmica."]
    if ru is not None or rd is not None:
        hyp.append(f"Rampas documentadas: subida {ru if ru is not None else '—'} W/s, bajada "
                   f"{rd if rd is not None else '—'} W/s ({limits.source or 'procedencia no indicada'}); "
                   "estado inicial = demanda alcanzable en t₀.")
    e_dem = float(np.trapezoid(p_dem, t) / 3600.0)
    kpis = []
    for mode in ("restringido", "ideal"):
        o = out[mode]
        e_del = float(np.trapezoid(o["P"], t) / 3600.0)
        h2 = float(np.trapezoid(o["H2_mol_s"], t))
        on = o["P"] > 0
        sfx = "" if mode == "restringido" else "_ideal"
        lab = "" if mode == "restringido" else " (ideal)"
        kpis += [_k("E_del" + sfx, "Energía entregada" + lab, e_del / 1000, "kWh", "∫ P_entregada dt."),
                 _k("E_uns" + sfx, "Energía no atendida" + lab, (e_dem - e_del) / 1000, "kWh", "∫ (P_demandada − P_entregada) dt."),
                 _k("pct_energy" + sfx, "Demanda satisfecha (energía)" + lab, 100 * e_del / e_dem if e_dem > 0 else None, "%",
                    "100 · E_entregada / E_demandada."),
                 _k("H2_g" + sfx, "H₂ consumido (teórico)" + lab, h2 * M_H2 * 1e3, "g", "∫ N·I/(2F) dt · M_H₂."),
                 _k("eta_energy" + sfx, "Eficiencia media ponderada por energía" + lab,
                    100 * e_del * 3600 / (h2 * HEATING[basis]) if h2 > 0 else None, "%",
                    f"E_entregada / (n_H₂,consumido · {basis}). Ponderada por energía."),
                 ]
        if mode == "restringido":
            kpis += [_k("eta_time", "Eficiencia media temporal", 100 * float(np.nanmean(o["eta"][on])) if on.any() else None, "%",
                        "Media aritmética de η(t) sobre los instantes con P > 0 (no ponderada)."),
                     _k("H2_NL", "H₂ consumido (teórico)", h2 * VM_NORMAL, "NL", "Volumen normal (0 °C, 1 atm)."),
                     _k("P_del_max", "Potencia máxima entregada", float(np.max(o["P"])), "W", "máx P_entregada(t)."),
                     _k("pct_time", "Tiempo con demanda satisfecha", 100 * float(np.mean(~def_mask)), "%",
                        "Fracción de instantes de la rejilla sin déficit."),
                     _k("t_limited_s", "Tiempo con restricción activa",
                        float(np.sum((def_mask | ramp_up | ramp_dn)[1:] * np.diff(t))), "s",
                        "Tiempo con déficit o rampa activa (operación en el límite)."),
                     _k("t_low_s", "Tiempo fuera del dominio calibrado (baja carga)", float(np.sum(low[1:] * np.diff(t))), "s",
                        "Tiempo con 0 < j < j_mín calibrado."),
                     _k("n_deficit_events", "Eventos de incumplimiento", float(sum(e["type"] == "incumplimiento_demanda" for e in events)), "", "Intervalos contiguos con déficit."),
                     _k("n_ramp_events", "Eventos de restricción de rampa",
                        float(sum(e["type"] == "restriccion_rampa" for e in events)) if (ru is not None or rd is not None) else None, "",
                        "Intervalos con rampa activa (solo si hay rampa documentada).")]
    kpis = [_k("E_dem", "Energía demandada", e_dem / 1000, "kWh", "∫ P_demandada dt."),
            _k("P_dem_max", "Potencia máxima demandada", float(np.max(p_dem)), "W", "máx P_demandada(t)."),
            _k("P_avail", "Potencia disponible (estacionaria)", cap_r["P_max_W"], "W",
               f"Máximo de P(j) en el dominio admisible; restricción: {cap_r['binding']}.")] + kpis
    series = {"t_s": _lst(t), "P_dem_W": _lst(p_dem)}
    for mode, o in out.items():
        sfx = "" if mode == "restringido" else "_ideal"
        for name, key in (("P_del_W", "P"), ("deficit_W", "deficit"), ("margin_W", "margin"), ("P_avail_W", "available"),
                          ("I_A", "I"), ("j_A_cm2", "j"), ("V_cell_V", "V_cell"), ("V_stack_V", "V_stack"),
                          ("H2_g_s", "H2_g_s"), ("H2_cum_g", "H2_cum_g"), ("eta", "eta")):
            series[name + sfx] = _lst(o[key])
    series["ramp_active"] = [bool(a or b) for a, b in zip(ramp_up, ramp_dn)]
    validity, reasons = _validity(model, warnings, ["Extrapolación a baja carga en algunos instantes."] if low.any() else [])
    if def_mask.any() and validity == V_OK:
        validity = V_WARN
    return BenchResult("carga", {"demand": demand.to_dict(), "limits": limits.to_dict(), "dt_s": dt, "basis": basis,
                                 "conditions": model.summary()["conditions"], "j_domain": [model.j_lo, model.j_hi]},
                       hyp, warnings, events, kpis, series, {}, validity, reasons,
                       {"capacity_ideal": cap_i, "capacity_restricted": cap_r, "model": model.summary()})


# =====================================================================================================================
# 03 — Alimentación de hidrógeno
# =====================================================================================================================
POLICIES = {"corriente": "Corriente objetivo [A]", "potencia": "Potencia objetivo [W]",
            "utilizacion": "Utilización de combustible objetivo [–]", "max_potencia": "Máxima potencia factible"}


def run_hydrogen(model: StackModel, feed: TimeSeries, policy: str, value: float | None = None,
                 u_max: float | None = None, limits: OperatingLimits | None = None, dt_s: float | None = None,
                 basis: str = "LHV") -> BenchResult:
    if feed.quantity != "caudal_H2":
        raise SimulationError("El perfil de alimentación debe ser un caudal de H₂.")
    if policy not in POLICIES:
        raise SimulationError(f"Política no admitida: {policy}.")
    if policy in ("corriente", "potencia", "utilizacion") and (value is None or not math.isfinite(value) or value <= 0):
        raise SimulationError(f"La política «{POLICIES[policy]}» necesita un valor positivo.")
    if policy == "utilizacion" and value > 1:
        raise SimulationError("La utilización de combustible no puede superar 1 (no se consume más H₂ del alimentado).")
    if policy == "max_potencia" and u_max is None:
        raise SimulationError("«Máxima potencia factible» requiere la utilización máxima admisible del stack (dato del "
                              "dispositivo o criterio de operación). Sin ella el problema no está cerrado: usar 1,0 "
                              "supondría consumir todo el H₂ alimentado.")
    if u_max is not None and not (0 < u_max <= 1):
        raise SimulationError("La utilización máxima debe estar en (0, 1].")
    limits = limits or OperatingLimits()
    u_lim = 1.0 if u_max is None else float(u_max)
    t, n_fed, dt = feed.resample(dt_s)
    cap = model.capacity(limits)
    j_up = cap["j_upper"]
    i_up = min(j_up * model.area, cap["I_at_Pmax_A"]) if limits.power_max_W is not None else j_up * model.area
    i_fuel = u_lim * n_fed * 2 * F / model.n_cells
    if policy == "corriente":
        i_req = np.full_like(t, value)
    elif policy == "potencia":
        if value > cap["P_max_W"]:
            i_req = np.full_like(t, cap["I_at_Pmax_A"])
        else:
            i_req = np.full_like(t, model.j_for_power(value, cap["j_at_Pmax"]) * model.area)
    elif policy == "utilizacion":
        i_req = value * n_fed * 2 * F / model.n_cells
    else:
        i_req = np.full_like(t, cap["I_at_Pmax_A"])
    i = np.minimum.reduce([i_req, i_fuel, np.full_like(t, i_up)])
    i = np.maximum(i, 0.0)
    fuel_lim = (i_fuel < i_req - 1e-12) & (i_fuel <= i_up + 1e-12)
    cur_lim = (i_up < i_req - 1e-12) & ~fuel_lim
    j = i / model.area
    v = model.v_cell(j)
    p = model.n_cells * v * i
    n_cons = model.h2_mol_s(i)
    util = np.where(n_fed > 0, n_cons / np.where(n_fed > 0, n_fed, 1.0), np.nan)
    eta_c = np.where(p > 0, model.efficiency_from_vcell(v, basis), np.nan)
    eta_f = np.where((p > 0) & (n_fed > 0), p / (np.where(n_fed > 0, n_fed, 1.0) * HEATING[basis]), np.nan)
    p_target_def = np.maximum(value - p, 0.0) if policy == "potencia" else np.zeros_like(t)
    low = (j > 0) & (j < model.j_lo)
    events, warnings = [], list(model.warnings)
    for a, b in _intervals(t, fuel_lim):
        events.append({"type": "limitado_por_combustible", "t_start_s": float(t[a]), "t_end_s": float(t[b]),
                       "duration_s": float(t[b] - t[a]), "max_magnitude": float(np.max(i_req[a:b + 1] - i[a:b + 1])),
                       "unit": "A", "cause": f"alimentación insuficiente (u ≤ {u_lim:g})",
                       "consequence": "La corriente se reduce a la que permite el H₂ alimentado; la política no se cumple."})
    for a, b in _intervals(t, cur_lim):
        events.append({"type": "limite_corriente", "t_start_s": float(t[a]), "t_end_s": float(t[b]),
                       "duration_s": float(t[b] - t[a]), "max_magnitude": float(np.max(i_req[a:b + 1] - i[a:b + 1])),
                       "unit": "A", "cause": cap["binding"], "consequence": "Corriente recortada al límite admisible."})
    for a, b in _intervals(t, low):
        events.append({"type": "baja_carga_fuera_de_dominio", "t_start_s": float(t[a]), "t_end_s": float(t[b]),
                       "duration_s": float(t[b] - t[a]), "max_magnitude": float(model.j_lo - np.min(j[a:b + 1])),
                       "unit": "A/cm²", "cause": "j por debajo del mínimo calibrado",
                       "consequence": "Punto evaluado por extrapolación a baja corriente."})
    events.sort(key=lambda e: e["t_start_s"])
    if policy == "potencia" and value > cap["P_max_W"]:
        warnings.append(f"La potencia objetivo ({value:g} W) supera la potencia disponible ({cap['P_max_W']:.4g} W): "
                        "se opera en el máximo admisible y se registra déficit.")
    if fuel_lim.any():
        warnings.append(f"Operación limitada por combustible durante {float(np.sum(fuel_lim[1:] * np.diff(t))):.4g} s.")
    if u_max is None:
        warnings.append("Sin utilización máxima documentada: solo se aplica el límite estequiométrico (u ≤ 1), que es "
                        "una cota física, no un punto de operación realista.")
    hyp = list(model.hypotheses) + [
        f"Política de operación: {POLICIES[policy]}" + (f" = {value:g}" if value is not None else "") + ". El caudal "
        "alimentado por sí solo no determina el punto de operación; la política cierra el problema.",
        "H₂ consumido = N·I/(2F) (faradaico). El H₂ alimentado NO se supone totalmente reaccionado: "
        "utilización u = consumido/alimentado ≤ u_máx.",
        f"η_consumido = P/(ṅ_consumido·{basis}); η_alimentado = P/(ṅ_alimentado·{basis}) = η_consumido · u.",
        f"Caudal interpretado como {feed.interpolation}, rejilla de paso {dt:.4g} s; integrales por trapecio.",
        "No se modelan presión/estequiometría del ánodo, recirculación, purgas ni dinámica de gases: el caudal "
        "solo limita la corriente por conservación de masa."]
    e = float(np.trapezoid(p, t) / 3600.0)
    nf, nc = float(np.trapezoid(n_fed, t)), float(np.trapezoid(n_cons, t))
    kpis = [_k("E_prod", "Energía producida", e / 1000, "kWh", "∫ P dt."),
            _k("H2_fed_g", "H₂ alimentado", nf * M_H2 * 1e3, "g", "∫ ṅ_alimentado dt · M_H₂."),
            _k("H2_cons_g", "H₂ consumido (teórico)", nc * M_H2 * 1e3, "g", "∫ N·I/(2F) dt · M_H₂."),
            _k("H2_excess_g", "H₂ no consumido", (nf - nc) * M_H2 * 1e3, "g", "Alimentado − consumido (sale sin reaccionar)."),
            _k("u_mean", "Utilización global", 100 * nc / nf if nf > 0 else None, "%", "100 · n_consumido / n_alimentado (totales)."),
            _k("P_max", "Potencia máxima", float(np.max(p)), "W", "máx P(t)."),
            _k("eta_cons", "Eficiencia (H₂ consumido)", 100 * e * 3600 / (nc * HEATING[basis]) if nc > 0 else None, "%",
               f"E / (n_consumido · {basis}), ponderada por energía."),
            _k("eta_fed", "Eficiencia (H₂ alimentado)", 100 * e * 3600 / (nf * HEATING[basis]) if nf > 0 else None, "%",
               f"E / (n_alimentado · {basis}), ponderada por energía."),
            _k("t_fuel_limited_s", "Tiempo limitado por combustible", float(np.sum(fuel_lim[1:] * np.diff(t))), "s",
               "Tiempo en que el H₂ alimentado impide cumplir la política.")]
    if policy == "potencia":
        kpis.append(_k("E_uns", "Energía no atendida", float(np.trapezoid(p_target_def, t) / 3.6e6), "kWh",
                       "∫ (P_objetivo − P) dt."))
    series = {"t_s": _lst(t), "H2_fed_g_s": _lst(n_fed * M_H2 * 1e3), "H2_cons_g_s": _lst(n_cons * M_H2 * 1e3),
              "H2_fed_cum_g": _lst(_cumtrapz(t, n_fed * M_H2 * 1e3)), "H2_cons_cum_g": _lst(_cumtrapz(t, n_cons * M_H2 * 1e3)),
              "utilization": _lst(util), "I_req_A": _lst(i_req), "I_A": _lst(i), "j_A_cm2": _lst(j), "V_cell_V": _lst(v),
              "V_stack_V": _lst(v * model.n_cells), "P_W": _lst(p), "E_cum_Wh": _lst(_cumtrapz(t, p) / 3600.0),
              "eta_cons": _lst(eta_c), "eta_fed": _lst(eta_f), "fuel_limited": [bool(x) for x in fuel_lim],
              "P_target_deficit_W": _lst(p_target_def)}
    validity, reasons = _validity(model, warnings, ["Extrapolación a baja carga en algunos instantes."] if low.any() else [])
    return BenchResult("hidrogeno", {"feed": feed.to_dict(), "policy": policy, "value": value, "u_max": u_max,
                                     "limits": limits.to_dict(), "dt_s": dt, "basis": basis,
                                     "conditions": model.summary()["conditions"]},
                       hyp, warnings, events, kpis, series, {}, validity, reasons,
                       {"capacity": cap, "model": model.summary()})


# =====================================================================================================================
# 04 — Optimización operacional
# =====================================================================================================================
OBJECTIVES = {"max_potencia": "Maximizar potencia eléctrica", "max_eficiencia": "Maximizar eficiencia",
              "min_consumo": "Minimizar consumo específico de H₂", "potencia_objetivo": "Punto factible para una potencia objetivo",
              "compromiso": "Compromiso potencia–eficiencia (frontera de Pareto)"}


def run_optimization(model: StackModel, objective: str, limits: OperatingLimits | None = None,
                     p_min_useful_W: float | None = None, p_target_W: float | None = None,
                     h2_feed_max_mol_s: float | None = None, u_max: float | None = None,
                     basis: str = "LHV", n_grid: int = 4001) -> BenchResult:
    if objective not in OBJECTIVES:
        raise SimulationError(f"Objetivo no admitido: {objective}.")
    if objective == "potencia_objetivo" and (p_target_W is None or p_target_W <= 0):
        raise SimulationError("Indique la potencia objetivo (W).")
    limits = limits or OperatingLimits()
    j_up, why_up = model.admissible_upper(limits)
    active_upper = why_up
    if h2_feed_max_mol_s is not None:
        u = 1.0 if u_max is None else u_max
        j_fuel = u * h2_feed_max_mol_s * 2 * F / (model.n_cells * model.area)
        if j_fuel < j_up:
            j_up, active_upper = j_fuel, f"alimentación máxima de H₂ (u ≤ {u:g})"
    if j_up <= model.j_lo:
        raise SimulationError(f"Dominio admisible vacío: el límite superior ({active_upper}) queda por debajo del "
                              f"mínimo calibrado ({model.j_lo:g} A/cm²).")
    g = np.linspace(model.j_lo, j_up, n_grid)
    v = model.v_cell(g)
    p = model.power(g)
    eta = model.efficiency_from_vcell(v, basis)
    n = model.h2_mol_s(g * model.area)
    sfc = n * M_H2 * 1e3 * 3600.0 / (p / 1000.0)
    feas = np.ones_like(g, bool)
    reasons_mask = []
    if limits.power_max_W is not None:
        feas &= p <= limits.power_max_W + 1e-9
        reasons_mask.append(f"P ≤ {limits.power_max_W:g} W (documentada)")
    if p_min_useful_W is not None:
        feas &= p >= p_min_useful_W - 1e-9
        reasons_mask.append(f"P ≥ {p_min_useful_W:g} W (potencia mínima útil)")
    warnings, hyp = list(model.warnings), list(model.hypotheses)
    hyp += [f"Búsqueda sobre {n_grid} puntos del dominio admisible j ∈ [{model.j_lo:.4g}, {j_up:.4g}] A/cm² "
            f"(cota superior: {active_upper}); refinamiento local acotado del óptimo.",
            f"η = V_celda / {HEATING[basis] / (2 * F):.4f} V ({basis}, H₂ consumido); consumo específico "
            "SFC = ṁ_H₂/P = M_H₂/(2F·V_celda) → minimizar SFC equivale a maximizar η (ambos dependen solo de V_celda).",
            "Restricciones adicionales: " + ("; ".join(reasons_mask) if reasons_mask else "ninguna documentada") + "."]
    if not feas.any():
        raise SimulationError("Ningún punto del dominio admisible cumple las restricciones indicadas.")
    idx = np.nonzero(feas)[0]

    def pick(score):
        k = idx[int(np.argmax(score[idx]))]
        return k

    selected, explanation, frontier = None, "", []
    kmax_p = pick(p)
    if objective == "max_potencia":
        k = kmax_p
        from scipy.optimize import minimize_scalar
        if 0 < k < n_grid - 1 and feas[k - 1] and feas[k + 1]:
            r = minimize_scalar(lambda x: -float(model.power(x)), bounds=(g[k - 1], g[k + 1]), method="bounded",
                                options={"xatol": 1e-12})
            selected = float(r.x)
            explanation = "Máximo interior de P(j): dP/dj = 0 (las pérdidas crecen más rápido que la corriente)."
        else:
            selected = float(g[k])
            explanation = ("El máximo se alcanza en el BORDE del conjunto admisible (" +
                           (active_upper if k == n_grid - 1 else "restricción de potencia") + "): no es un máximo del "
                           "stack sino de la región donde el modelo está respaldado/permitido.")
    elif objective in ("max_eficiencia", "min_consumo"):
        k = pick(eta) if objective == "max_eficiencia" else idx[int(np.argmin(sfc[idx]))]
        selected = float(g[k])
        if p_min_useful_W is not None and k > 0 and k == idx[0] and p[k - 1] < p_min_useful_W <= p[k]:
            selected = float(brentq(lambda x: float(model.power(x)) - p_min_useful_W, g[k - 1], g[k], xtol=1e-14))
        if not np.all(np.diff(eta[idx]) <= 1e-12):
            hyp.append("η(j) no es monótona en el dominio admisible: el óptimo se toma del barrido numérico.")
        explanation = ("η y SFC dependen solo de V_celda, que decrece con j: el óptimo es la menor corriente admisible"
                       + (" que cumple la potencia mínima útil." if p_min_useful_W is not None else "."))
        if p_min_useful_W is None:
            warnings.append("Sin potencia mínima útil: el óptimo de eficiencia es trivial (la menor corriente del dominio, "
                            f"P = {p[k]:.4g} W, {100 * p[k] / p[kmax_p]:.2g} % de la potencia máxima). Defina una "
                            "potencia mínima útil para obtener un punto operacionalmente significativo.")
        if objective == "min_consumo":
            hyp.append("Este objetivo es EQUIVALENTE a maximizar la eficiencia bajo las hipótesis adoptadas.")
    elif objective == "potencia_objetivo":
        if p_target_W > p[kmax_p] + 1e-9:
            raise SimulationError(f"La potencia objetivo ({p_target_W:g} W) supera la máxima admisible "
                                  f"({p[kmax_p]:.4g} W, {active_upper}).")
        selected = model.j_for_power(p_target_W, float(g[kmax_p]))
        if selected < model.j_lo:
            warnings.append("La potencia objetivo exige j por debajo del mínimo calibrado (extrapolación a baja carga).")
        explanation = ("De las corrientes que entregan esa potencia se elige la menor (rama ascendente de P–j), que tiene "
                       "mayor tensión y por tanto mayor eficiencia y menor consumo.")
        hi_branch = np.nonzero((p[kmax_p:] <= p_target_W) & feas[kmax_p:])[0]
        if hi_branch.size:
            warnings.append("Existe una segunda solución en la rama descendente (mayor corriente), menos eficiente; se descarta.")
    else:   # compromiso
        sel = idx[g[idx] <= g[kmax_p] + 1e-15]
        frontier = [int(x) for x in sel]
        pn = (p[sel] - p[sel].min()) / max(np.ptp(p[sel]), 1e-30)
        en = (eta[sel] - eta[sel].min()) / max(np.ptp(eta[sel]), 1e-30)
        knee = sel[int(np.argmin(np.hypot(1 - pn, 1 - en)))]
        selected = float(g[knee])
        explanation = ("Frontera de Pareto: entre j_mín y j(P_máx) aumentar la potencia reduce la eficiencia; ningún punto "
                       "domina a otro. Se señala el punto más cercano al ideal (P y η normalizados = 1) como referencia, "
                       "no como óptimo único: la elección depende de los criterios del usuario.")
    op = model.operating_point(selected, basis)
    act = []
    if abs(selected - j_up) <= 1e-9 * max(j_up, 1):
        act.append(active_upper)
    if abs(selected - model.j_lo) <= 1e-12:
        act.append("densidad mínima del dominio calibrado")
    if p_min_useful_W is not None and abs(op["P_W"] - p_min_useful_W) <= 1e-6 * max(p_min_useful_W, 1):
        act.append("potencia mínima útil")
    if limits.power_max_W is not None and abs(op["P_W"] - limits.power_max_W) <= 1e-6 * limits.power_max_W:
        act.append("potencia máxima documentada")
    comps = []
    for name, kk in (("Máxima potencia", kmax_p), ("Máxima eficiencia (admisible)", pick(eta)),
                     ("Borde inferior del dominio", 0), ("Borde superior del dominio", n_grid - 1)):
        o = model.operating_point(float(g[kk]), basis)
        comps.append({"punto": name, "admisible": bool(feas[kk]), **{k: o[k] for k in ("j_A_cm2", "I_A", "V_cell_V", "P_W", "eta", "SFC_g_kWh", "H2_g_s")}})
    comps.insert(0, {"punto": "SELECCIONADO", "admisible": True, **{k: op[k] for k in ("j_A_cm2", "I_A", "V_cell_V", "P_W", "eta", "SFC_g_kWh", "H2_g_s")}})
    kpis = [_k("j", "Densidad de corriente", op["j_A_cm2"], "A/cm²", "Punto seleccionado."),
            _k("I", "Corriente", op["I_A"], "A", "I = j·A."),
            _k("V_cell", "Tensión de celda", op["V_cell_V"], "V", "Modelo del perfil."),
            _k("V_stack", "Tensión de stack", op["V_stack_V"], "V", "N·V_celda."),
            _k("P", "Potencia", op["P_W"], "W", "N·V_celda·I."),
            _k("H2_g_s", "Consumo de H₂ (teórico)", op["H2_g_s"], "g/s", "N·I/(2F)·M_H₂."),
            _k("eta", "Eficiencia", 100 * op["eta"], "%", f"V_celda / {HEATING[basis] / (2 * F):.4f} V ({basis})."),
            _k("SFC", "Consumo específico", op["SFC_g_kWh"], "g/kWh", "ṁ_H₂ / P.")]
    series = {"j_A_cm2": _lst(g), "P_W": _lst(p), "V_cell_V": _lst(v), "eta": _lst(eta), "SFC_g_kWh": _lst(sfc),
              "feasible": [bool(x) for x in feas], "frontier_idx": frontier}
    validity, reasons = _validity(model, warnings, [])
    return BenchResult("optimizacion", {"objective": objective, "limits": limits.to_dict(), "p_min_useful_W": p_min_useful_W,
                                        "p_target_W": p_target_W, "h2_feed_max_mol_s": h2_feed_max_mol_s, "u_max": u_max,
                                        "basis": basis, "conditions": model.summary()["conditions"]},
                       hyp, warnings, [], kpis, series, {"comparacion": comps}, validity, reasons,
                       {"selected": op, "active_constraints": act, "explanation": explanation, "j_upper": j_up,
                        "upper_binding": active_upper, "model": model.summary()})
