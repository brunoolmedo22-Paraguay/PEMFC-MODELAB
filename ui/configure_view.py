"""Pestaña 2: Configurar identificación."""
from __future__ import annotations

import math
from dataclasses import replace

import pandas as pd
import streamlit as st

from identification.optimizer import (
    MAX_NFEV_LIMIT, MAX_STARTS, FitConfig, ParameterSetting, preset_generic, preset_otekon, structural_checks,
)
from pemfc_core.parameters import FITTABLE_PARAMETERS, ORIGIN_IDENTIFIED, ORIGINS, PARAMETER_INFO

from . import state

FIXED_ORIGINS = [o for o in ORIGINS if o != ORIGIN_IDENTIFIED]


def _apply_preset(kind: str) -> None:
    curves = st.session_state.curves
    st.session_state.fit_config = preset_otekon() if kind == "otekon" else preset_generic(curves)
    st.session_state.cfg_version = st.session_state.get("cfg_version", 0) + 1
    st.session_state.cfg_base_frame = _settings_frame(st.session_state.fit_config)
    st.session_state.cfg_base_preset = st.session_state.fit_config.preset
    _config_to_widgets(st.session_state.fit_config)


def _config_to_widgets(cfg: FitConfig) -> None:
    ss = st.session_state
    ss.cfg_starts, ss.cfg_seed, ss.cfg_nfev = cfg.n_starts, cfg.seed, cfg.max_nfev
    ss.cfg_weighting, ss.cfg_informed = cfg.weighting, cfg.data_informed_start
    ss.cfg_rmse_mV = 1000 * cfg.rmse_threshold_V
    ss.cfg_val_mV = 1000 * cfg.validation_rmse_threshold_V
    b = cfg.base_params
    ss.cfg_ph2, ss.cfg_ph2o, ss.cfg_yo2 = b.p_h2, b.p_h2o, b.oxygen_fraction_air


def _settings_frame(cfg: FitConfig) -> pd.DataFrame:
    rows = []
    for n in FITTABLE_PARAMETERS:
        s, info = cfg.settings[n], PARAMETER_INFO[n]
        req = {"temperaturas": "≥ 2 temperaturas", "presiones": "≥ 2 presiones de O2"}.get(info.requires, "")
        rows.append({"parámetro": n, "símbolo": info.symbol, "unidad": info.unit, "libre": s.free,
                     "valor": s.value, "límite_inf": s.lower, "límite_sup": s.upper, "escala": s.scale,
                     "prior_media": s.prior_mean, "prior_sigma": s.prior_sigma,
                     "origen_si_fijado": s.fixed_origin if s.fixed_origin in FIXED_ORIGINS else "ASUMIDO",
                     "requisito": req, "justificación": s.rationale})
    return pd.DataFrame(rows)


def _frame_to_settings(df: pd.DataFrame, previous: FitConfig) -> dict[str, ParameterSetting]:
    out = {}
    for _, r in df.iterrows():
        def num(v, default=math.nan):
            return default if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)
        pm, ps = r["prior_media"], r["prior_sigma"]
        pm = None if pm is None or pd.isna(pm) else float(pm)
        ps = None if ps is None or pd.isna(ps) else float(ps)
        out[r["parámetro"]] = ParameterSetting(
            name=r["parámetro"], free=bool(r["libre"]), value=num(r["valor"]), lower=num(r["límite_inf"]),
            upper=num(r["límite_sup"]), scale=num(r["escala"]), prior_mean=pm, prior_sigma=ps,
            fixed_origin=r["origen_si_fijado"] or "ASUMIDO",
            rationale=previous.settings[r["parámetro"]].rationale)
    return out


