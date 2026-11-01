"""Pestaña 5: Exportar perfil y reimportar perfiles existentes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from identification.profiles import ProfileError, build_profile, evaluate_profile, load_profile, profile_to_json
from identification.reporting import PALETTE, experiment_zip
from pemfc_core import model as core

from . import state

_EXPORT_HOOK: dict = {"fn": None}


def set_export_hook(fn) -> None:
    """Registro opcional de exportaciones (v0.3.0: historial del dispositivo). No altera el contenido exportado."""
    _EXPORT_HOOK["fn"] = fn


def _fire(kind: str, filename: str, data: bytes) -> None:
    if _EXPORT_HOOK["fn"] is not None:
        _EXPORT_HOOK["fn"](kind, filename, data)


def _export_section() -> None:
    result = st.session_state.fit_result
    if result is None:
        st.info("Ejecute una identificación para poder exportar un perfil. No existe exportación sin curva V–I calibrada.")
        return
    if not state.result_is_current():
        st.error("El resultado está desactualizado respecto a los datos o la configuración actuales. "
                 "Vuelva a ejecutar la identificación antes de exportar.")
        return
    curves = [c for c in st.session_state.curves if c.curve_id in result.curve_ids]
    device = st.session_state.device
    if st.session_state.profile_key != st.session_state.fit_key:
        try:
            st.session_state.profile = build_profile(result, curves, device)
            st.session_state.profile_key = st.session_state.fit_key
        except ProfileError as exc:
            st.error(f"No se pudo construir el perfil: {exc}")
            return
    prof = st.session_state.profile
    usable = prof["status"]["usable_for_simulation"]
    (st.success if usable else st.error)(
        f"Perfil `{prof['profile_id']}` — estado **{prof['status']['code']}**. "
        f"{'Utilizable' if usable else 'NO utilizable'} para simulación. Capacidad predictiva: "
        f"{prof['status']['predictive_capability']}.")
    c1, c2 = st.columns(2)
    prof_bytes = profile_to_json(prof).encode("utf-8")
    c1.download_button("Descargar profile.json", prof_bytes,
                       file_name=f"{prof['profile_id']}_profile.json", mime="application/json",
                       width="stretch", key="dl_profile", on_click=_fire,
                       args=("profile.json", f"{prof['profile_id']}_profile.json", prof_bytes))
    if st.session_state.get("zip_key") != st.session_state.fit_key:
        st.session_state.zip_bytes = None
    if c2.button("Preparar ZIP del experimento", width="stretch", key="prep_zip"):
        with st.spinner("Generando figuras, reporte y tablas…"):
            st.session_state.zip_bytes = experiment_zip(prof, result, curves, device, st.session_state.originals)
            st.session_state.zip_key = st.session_state.fit_key
    if st.session_state.get("zip_bytes"):
        c2.download_button("Descargar ZIP del experimento", st.session_state.zip_bytes,
                           file_name=f"pemfc_modellab_{prof['profile_id']}.zip", mime="application/zip",
                           width="stretch", key="dl_zip", on_click=_fire,
                           args=("zip", f"pemfc_modellab_{prof['profile_id']}.zip", st.session_state.zip_bytes))
    st.caption("El ZIP contiene profile.json, report.md, datos originales y normalizados, resultados CSV y figuras PNG; "
               "todo legible sin ejecutar la aplicación. Nada se guarda en el servidor.")
    with st.expander("Ver profile.json"):
        st.json(prof, expanded=False)


def _reload_section() -> None:
    st.subheader("Cargar un perfil existente")
    up = st.file_uploader("profile.json", type=["json"], key="profile_upload")
    text = st.text_area("…o pegue el JSON del perfil", key="profile_text", height=100)
    source = up.getvalue() if up is not None else (text.encode() if text.strip() else None)
    if source is None:
        return
    try:
        loaded = load_profile(source)
    except ProfileError as exc:
        msg = "\n".join(f"- {e}" for e in exc.report.errors) if exc.report else str(exc)
        st.error(f"Perfil rechazado:\n\n{msg}")
        return
    prof = loaded.profile
    (st.success if loaded.reproduction_ok else st.error)(
        f"Perfil `{prof['profile_id']}` ({prof['device'].get('name')}) — estado **{loaded.status}**. "
        f"Reproducción de la curva guardada: error máx. {loaded.max_reproduction_error_V:.2e} V "
        f"({'OK' if loaded.reproduction_ok else 'FALLA'}; tolerancia {prof['reproduction_check']['tolerance_V']:.0e} V). "
        f"Motor {'igual' if loaded.engine_match else 'distinto'} (modelo v{prof['engine']['model_version']}).")
    for m in loaded.messages:
        st.warning(m)
    fig = go.Figure()
    for i, d in enumerate(loaded.curves):
        col = PALETTE[i % len(PALETTE)]
        cond = core.OperatingConditions(**d["conditions"])
        j = np.asarray(d["points"]["j_A_cm2"])
        jj = np.linspace(j.min(), j.max(), 200)
        fig.add_trace(go.Scatter(x=j, y=d["points"]["V_cell_V"], mode="markers", marker=dict(color=col),
                                 name=f"{d['curve_id']} — datos del perfil"))
        fig.add_trace(go.Scatter(x=jj, y=core.cell_voltage(jj, loaded.params, cond), mode="lines",
                                 line=dict(color=col), name=f"{d['curve_id']} — recalculado"))
    fig.update_layout(title="Curva recalculada con este motor", xaxis_title="j [A/cm²]",
                      yaxis_title="Tensión por celda [V]", margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig, width="stretch")
    st.dataframe(pd.DataFrame([{k: p.get(k) for k in ("name", "symbol", "value", "unit", "origin", "identifiability")}
                               for p in prof["parameters"]]), hide_index=True, width="stretch")

    with st.expander("Evaluar el perfil en un punto de operación"):
        dom = prof["domain"]["calibration"]
        c1, c2, c3 = st.columns(3)
        j = c1.number_input("j [A/cm²]", min_value=0.0, value=float(np.mean(dom["j_A_cm2"])), format="%.4g", key="ev_j")
        T = c2.number_input("T [K]", min_value=1.0, value=float(dom["temperature_K"][0]), format="%.5g", key="ev_T")
        P = c3.number_input("P cátodo [atm abs]", min_value=1e-3, value=float(dom["cathode_pressure_atm"][0]),
                            format="%.5g", key="ev_P")
        out = evaluate_profile(loaded, [j], core.OperatingConditions(T, P))
        v = float(out["V_cell_V"][0])
        text = f"V_cell = {v:.5f} V"
        if loaded.device.n_cells:
            text += f" · V_stack = {v * loaded.device.n_cells:.4f} V"
        if loaded.device.active_area_cm2:
            text += f" · I = {j * loaded.device.active_area_cm2:.4g} A"
        st.markdown(text)
        if bool(out["extrapolated"][0]):
            st.warning("Punto fuera del dominio de calibración: EXTRAPOLACIÓN no respaldada por los datos.")
        st.caption("Evaluación estacionaria del Motor 1. La simulación operacional (Motor 2) no está implementada.")


def render() -> None:
    st.subheader("Exportar perfil")
    _export_section()
    st.divider()
    _reload_section()
