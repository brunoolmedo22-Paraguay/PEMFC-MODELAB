"""Historial del dispositivo: calibraciones (solo lectura), perfil activo, comparación y trazabilidad."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from identification.profiles import load_profile, profile_to_json
from identification.reporting import PALETTE
from pemfc_core import model as core
from workspace.model import Calibration, WorkspaceError

from . import persistence, shell

ORIGIN_TEXT = {"ejecutada": "ejecutada en ModelLab", "migrada_v020": "migrada de un perfil v0.1/v0.2",
               "importada": "importada de un proyecto"}


def fmt_dt(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def _rmse_mv(c: Calibration) -> str:
    return "—" if c.rmse_V is None else f"{1000 * c.rmse_V:.3f}"


def calibration_table(cals: list[Calibration], active_id: str | None) -> pd.DataFrame:
    rows = []
    for c in cals:
        dom = c.profile.get("domain", {}).get("calibration", {}) or {}
        j = dom.get("j_A_cm2") or [None, None]
        rows.append({"": "★ activo" if c.id == active_id else "", "calibración": c.label, "fecha": fmt_dt(c.created_utc),
                     "estado": c.status_code, "validación": c.validation_status, "RMSE [mV/celda]": _rmse_mv(c),
                     "curvas": ", ".join(c.curve_ids), "libres": len(c.free_parameters),
                     "j [A/cm²]": f"{j[0]:.3g}–{j[1]:.3g}" if j[0] is not None else "—",
                     "origen": ORIGIN_TEXT.get(c.origin, c.origin), "perfil": c.profile_id, "id": c.id})
    return pd.DataFrame(rows)


def _record_export(cal: Calibration):
    def fn(kind, filename, data):
        persistence.workspace().record_export(cal.id, filename, data, kind)
    return fn


def render_calibration(cal: Calibration, key: str, allow_actions: bool = True) -> None:
    """Vista de SOLO LECTURA de una calibración registrada (a partir de su perfil inmutable)."""
    prof = cal.profile
    ws = persistence.workspace()
    dev = ws.devices[cal.device_id]
    usable = cal.usable
    (st.success if usable else st.warning)(
        f"**{cal.label}** · {fmt_dt(cal.created_utc)} · perfil `{cal.profile_id}` — estado **{cal.status_code}** · "
        f"validación **{cal.validation_status}** · {ORIGIN_TEXT.get(cal.origin, cal.origin)}.")
    reasons = prof.get("status", {}).get("reasons", [])
    if reasons:
        st.caption(" · ".join(reasons))
    st.caption("Consulta de una calibración registrada: no se puede modificar. Para cambiar datos o configuración, cree "
               "una identificación nueva a partir de ella.")
    m = prof.get("fit", {}).get("metrics_calibration") or {}
    cols = st.columns(4)
    cols[0].metric("RMSE [mV/celda]", _rmse_mv(cal))
    cols[1].metric("MAE [mV/celda]", "—" if m.get("mae_V") is None else f"{1000 * m['mae_V']:.3f}")
    cols[2].metric("Puntos de calibración", m.get("n", "—"))
    cols[3].metric("Parámetros libres", len(cal.free_parameters))
    try:
        loaded = load_profile(prof)
        params = loaded.params
        repro = f"reproducción {'OK' if loaded.reproduction_ok else 'FALLA'} ({loaded.max_reproduction_error_V:.1e} V)"
    except Exception as exc:  # noqa: BLE001
        loaded, params, repro = None, None, f"no reproducible: {exc}"
    fig = go.Figure()
    for i, d in enumerate(prof.get("datasets", [])):
        col = PALETTE[i % len(PALETTE)]
        j = np.asarray(d["points"]["j_A_cm2"])
        fig.add_trace(go.Scatter(x=j, y=d["points"]["V_cell_V"], mode="markers", marker=dict(color=col, size=6),
                                 name=f"{d['curve_id']} ({d.get('role', '')}) observado"))
        if params is not None:
            jj = np.linspace(j.min(), j.max(), 200)
            fig.add_trace(go.Scatter(x=jj, y=core.cell_voltage(jj, params, core.OperatingConditions(**d["conditions"])),
                                     mode="lines", line=dict(color=col), name=f"{d['curve_id']} modelo"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=36, b=10), title=f"Observado frente a modelo · {repro}",
                      xaxis_title="j [A/cm²]", yaxis_title="Tensión por celda [V]")
    st.plotly_chart(fig, width="stretch", key=f"{key}_plot")
    st.dataframe(pd.DataFrame([{k: p.get(k) for k in ("name", "symbol", "value", "unit", "origin", "identifiability")}
                               for p in prof.get("parameters", [])]), hide_index=True, width="stretch")
    if not allow_actions:
        return
    c1, c2, c3 = st.columns(3)
    data = profile_to_json(prof).encode("utf-8")
    c1.download_button("Descargar profile.json", data, file_name=f"{cal.profile_id}_profile.json",
                       mime="application/json", key=f"{key}_dl", width="stretch", on_click=_record_export(cal),
                       args=("profile.json", f"{cal.profile_id}_profile.json", data))
    if dev.active_calibration_id == cal.id:
        c2.button("★ Perfil activo (quitar selección)", key=f"{key}_unact", width="stretch",
                  on_click=lambda: ws.set_active_calibration(dev.id, None),
                  help="Selección administrativa del perfil de referencia para futuras simulaciones.")
    else:
        c2.button("Establecer como perfil activo", key=f"{key}_act", width="stretch", disabled=not usable,
                  on_click=lambda: ws.set_active_calibration(dev.id, cal.id),
                  help=("Selección administrativa: NO convierte el perfil en validado." if usable
                        else f"Estado {cal.status_code}: no utilizable para simulación."))
    if c3.button("Nueva identificación a partir de esta", key=f"{key}_fork", width="stretch",
                 help="Crea un borrador nuevo con las mismas curvas y configuración. La calibración original no cambia."):
        fork_from_calibration(cal)
        st.rerun()


def fork_from_calibration(cal: Calibration) -> None:
    from workspace.serialization import curve_from_profile_dataset, curve_to_dict
    ws = persistence.workspace()
    src_draft = ws.drafts.get(cal.draft_id) if cal.draft_id else None
    dr = ws.new_draft(cal.device_id, f"Revisión de {cal.label}")
    curves = src_draft.curves if src_draft and src_draft.data_key == cal.data_key else \
        [curve_to_dict(curve_from_profile_dataset(d)) for d in cal.profile.get("datasets", [])]
    ws.update_draft(dr.id, curves=curves, fit_config=cal.profile.get("fit", {}).get("config"), stage=3,
                    dataset_label=f"Datos de {cal.label}")
    if src_draft:
        ws.set_draft_originals(dr.id, ws.originals_bytes(src_draft.originals))
    shell.go("device", device=cal.device_id, draft=dr.id, step=3, panel="flujo")


def render(device_id: str) -> None:
    ws = persistence.workspace()
    dev = ws.devices[device_id]
    cals = ws.device_calibrations(device_id)
    drafts = ws.device_drafts(device_id)
    sets = ws.device_datasets(device_id)
    exports = ws.device_exports(device_id)
    c = st.columns(4)
    c[0].metric("Calibraciones", len(cals))
    c[1].metric("Identificaciones (borradores)", len(drafts))
    c[2].metric("Curvas en borradores", sum(len(d.curves) for d in drafts))
    c[3].metric("Perfiles exportados", len(exports))
    active = ws.calibrations.get(dev.active_calibration_id) if dev.active_calibration_id else None
    if active:
        st.info(f"★ Perfil activo: **{active.label}** (`{active.profile_id}`, {active.status_code}). Selección "
                "administrativa; no implica validación científica.")

    st.markdown('<div class="pml-section-title">Calibraciones</div>', unsafe_allow_html=True)
    if not cals:
        st.caption("Todavía no hay calibraciones. Cada ejecución del optimizador queda registrada aquí sin sobrescribir "
                   "las anteriores.")
    else:
        df = calibration_table(cals, dev.active_calibration_id)
        st.dataframe(df.drop(columns=["id"]), hide_index=True, width="stretch")
        labels = {c.id: f"{c.label} · {fmt_dt(c.created_utc)} · {c.status_code}" for c in cals}
        sel = st.selectbox("Consultar calibración", list(labels), format_func=labels.get, key=f"hist_sel_{device_id}")
        with st.container(border=True):
            render_calibration(ws.calibrations[sel], key=f"hist_{sel}")
        if len(cals) >= 2:
            with st.expander("Comparar calibraciones"):
                pick = st.multiselect("Calibraciones", list(labels), default=list(labels)[:2], format_func=labels.get,
                                      key=f"cmp_{device_id}")
                if len(pick) >= 2:
                    _compare([ws.calibrations[p] for p in pick])

    st.markdown('<div class="pml-section-title">Identificaciones (borradores)</div>', unsafe_allow_html=True)
    rows = [{"identificación": d.title, "estado": d.status, "etapa": d.stage, "curvas": len(d.curves),
             "calibraciones": len(d.calibration_ids), "actualizado": fmt_dt(d.updated_utc),
             "guardado explícito": fmt_dt(d.saved_explicitly_utc), "id": d.id} for d in drafts]
    if rows:
        st.dataframe(pd.DataFrame(rows).drop(columns=["id"]), hide_index=True, width="stretch")
        cols = st.columns([3, 1, 1])
        opts = {d.id: f"{d.title} · etapa {d.stage} · {fmt_dt(d.updated_utc)}" for d in drafts if d.status == "abierto"}
        if opts:
            pick = cols[0].selectbox("Continuar identificación", list(opts), format_func=opts.get, key=f"cont_{device_id}")
            if cols[1].button("Abrir", key=f"open_{device_id}", width="stretch"):
                shell.go("device", device=device_id, draft=pick, step=ws.drafts[pick].stage, panel="flujo")
                st.rerun()
        if cols[2].button("Nueva identificación", key=f"newdr_{device_id}", width="stretch"):
            dr = ws.new_draft(device_id)
            shell.go("device", device=device_id, draft=dr.id, step=2, panel="flujo")
            st.rerun()
    if sets:
        st.markdown('<div class="pml-section-title">Conjuntos de datos registrados</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"conjunto": s.label, "origen": s.source_kind, "curvas": len(s.curves),
                                    "archivos": ", ".join(s.originals), "fecha": fmt_dt(s.created_utc)} for s in sets]),
                     hide_index=True, width="stretch")
    if exports:
        st.markdown('<div class="pml-section-title">Perfiles exportados</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"archivo": e.filename, "tipo": e.kind, "perfil": e.profile_id,
                                    "calibración": ws.calibrations[e.calibration_id].label if e.calibration_id in ws.calibrations else e.calibration_id,
                                    "fecha": fmt_dt(e.created_utc), "SHA-256": e.sha256[:16] + "…"} for e in exports]),
                     hide_index=True, width="stretch")


def _compare(cals: list[Calibration]) -> None:
    rows = []
    names = sorted({n for c in cals for n in c.free_parameters})
    for c in cals:
        dom = c.profile.get("domain", {}).get("calibration", {}) or {}
        r = {"calibración": c.label, "estado": c.status_code, "validación": c.validation_status,
             "RMSE [mV/celda]": _rmse_mv(c),
             "T [K]": "–".join(f"{v:g}" for v in (dom.get("temperature_K") or [])),
             "P [atm abs]": "–".join(f"{v:g}" for v in (dom.get("cathode_pressure_atm") or [])),
             "j [A/cm²]": "–".join(f"{v:.3g}" for v in (dom.get("j_A_cm2") or []))}
        p = c.parameters()
        for n in names:
            r[n] = p.get(n)
        rows.append(r)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Parámetros identificados en cada calibración (libres en al menos una). Diferencias de dominio o "
               "condiciones impiden comparar directamente los valores.")
