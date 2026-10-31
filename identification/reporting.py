"""Curvas densas, figuras, reporte Markdown y ZIP de experimento.

Las curvas se calculan con pemfc_core.model (el mismo núcleo del ajuste).
"""
from __future__ import annotations

import io
import json
import zipfile

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pemfc_core import model as core  # noqa: E402
from pemfc_core.parameters import PARAMETER_INFO, ModelParameters  # noqa: E402
from pemfc_core.schemas import ROLE_CALIBRATION, STATUS_DESCRIPTIONS, DeviceInfo  # noqa: E402

from .datasets import PolarizationCurve  # noqa: E402
from .optimizer import FitResult  # noqa: E402
from .profiles import profile_to_json  # noqa: E402

PALETTE = ["#1f5f8b", "#c0392b", "#2e8b57", "#8e44ad", "#d68910", "#17a2b8", "#6c757d", "#a0522d"]


def model_curves(params: ModelParameters, curves: list[PolarizationCurve], device: DeviceInfo | None = None,
                 points: int = 200, extend_to: float | None = None) -> pd.DataFrame:
    """Curva del modelo para cada condición, en el rango de datos de la curva.

    Si `extend_to` > j_max, añade una zona marcada `extrapolated=True`.
    """
    frames = []
    for c in curves:
        lo, hi = float(c.j_A_cm2.min()), float(c.j_A_cm2.max())
        top = max(hi, extend_to or hi)
        j = np.unique(np.concatenate([np.linspace(lo, hi, points), np.linspace(hi, top, max(points // 4, 2))]))
        ev = core.evaluate(j, params, c.conditions)
        df = pd.DataFrame({k: v for k, v in ev.items() if not k.startswith("flag_")})
        df.insert(0, "curve_id", c.curve_id)
        df["role"] = c.meta.role
        df["extrapolated"] = j > hi + 1e-12
        if device is not None:
            st = core.stack_quantities(j, df["V_cell_V"].to_numpy(), device.n_cells, device.active_area_cm2)
            for k, v in st.items():
                if v is not None:
                    df[k] = v
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def parameter_table(result: FitResult) -> pd.DataFrame:
    from .optimizer import parameter_origins
    origins = parameter_origins(result.config)
    ident = result.identifiability["parameters"].set_index("parameter") if result.identifiability else None
    rows = []
    for name, s in result.config.settings.items():
        info = PARAMETER_INFO[name]
        row = {"Parámetro": name, "Símbolo": info.symbol, "Valor": getattr(result.params, name), "Unidad": info.unit,
               "Origen": origins[name], "Límite inf.": s.lower if s.free else None,
               "Límite sup.": s.upper if s.free else None, "Inicial": s.value if s.free else None,
               "Prior": f"N({s.prior_mean:g}, {s.prior_sigma:g})" if s.has_prior else "",
               "Error est.": None, "Identificabilidad": "NO_AJUSTADO", "Motivos": ""}
        if s.free and ident is not None and name in ident.index:
            r = ident.loc[name]
            row["Error est."] = r["std_error"]
            row["Identificabilidad"] = r["identifiability"]
            row["Motivos"] = "; ".join(r["reasons"])
        rows.append(row)
    return pd.DataFrame(rows)


def _fig_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def figure_polarization(result: FitResult, curves, device) -> bytes:
    dense = model_curves(result.params, curves, device)
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for k, c in enumerate(curves):
        col = PALETTE[k % len(PALETTE)]
        d = dense[dense.curve_id == c.curve_id]
        mk = "o" if c.meta.role == ROLE_CALIBRATION else "s"
        ax.plot(c.j_A_cm2, c.v_cell_V, mk, ms=4, color=col, mfc="none" if mk == "s" else col,
                label=f"{c.curve_id} medido ({c.meta.role})")
        ax.plot(d.j_A_cm2, d.V_cell_V, "-", color=col, lw=1.6,
                label=f"{c.curve_id} modelo ({c.conditions.temperature_K:.1f} K, {c.conditions.cathode_pressure_atm:.3g} atm)")
    ax.set_xlabel("Densidad de corriente j [A/cm²]")
    ax.set_ylabel("Tensión por celda [V]")
    ax.set_title(f"Curva de polarización — estado {result.status}")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7, loc="best")
    return _fig_bytes(fig)


def figure_residuals(result: FitResult, curves) -> bytes:
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    for k, c in enumerate(curves):
        r = result.residuals[result.residuals.curve_id == c.curve_id]
        ax.plot(r.j_A_cm2, 1000 * r.residual_V, "o-" if c.meta.role == ROLE_CALIBRATION else "s--",
                ms=3, lw=0.8, color=PALETTE[k % len(PALETTE)], label=c.curve_id)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xlabel("j [A/cm²]")
    ax.set_ylabel("Residuo V_mod − V_obs [mV/celda]")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7)
    return _fig_bytes(fig)


def figure_losses(result: FitResult, curves) -> bytes:
    dense = model_curves(result.params, curves)
    n = len(curves)
    fig, axes = plt.subplots(1, n, figsize=(4.0 * n, 3.6), squeeze=False)
    for ax, c in zip(axes[0], curves):
        d = dense[dense.curve_id == c.curve_id]
        ax.plot(d.j_A_cm2, d.V_act_V, label="V_act")
        ax.plot(d.j_A_cm2, d.V_ohm_V, label="V_ohm")
        ax.plot(d.j_A_cm2, d.V_conc_V, label="V_conc")
        ax.set_title(f"{c.curve_id}\nE = {d.E_nernst_V.iloc[0]:.4f} V", fontsize=8)
        ax.set_xlabel("j [A/cm²]")
        ax.grid(alpha=0.3)
    axes[0][0].set_ylabel("Pérdida [V/celda]")
    axes[0][0].legend(fontsize=7)
    return _fig_bytes(fig)


def figure_multistart(result: FitResult) -> bytes:
    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    runs = result.runs
    ok = np.isfinite(runs.rmse_V)
    ax.bar(runs.start_id[ok], 1000 * runs.rmse_V[ok],
           color=["#2e8b57" if s else "#c0392b" for s in runs.success[ok]])
    ax.set_xlabel("Inicio")
    ax.set_ylabel("RMSE de calibración [mV/celda]")
    ax.set_title("Multistart (verde: convergido, rojo: no convergido)", fontsize=9)
    ax.grid(alpha=0.3, axis="y")
    return _fig_bytes(fig)


def _fmt(x, nd=6):
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return "—"
    return f"{x:.{nd}g}" if isinstance(x, (float, int, np.floating)) else str(x)


def markdown_report(profile: dict, result: FitResult, curves, device: DeviceInfo) -> str:
    m = result.metrics_global
    L = [f"# Reporte de identificación — {device.name}", "",
         f"Perfil `{profile['profile_id']}` · creado {profile['created_utc']} · "
         f"{profile['engine']['app']} {profile['engine']['app_version']} · modelo "
         f"`{profile['engine']['model_id']}` v{profile['engine']['model_version']}", "",
         f"## Estado: **{result.status}**", "", STATUS_DESCRIPTIONS[result.status], ""]
    L += [f"- {r}" for r in result.status_reasons] + [""]
    L += ["Calidad de reproducción de los datos calibrados, validación independiente y capacidad predictiva "
          "son cosas distintas: este reporte solo demuestra la primera, salvo que la sección de validación "
          "indique lo contrario.", ""]
    L += ["## Dispositivo", "", "| Campo | Valor | Origen |", "|---|---|---|",
          f"| Nombre | {device.name} | |", f"| Fabricante / modelo | {device.manufacturer} / {device.model} | |",
          f"| N_cells | {_fmt(device.n_cells)} | {device.n_cells_origin if device.n_cells else ''} |",
          f"| A_active [cm²] | {_fmt(device.active_area_cm2)} | {device.active_area_origin if device.active_area_cm2 else ''} |",
          f"| Datasheet (complementario, no usado en el ajuste) | {device.datasheet_reference or '—'} | |", ""]
    L += ["## Curvas", "", "| Curva | Rol | Calidad | T [K] | P cátodo [atm abs] | n | j [A/cm²] | σ_V [V] | SHA-256 original |",
          "|---|---|---|---|---|---|---|---|---|"]
    for c in curves:
        L.append(f"| {c.curve_id} | {c.meta.role} | {c.meta.quality} | {c.conditions.temperature_K:.2f} | "
                 f"{c.conditions.cathode_pressure_atm:.4g} | {c.n_points} | {c.j_A_cm2.min():.3g}–{c.j_A_cm2.max():.3g} | "
                 f"{_fmt(c.meta.sigma_V)} | `{(c.source_sha256 or '—')[:12]}` |")
    L.append("")
    for c in curves:
        if c.transformations:
            L.append(f"Transformaciones `{c.curve_id}`: " + " · ".join(c.transformations))
    L += ["", "## Configuración del ajuste", "",
          f"Preset: {result.config.preset}. Algoritmo: TRF acotado, jac 3-point, {result.config.n_starts} inicios, "
          f"semilla {result.config.seed}, max_nfev {result.config.max_nfev}, tolerancias {result.config.tolerance:g}, "
          f"ponderación por {result.config.weighting}, inicio informado por datos: "
          f"{'sí' if result.config.data_informed_start else 'no'}. σ_V declarada: "
          f"{'sí' if result.sigma_declared else 'no (pesos unitarios)'}. Tiempo {result.elapsed_s:.2f} s. "
          f"Mejor inicio: {result.best_start}.", ""]
    L += [f"- {n}" for n in result.config.notes] + [""]
    L += ["## Parámetros", "", "| Parámetro | Símbolo | Valor | Unidad | Origen | Límites | Error est. | Identificabilidad |",
          "|---|---|---|---|---|---|---|---|"]
    for _, r in parameter_table(result).iterrows():
        lim = f"[{_fmt(r['Límite inf.'])}, {_fmt(r['Límite sup.'])}]" if pd.notna(r["Límite inf."]) else "—"
        L.append(f"| {r['Parámetro']} | {r['Símbolo']} | {_fmt(r['Valor'], 10)} | {r['Unidad']} | {r['Origen']} | "
                 f"{lim} | {_fmt(r['Error est.'], 3)} | {r['Identificabilidad']} |")
    L += ["", "## Métricas de calibración (tensión por celda)", "",
          f"RMSE {_fmt(1000 * m.get('rmse_V', np.nan), 5)} mV · MAE {_fmt(1000 * m.get('mae_V', np.nan), 5)} mV · "
          f"error máx. {_fmt(1000 * m.get('max_abs_V', np.nan), 5)} mV · sesgo {_fmt(1000 * m.get('bias_V', np.nan), 4)} mV · "
          f"n = {m.get('n')}" + (f" · χ²_red = {_fmt(m['chi2_reduced'], 4)}" if "chi2_reduced" in m else ""), ""]
    if device.n_cells:
        L += [f"Equivalente de stack (×{device.n_cells}): RMSE {_fmt(device.n_cells * m.get('rmse_V', np.nan), 5)} V.", ""]
    L += ["| Curva | Rol | n | RMSE [mV] | MAE [mV] | Máx. [mV] | Rachas z |", "|---|---|---|---|---|---|---|"]
    for _, r in result.metrics_by_curve.iterrows():
        L.append(f"| {r.curve_id} | {r.role} | {r.n} | {1000 * r.rmse_V:.4g} | {1000 * r.mae_V:.4g} | "
                 f"{1000 * r.max_abs_V:.4g} | {_fmt(r.runs_z, 3)} |")
    ident = result.identifiability
    if ident:
        L += ["", "## Identificabilidad local", "",
              f"Condición del Jacobiano escalado {ident['condition_number']:.4g}; rango {ident['rank']}/{ident['n_free']}; "
              f"grados de libertad {ident['dof']}; inicios equivalentes {ident['n_equivalent_starts']}/{len(result.runs)}. "
              f"Covarianza: {ident['covariance_basis']}.", "",
              "Dirección peor condicionada: " + ", ".join(f"{k} {v:+.2f}" for k, v in ident["weakest_direction"].items()), ""]
    v = result.validation
    L += ["## Validación independiente", "", f"Estado: **{v['status']}**."]
    if v["metrics"]:
        L.append(f"Curvas {', '.join(v['curves'])}: RMSE {1000 * v['metrics']['rmse_V']:.4g} mV (criterio "
                 f"{1000 * v['criterion_rmse_V']:.3g} mV).")
    L += [f"- {n}" for n in v["notes"]]
    L += ["", "## Advertencias", ""] + ([f"- {w}" for w in profile["warnings"]] or ["- Ninguna."])
    dom = profile["domain"]["calibration"]
    L += ["", "## Dominio y límites", "",
          f"Calibrado en j ∈ [{dom['j_A_cm2'][0]:.4g}, {dom['j_A_cm2'][1]:.4g}] A/cm², T ∈ "
          f"[{dom['temperature_K'][0]:.2f}, {dom['temperature_K'][1]:.2f}] K, P ∈ "
          f"[{dom['cathode_pressure_atm'][0]:.4g}, {dom['cathode_pressure_atm'][1]:.4g}] atm abs. "
          "Fuera de ese dominio el perfil extrapola.",
          "", "El modelo es semiempírico y estacionario: no representa transitorios, envejecimiento, gestión de agua "
          "ni condiciones no medidas. Los parámetros con identificabilidad DÉBIL o NO_IDENTIFICABLE son efectivos.",
          "", "## Reproducibilidad", "",
          "Para reproducir: cargar `profile.json` en PEMFC ModelLab (pestaña Exportar → Cargar perfil) o "
          "recalcular con `identification.profiles.load_profile`. Los datos normalizados están en el perfil y en "
          "`data/normalized/`; los archivos originales, en `data/original/` con su SHA-256.", ""]
    return "\n".join(L)


def experiment_zip(profile: dict, result: FitResult, curves: list[PolarizationCurve], device: DeviceInfo,
                   original_files: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    root = f"pemfc_modellab_{profile['profile_id']}/"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(root + "profile.json", profile_to_json(profile))
        z.writestr(root + "report.md", markdown_report(profile, result, curves, device))
        for name, data in (original_files or {}).items():
            z.writestr(root + f"data/original/{name}", data)
        for c in curves:
            z.writestr(root + f"data/normalized/{c.curve_id}.csv", c.normalized_frame(device).to_csv(index=False))
            z.writestr(root + f"data/raw_points/{c.curve_id}.csv", c.raw.to_csv(index=False))
        z.writestr(root + "results/fit_points.csv", result.residuals.to_csv(index=False))
        z.writestr(root + "results/model_curves.csv", model_curves(result.params, curves, device).to_csv(index=False))
        z.writestr(root + "results/parameters.csv", parameter_table(result).to_csv(index=False))
        z.writestr(root + "results/optimization_runs.csv", result.runs.to_csv(index=False))
        z.writestr(root + "results/metrics_by_curve.csv", result.metrics_by_curve.to_csv(index=False))
        if result.identifiability:
            z.writestr(root + "results/parameter_correlation.csv", result.identifiability["correlation"].to_csv())
            z.writestr(root + "results/identifiability.csv",
                       result.identifiability["parameters"].assign(
                           reasons=lambda d: d.reasons.map("; ".join)).to_csv(index=False))
        z.writestr(root + "figures/polarization.png", figure_polarization(result, curves, device))
        z.writestr(root + "figures/residuals.png", figure_residuals(result, curves))
        z.writestr(root + "figures/losses.png", figure_losses(result, curves))
        z.writestr(root + "figures/multistart.png", figure_multistart(result))
        z.writestr(root + "manifest.json", json.dumps({
            "profile_id": profile["profile_id"], "status": profile["status"]["code"],
            "files": sorted(n[len(root):] for n in z.namelist())}, indent=2, ensure_ascii=False))
    return buf.getvalue()
