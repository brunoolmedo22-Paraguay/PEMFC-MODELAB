"""Pestaña 3: Calibrar. El ajuste solo se ejecuta al pulsar el botón."""
from __future__ import annotations

import streamlit as st

from identification.optimizer import FitConfigError, run_identification, structural_checks
from pemfc_core.schemas import STATUS_FITTED, STATUS_INSUFFICIENT, STATUS_NOT_CONVERGED, STATUS_VALIDATED

from . import state

STATUS_STYLE = {
    STATUS_VALIDATED: st.success, STATUS_FITTED: st.success,
    STATUS_INSUFFICIENT: st.warning, STATUS_NOT_CONVERGED: st.error,
}


def status_banner(result) -> None:
    STATUS_STYLE[result.status](f"**Estado: {result.status}**\n\n" + "\n".join(f"- {r}" for r in result.status_reasons))


def render() -> None:
    curves = st.session_state.curves
    cfg = st.session_state.fit_config
    if not curves or cfg is None:
        st.info("Importe curvas y revise la configuración antes de calibrar.")
        return
    issues = structural_checks(curves, cfg)
    blocked = any(i.level == "error" for i in issues)
    cal = [c for c in curves if c.meta.role == "calibración"]
    st.markdown(
        f"**{len(cfg.free_names())} parámetros libres** ({', '.join(cfg.free_names()) or '—'}) · "
        f"{sum(c.n_points for c in cal)} puntos de calibración · {cfg.n_starts} inicios · semilla {cfg.seed} · "
        f"criterio RMSE {1000 * cfg.rmse_threshold_V:g} mV/celda")
    if blocked:
        state.show_issues(issues)
        st.button("Ejecutar identificación", disabled=True, key="run_fit_disabled")
        return

    if st.button("Ejecutar identificación", type="primary", key="run_fit"):
        bar = st.progress(0.0, text="Iniciando optimización…")

        def progress(k, n):
            bar.progress(k / n, text=f"Inicio {k} de {n} completado")

        try:
            result = run_identification(curves, cfg, progress)
        except FitConfigError as exc:
            state.show_issues(exc.issues)
            return
        except Exception as exc:  # error inesperado: se informa, no se oculta
            st.error(f"La identificación falló: {type(exc).__name__}: {exc}")
            return
        bar.empty()
        st.session_state.fit_result = result
        st.session_state.fit_key = state.fit_key(cfg)
        st.session_state.profile = None

    result = st.session_state.fit_result
    if result is None:
        st.info("Pulse «Ejecutar identificación». El resultado se conserva al cambiar de pestaña.")
        return
    if not state.result_is_current():
        st.warning("Los datos o la configuración cambiaron después de este ajuste. El resultado mostrado está "
                   "desactualizado: vuelva a ejecutar la identificación antes de exportar.")
    status_banner(result)
    m = result.metrics_global
    if m.get("n"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("RMSE calibración [mV/celda]", f"{1000 * m['rmse_V']:.3f}")
        c2.metric("Error máximo [mV/celda]", f"{1000 * m['max_abs_V']:.3f}")
        c3.metric("Tiempo [s]", f"{result.elapsed_s:.2f}")
        c4.metric("Inicios convergidos", f"{int(result.runs.success.sum())}/{len(result.runs)}")
    st.caption(f"Mensaje del optimizador (mejor inicio {result.best_start}): {result.optimizer_message}")
    with st.expander("Inspeccionar todos los inicios"):
        runs = result.runs.copy()
        runs["rmse_mV"] = 1000 * runs["rmse_V"]
        st.dataframe(runs.drop(columns=["rmse_V"]), hide_index=True, width="stretch")
    st.info("Continúe en «Resultados» para gráficos, parámetros y diagnóstico de identificabilidad.")
