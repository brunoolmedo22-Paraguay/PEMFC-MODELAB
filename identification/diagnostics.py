"""Métricas de ajuste y diagnóstico de identificabilidad local.

Todo diagnóstico es LOCAL (linealización en el óptimo) y condicionado a la
estructura del modelo. No sustituye a una validación experimental.

Umbrales (decisiones de ModelLab, editables aquí y documentados en docs/):
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

COND_ILL = 1e6          # condición del Jacobiano escalado: mal condicionado
COND_SINGULAR = 1e10    # prácticamente singular
REL_SE_WEAK = 0.5       # error estándar relativo > 50 %
CORR_STRONG = 0.99      # |correlación| > 0,99
SPREAD_WEAK = 0.05      # dispersión multistart > 5 % del rango admisible
BOUND_TOL = 1e-3        # a menos de 0,1 % del rango de un límite
PRIOR_DOMINANCE = 0.7   # σ_post / σ_prior > 0,7 => determinado por el prior
EQUIVALENT_COST = 1.01  # inicios con coste ≤ 1,01 × mejor se consideran equivalentes
RUNS_Z = -2.5           # z del test de rachas para avisar de residuo sistemático

ID_OK = "IDENTIFICADO_LOCALMENTE"
ID_WEAK = "DÉBIL"
ID_NONE = "NO_IDENTIFICABLE"
ID_FIXED = "NO_AJUSTADO"


def voltage_metrics(residual_V: np.ndarray, observed_V: np.ndarray) -> dict:
    """Métricas de tensión [V]. El error relativo solo si |V_obs| ≥ 0,05 V en todos los puntos."""
    r = np.asarray(residual_V, float)
    o = np.asarray(observed_V, float)
    if r.size == 0:
        return {"n": 0}
    out = {
        "n": int(r.size),
        "rmse_V": float(np.sqrt(np.mean(r ** 2))),
        "mae_V": float(np.mean(np.abs(r))),
        "max_abs_V": float(np.max(np.abs(r))),
        "bias_V": float(np.mean(r)),
    }
    out["mape_percent"] = float(100 * np.mean(np.abs(r) / np.abs(o))) if np.min(np.abs(o)) >= 0.05 else None
    return out


def runs_test(residuals_sorted: np.ndarray) -> dict:
    """Test de rachas de Wald–Wolfowitz sobre el signo de los residuos ordenados por j."""
    r = np.asarray(residuals_sorted, float)
    s = np.sign(r[r != 0])
    n = s.size
    n_pos, n_neg = int((s > 0).sum()), int((s < 0).sum())
    if n < 6:
        return {"n": n, "runs": None, "z": None, "systematic": False}
    if n_pos == 0 or n_neg == 0:
        return {"n": n, "runs": 1, "z": -math.inf, "systematic": True}
    runs = 1 + int((s[1:] != s[:-1]).sum())
    mu = 2 * n_pos * n_neg / n + 1
    var = (mu - 1) * (mu - 2) / (n - 1)
    z = (runs - mu) / math.sqrt(var) if var > 0 else 0.0
    return {"n": n, "runs": runs, "z": float(z), "systematic": bool(z < RUNS_Z)}


def identifiability(
    *,
    names: list[str],
    x: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    scales: np.ndarray,
    jac_data: np.ndarray,
    jac_full: np.ndarray,
    ssr_weighted: float,
    n_data: int,
    sigma_declared: bool,
    prior_sigma: dict[str, float],
    runs: pd.DataFrame,
    best_cost: float,
) -> dict:
    """Diagnóstico local de identificabilidad en el óptimo."""
    p = len(names)
    dof = n_data - p
    warnings: list[str] = []
    js = jac_data @ np.diag(scales)
    sv = np.linalg.svd(js, compute_uv=False) if js.size else np.zeros(p)
    _, _, vt = np.linalg.svd(js, full_matrices=True) if js.size else (None, None, np.eye(p))
    sv_full = np.zeros(p)
    sv_full[: sv.size] = sv
    smax = float(sv_full.max()) if p else 0.0
    smin = float(sv_full.min()) if p else 0.0
    cond = math.inf if smin <= smax * 1e-15 else smax / smin
    rank = int((sv_full > smax * 1e-10).sum()) if smax > 0 else 0
    weakest = vt[-1] if p else np.array([])
    weakest_combo = {n: float(c) for n, c in zip(names, weakest) if abs(c) > 0.3}

    jtj = jac_full.T @ jac_full
    cov_unit = np.linalg.pinv(jtj, rcond=1e-15)
    if sigma_declared:
        s2 = 1.0
        cov_basis = "incertidumbre σ_V declarada por el usuario"
    elif dof > 0:
        s2 = ssr_weighted / dof
        cov_basis = "varianza residual estimada (SSR/(n−p)); sin incertidumbre declarada"
    else:
        s2 = math.nan
        cov_basis = "no estimable (n ≤ p y sin σ declarada)"
    cov = cov_unit * s2
    se = np.sqrt(np.clip(np.diag(cov), 0, None)) if np.isfinite(s2) else np.full(p, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.sqrt(np.clip(np.diag(cov_unit), 1e-300, None))
        corr = cov_unit / np.outer(sd, sd)
    corr = np.clip(corr, -1, 1)

    rel_pos = (x - lower) / np.where(upper > lower, upper - lower, 1.0)
    at_bound = (rel_pos < BOUND_TOL) | (rel_pos > 1 - BOUND_TOL)

    spread = np.zeros(p)
    n_equiv = 0
    if runs is not None and len(runs) and np.isfinite(best_cost):
        ok = runs[np.isfinite(runs["cost"]) & (runs["cost"] <= best_cost * EQUIVALENT_COST + 1e-300)]
        n_equiv = len(ok)
        if n_equiv > 1:
            vals = ok[[f"x_{n}" for n in names]].to_numpy(float)
            spread = (vals.max(0) - vals.min(0)) / np.where(upper > lower, upper - lower, 1.0)

    col_norm = np.linalg.norm(js, axis=0) if js.size else np.zeros(p)
    no_sens = col_norm <= (col_norm.max() if col_norm.size else 0) * 1e-12

    rows = []
    for k, n in enumerate(names):
        reasons = []
        rel_se = se[k] / abs(x[k]) if (np.isfinite(se[k]) and abs(x[k]) > 0) else math.nan
        others = np.delete(np.abs(corr[k]), k) if p > 1 else np.array([0.0])
        max_corr = float(others.max()) if others.size else 0.0
        partner = names[[i for i in range(p) if i != k][int(others.argmax())]] if p > 1 else ""
        prior_dom = None
        if n in prior_sigma and sigma_declared and np.isfinite(se[k]):
            prior_dom = float(se[k] / prior_sigma[n])
        level = ID_OK
        if no_sens[k]:
            level, reasons = ID_NONE, ["sin sensibilidad de la tensión a este parámetro en los datos"]
        elif dof <= 0 and n not in prior_sigma:
            level, reasons = ID_NONE, ["puntos de datos ≤ parámetros libres"]
        elif cond >= COND_SINGULAR and abs(weakest[k]) > 0.3:
            level, reasons = ID_NONE, ["participa en una dirección casi singular del Jacobiano"]
        else:
            if np.isfinite(rel_se) and rel_se > REL_SE_WEAK:
                reasons.append(f"error estándar relativo {100 * rel_se:.0f} %")
            if max_corr > CORR_STRONG:
                reasons.append(f"|ρ| = {max_corr:.3f} con {partner}")
            if spread[k] > SPREAD_WEAK:
                reasons.append(f"dispersión multistart {100 * spread[k]:.0f} % del rango")
            if at_bound[k]:
                reasons.append("en un límite (resultado condicionado por el límite)")
            if prior_dom is not None and prior_dom > PRIOR_DOMINANCE:
                reasons.append("determinado principalmente por el prior")
            if cond >= COND_ILL and abs(weakest[k]) > 0.5:
                reasons.append("domina la dirección peor condicionada")
            if reasons:
                level = ID_WEAK
        rows.append({
            "parameter": n, "value": float(x[k]), "std_error": float(se[k]) if np.isfinite(se[k]) else None,
            "relative_std_error": float(rel_se) if np.isfinite(rel_se) else None,
            "max_abs_correlation": max_corr, "most_correlated_with": partner,
            "at_bound": bool(at_bound[k]), "multistart_spread": float(spread[k]),
            "prior_ratio": prior_dom, "identifiability": level, "reasons": reasons,
        })

    if dof <= 0:
        warnings.append(f"Grados de libertad de los datos = {dof}: hay tantos o más parámetros libres que puntos. "
                        "La solución no está determinada por los datos.")
    if cond >= COND_SINGULAR:
        warnings.append(f"Jacobiano escalado prácticamente singular (condición {cond:.2e}). Hay combinaciones de "
                        "parámetros que los datos no distinguen.")
    elif cond >= COND_ILL:
        warnings.append(f"Problema mal condicionado (condición {cond:.2e}): parámetros fuertemente correlacionados.")
    if rank < p:
        warnings.append(f"Rango numérico del Jacobiano {rank} < {p} parámetros libres.")
    if any(r["identifiability"] != ID_OK for r in rows):
        weak = [r["parameter"] for r in rows if r["identifiability"] != ID_OK]
        warnings.append("Parámetros no identificados de forma robusta: " + ", ".join(weak) +
                        ". Sus valores son efectivos y no deben interpretarse como propiedades físicas.")
    return {
        "n_data": n_data, "n_free": p, "dof": dof,
        "singular_values": [float(s) for s in sv_full],
        "condition_number": float(cond), "rank": rank,
        "weakest_direction": weakest_combo,
        "covariance_basis": cov_basis,
        "correlation": pd.DataFrame(corr, index=names, columns=names),
        "parameters": pd.DataFrame(rows),
        "n_equivalent_starts": n_equiv,
        "warnings": warnings,
    }
