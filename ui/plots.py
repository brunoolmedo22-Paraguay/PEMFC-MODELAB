"""Figuras interactivas. Todas las curvas del modelo vienen de pemfc_core vía reporting.model_curves."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from identification.reporting import PALETTE, model_curves
from pemfc_core.schemas import ROLE_CALIBRATION

LAYOUT = dict(margin=dict(l=10, r=10, t=40, b=10), legend=dict(font=dict(size=11)), hovermode="closest")


def _scale(stack: bool, device) -> tuple[float, str]:
    if stack and device is not None and device.n_cells:
        return float(device.n_cells), f"Tensión de stack [V] (N = {device.n_cells})"
    return 1.0, "Tensión por celda [V]"


def _x(stack_current: bool, device, j):
    if stack_current and device is not None and device.active_area_cm2:
        return np.asarray(j) * device.active_area_cm2, f"Corriente [A] (A = {device.active_area_cm2:g} cm²)"
    return np.asarray(j), "Densidad de corriente j [A/cm²]"


def data_preview(curves, device, stack: bool = False) -> go.Figure:
    k, ylab = _scale(stack, device)
    fig = go.Figure()
    for i, c in enumerate(curves):
        x, xlab = _x(stack, device, c.j_A_cm2)
        fig.add_trace(go.Scatter(x=x, y=k * c.v_cell_V, mode="markers+lines", name=f"{c.curve_id} ({c.meta.role})",
                                 line=dict(width=1, color=PALETTE[i % len(PALETTE)]), marker=dict(size=6)))
    fig.update_layout(title="Puntos normalizados (antes de calibrar)", xaxis_title=xlab if curves else "",
                      yaxis_title=ylab, **LAYOUT)
    return fig


def polarization(result, curves, device, stack: bool = False, extend_to: float | None = None) -> go.Figure:
    k, ylab = _scale(stack, device)
    dense = model_curves(result.params, curves, device, extend_to=extend_to)
    fig = go.Figure()
    for i, c in enumerate(curves):
        col = PALETTE[i % len(PALETTE)]
        x, xlab = _x(stack, device, c.j_A_cm2)
        cal = c.meta.role == ROLE_CALIBRATION
        fig.add_trace(go.Scatter(x=x, y=k * c.v_cell_V, mode="markers", name=f"{c.curve_id} — medido",
                                 marker=dict(size=7, color=col, symbol="circle" if cal else "square-open"),
                                 legendgroup=c.curve_id))
        d = dense[dense.curve_id == c.curve_id]
        segments = [(d[~d.extrapolated], "solid", "modelo")]
        if d.extrapolated.any():
            segments.append((d[d.j_A_cm2 >= c.j_A_cm2.max()], "dot", "EXTRAPOLACIÓN"))
        for dd, dash, suffix in segments:
            xx, _ = _x(stack, device, dd.j_A_cm2)
            fig.add_trace(go.Scatter(x=xx, y=k * dd.V_cell_V, mode="lines", line=dict(color=col, dash=dash, width=2),
                                     name=f"{c.curve_id} — {suffix} ({c.conditions.temperature_K:.1f} K, "
                                          f"{c.conditions.cathode_pressure_atm:.3g} atm)", legendgroup=c.curve_id))
    fig.update_layout(title="Curva de polarización: medido vs. modelo", xaxis_title=xlab, yaxis_title=ylab, **LAYOUT)
    return fig


def residuals(result, curves) -> go.Figure:
    fig = go.Figure()
    for i, c in enumerate(curves):
        r = result.residuals[result.residuals.curve_id == c.curve_id]
        fig.add_trace(go.Scatter(x=r.j_A_cm2, y=1000 * r.residual_V, mode="markers+lines",
                                 name=f"{c.curve_id} ({c.meta.role})",
                                 line=dict(width=1, color=PALETTE[i % len(PALETTE)],
                                           dash="solid" if c.meta.role == ROLE_CALIBRATION else "dash")))
    fig.add_hline(y=0, line_width=1)
    fig.update_layout(title="Residuos V_modelo − V_medido", xaxis_title="j [A/cm²]",
                      yaxis_title="Residuo [mV/celda]", **LAYOUT)
    return fig


def losses(result, curve) -> go.Figure:
    d = model_curves(result.params, [curve])
    fig = go.Figure()
    for col, name in (("V_act_V", "Activación"), ("V_ohm_V", "Óhmica"), ("V_conc_V", "Concentración")):
        fig.add_trace(go.Scatter(x=d.j_A_cm2, y=d[col], mode="lines", name=name))
    fig.update_layout(title=f"Contribuciones de pérdida — {curve.curve_id} (E = {d.E_nernst_V.iloc[0]:.4f} V)",
                      xaxis_title="j [A/cm²]", yaxis_title="Pérdida [V/celda]", **LAYOUT)
    return fig


def correlation(corr_df) -> go.Figure:
    fig = go.Figure(go.Heatmap(z=corr_df.to_numpy(), x=list(corr_df.columns), y=list(corr_df.index),
                               zmin=-1, zmax=1, colorscale="RdBu", reversescale=True,
                               text=np.round(corr_df.to_numpy(), 2), texttemplate="%{text}"))
    fig.update_layout(title="Correlación local entre parámetros libres", **LAYOUT)
    return fig