def render() -> None:
    curves = st.session_state.curves
    if not curves:
        st.info("Primero importe al menos una curva V–I en «Importar curva». La identificación no puede "
                "realizarse solo con datos de datasheet.")
        return
    if st.session_state.fit_config is None or "cfg_base_frame" not in st.session_state:
        _apply_preset("generic")
    cfg: FitConfig = st.session_state.fit_config

    st.subheader("Preset")
    c1, c2 = st.columns(2)
    c1.button("Aplicar preset recomendado para estos datos", on_click=_apply_preset, args=("generic",),
              width="stretch")
    c2.button("Preset OTEKON (9 parámetros, reproducción del artículo)", on_click=_apply_preset, args=("otekon",),
              width="stretch")
    st.caption(f"Preset activo: **{cfg.preset}**")
    for n in cfg.notes:
        st.caption(f"• {n}")

    st.subheader("Parámetros del modelo")
    st.caption("Marque *libre* para identificar el parámetro. Los fijados conservan su valor y el origen que "
               "indique (MEDIDO, DATASHEET, FIJADO o ASUMIDO). Un prior N(media, σ) solo se admite si todas las "
               "curvas de calibración declaran σ_V. ξ2, n_R y a_T requieren ≥ 2 temperaturas; ξ4, ≥ 2 presiones de O2.")
    version = st.session_state.get("cfg_version", 0)
    edited = st.data_editor(
        st.session_state.cfg_base_frame, key=f"param_editor_{version}", hide_index=True, width="stretch",
        num_rows="fixed",
        disabled=["parámetro", "símbolo", "unidad", "requisito", "justificación"],
        column_config={
            "libre": st.column_config.CheckboxColumn(),
            "valor": st.column_config.NumberColumn("valor inicial / fijado", format="%.6g"),
            "límite_inf": st.column_config.NumberColumn(format="%.6g"),
            "límite_sup": st.column_config.NumberColumn(format="%.6g"),
            "escala": st.column_config.NumberColumn(format="%.4g"),
            "prior_media": st.column_config.NumberColumn(format="%.6g"),
            "prior_sigma": st.column_config.NumberColumn(format="%.4g"),
            "origen_si_fijado": st.column_config.SelectboxColumn(options=FIXED_ORIGINS, required=True),
        })

    with st.expander("Parámetros no ajustables y gases (valores globales)"):
        st.caption("E0, R, F, T_ref y el piso numérico j_floor son fijos. t_m y D_H no afectan a la curva V–I en "
                   "esta parametrización. p_H2 y y_O2 pueden declararse por curva en sus condiciones.")
        c1, c2, c3 = st.columns(3)
        c1.number_input("p_H2 global [atm abs]", min_value=1e-6, format="%.6g", key="cfg_ph2")
        c2.number_input("p_H2O [atm] (hipótesis OTEKON)", min_value=1e-6, format="%.6g", key="cfg_ph2o")
        c3.number_input("Fracción de O2 global", min_value=1e-6, max_value=1.0, format="%.4g", key="cfg_yo2")

    st.subheader("Algoritmo y criterios")
    c1, c2, c3, c4 = st.columns(4)
    c1.number_input("Inicios (multistart)", 1, MAX_STARTS, step=1, key="cfg_starts",
                    help="Más inicios exploran mejor, a costa de tiempo. Límite pensado para Streamlit Cloud.")
    c2.number_input("Semilla", 0, 2**31 - 1, step=1, key="cfg_seed")
    c3.number_input("Evaluaciones máx. por inicio", 50, MAX_NFEV_LIMIT, step=50, key="cfg_nfev")
    c4.selectbox("Ponderación", ["puntos", "curvas"], key="cfg_weighting",
                 help="‘curvas’: cada curva pesa lo mismo aunque tenga distinto número de puntos.")
    c1, c2, c3 = st.columns(3)
    c1.checkbox("Añadir inicio informado por los datos", key="cfg_informed",
                help="Proyección lineal sobre los parámetros que entran linealmente. Desactivado en el preset OTEKON.")
    c2.number_input("Criterio de ajuste: RMSE máx. [mV/celda]", min_value=0.01, format="%.3g", key="cfg_rmse_mV",
                    help="Decisión del usuario/proyecto. Si el RMSE lo supera, el estado será AJUSTE_INSUFICIENTE.")
    c3.number_input("Criterio de validación: RMSE máx. [mV/celda]", min_value=0.01, format="%.3g", key="cfg_val_mV")

    ss = st.session_state
    try:
        new_cfg = FitConfig(
            settings=_frame_to_settings(edited, cfg),
            base_params=replace(cfg.base_params, p_h2=float(ss.cfg_ph2), p_h2o=float(ss.cfg_ph2o),
                                oxygen_fraction_air=float(ss.cfg_yo2)),
            n_starts=int(ss.cfg_starts), seed=int(ss.cfg_seed), max_nfev=int(ss.cfg_nfev), tolerance=cfg.tolerance,
            weighting=ss.cfg_weighting, data_informed_start=bool(ss.cfg_informed),
            rmse_threshold_V=float(ss.cfg_rmse_mV) / 1000, validation_rmse_threshold_V=float(ss.cfg_val_mV) / 1000,
            preset=(st.session_state.cfg_base_preset if edited.equals(st.session_state.cfg_base_frame)
                    else f"{st.session_state.cfg_base_preset} (modificado)"),
            notes=cfg.notes)
    except (TypeError, ValueError) as exc:
        st.error(f"Configuración inválida: {exc}")
        return
    st.session_state.fit_config = new_cfg

    st.subheader("Comprobación previa")
    issues = structural_checks(curves, new_cfg)
    cal = [c for c in curves if c.meta.role == "calibración"]
    st.markdown(f"{len(new_cfg.free_names())} parámetros libres · {sum(c.n_points for c in cal)} puntos de "
                f"calibración en {len(cal)} curva(s) · {len(curves) - len(cal)} curva(s) de validación.")
    if not state.show_issues(issues):
        st.success("Configuración coherente. Continúe en «Calibrar».")
