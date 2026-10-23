"""Pestaña 4: Resultados."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from identification.reporting import parameter_table

from . import plots, state
from .fit_view import status_banner


def render() -> None:
    result = st.session_state.fit_result
    curves = st.session_state.curves
    device = st.session_state.device
    if result is None:
        st.info("Todavía no hay resultados. Ejecute la identificación en «Calibrar».")
        return
    if not state.result_is_current():
        st.warning("Resultado desactualizado respecto a los datos/configuración actuales.")
    curves = [c for c in curves if c.curve_id in result.curve_ids]
    status_banner(result)
    st.caption("Un buen ajuste a las curvas de calibración no es una validación experimental independiente ni "
               "demuestra capacidad predictiva en otras condiciones.")

    if result.x_best is None:
        st.error("No hay solución que mostrar.")
        return
    m = result.metrics_global
    cols = st.columns(5)
    cols[0].metric("RMSE [mV/celda]", f"{1000 * m['rmse_V']:.3f}")
    cols[1].metric("MAE [mV/celda]", f"{1000 * m['mae_V']:.3f}")
    cols[2].metric("Error máx. [mV/celda]", f"{1000 * m['max_abs_V']:.3f}")
    cols[3].metric("Puntos", m["n"])
    if device.n_cells:
        cols[4].metric("RMSE stack [V]", f"{device.n_cells * m['rmse_V']:.4f}")
    elif "chi2_reduced" in m:
        cols[4].metric("χ² reducido", f"{m['chi2_reduced']:.3g}")

    c1, c2 = st.columns(2)
    stack = c1.toggle("Unidades de stack", key="res_stack", disabled=not (device.n_cells and device.active_area_cm2))
    extend = c2.number_input("Extender modelo hasta j [A/cm²] (zona marcada como extrapolación)",
                             value=None, min_value=0.0, format="%.3g", key="res_extend")
    st.plotly_chart(plots.polarization(result, curves, device, stack, extend), width="stretch")
    st.plotly_chart(plots.residuals(result, curves), width="stretch")
    sel = st.selectbox("Contribuciones de pérdida de la curva", [c.curve_id for c in curves], key="res_loss_curve")
    st.plotly_chart(plots.losses(result, next(c for c in curves if c.curve_id == sel)), width="stretch")

    st.subheader("Métricas por curva")
    mc = result.metrics_by_curve.copy()
    for k in ("rmse_V", "mae_V", "max_abs_V", "bias_V"):
        mc[k.replace("_V", " [mV]")] = 1000 * mc.pop(k)
    st.dataframe(mc.rename(columns={"runs_z": "rachas z", "systematic_residual": "residuo sistemático",
                                    "mape_percent": "error rel. medio [%]"}), hide_index=True, width="stretch")

    st.subheader("Parámetros")
    st.dataframe(parameter_table(result), hide_index=True, width="stretch",
                 column_config={"Valor": st.column_config.NumberColumn(format="%.8g"),
                                "Error est.": st.column_config.NumberColumn(format="%.3g")})

    ident = result.identifiability
    if ident:
        st.subheader("Identificabilidad local")
        c1, c2, c3 = st.columns(3)
        c1.metric("Condición del Jacobiano escalado", f"{ident['condition_number']:.3g}")
        c2.metric("Rango numérico", f"{ident['rank']}/{ident['n_free']}")
        c3.metric("Grados de libertad", ident["dof"])
        st.caption(f"Covarianza basada en: {ident['covariance_basis']}. Inicios con coste equivalente al mejor: "
                   f"{ident['n_equivalent_starts']}/{len(result.runs)}. Dirección peor condicionada: "
                   + ", ".join(f"{k} ({v:+.2f})" for k, v in ident["weakest_direction"].items()))
        if len(ident["correlation"]) > 1:
            st.plotly_chart(plots.correlation(ident["correlation"]), width="stretch")
        st.dataframe(pd.DataFrame({"valor singular (escalado)": ident["singular_values"]}).T,
                     width="stretch")

    v = result.validation
    st.subheader("Validación independiente")
    st.markdown(f"Estado: **{v['status']}**")
    if v["metrics"]:
        st.markdown(f"Curvas {', '.join(v['curves'])}: RMSE {1000 * v['metrics']['rmse_V']:.3f} mV/celda "
                    f"(criterio {1000 * v['criterion_rmse_V']:.3g} mV/celda).")
    for n in v["notes"]:
        st.caption(f"• {n}")
    if v["status"] == "SIN_VALIDACION_INDEPENDIENTE":
        st.caption("Para validar, importe curvas medidas no usadas en el ajuste con rol «validación».")

    if result.warnings:
        st.subheader("Advertencias")
        st.warning("\n".join(f"- {w}" for w in result.warnings))
