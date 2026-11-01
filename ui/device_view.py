"""Espacio de trabajo de un dispositivo: flujo guiado 01–06 e historial."""
from __future__ import annotations

import os
import sys

import streamlit as st

from identification.datasets import check_curve_set
from identification.optimizer import structural_checks
from pemfc_core.parameters import ORIGINS
from workspace.model import ADM_TEXT, WorkspaceError
from workspace.project_io import config_key
from workspace.serialization import fit_config_to_dict

from . import (
    configure_view, draft_binding, export_view, fit_view, history_view, import_view, persistence, results_view, shell,
    state,
)

STEPS = [(1, "Dispositivo"), (2, "Datos experimentales"), (3, "Configuración del modelo"), (4, "Calibración"),
         (5, "Análisis y validación"), (6, "Perfil y exportación")]
DEVICE_ORIGINS = [o for o in ORIGINS if o != "IDENTIFICADO"]


def _ss():
    return st.session_state


# --------------------------------------------------------------------------- estados de las etapas
def _current_calibration(ws, draft):
    """Calibración registrada que corresponde a los datos y la configuración actuales del borrador."""
    ss = _ss()
    if not ss.get("curves") or ss.get("fit_config") is None:
        return None
    dk = state.data_key()
    ck = config_key(dk, fit_config_to_dict(ss.fit_config))
    cands = [ws.calibrations[c] for c in draft.calibration_ids if c in ws.calibrations]
    cands = [c for c in cands if c.data_key == dk and c.config_key == ck]
    return cands[-1] if cands else None


def step_states(ws, dev, draft) -> list[dict]:
    ss = _ss()
    curves = ss.get("curves") or []
    cfg = ss.get("fit_config")
    mism = draft_binding.geometry_mismatch()
    out = []
    # 01
    errs = dev.validate()
    s1 = ("atencion", "corrija los datos del dispositivo") if errs else (
        ("atencion", "geometría distinta de la usada al importar") if mism else ("completa", ""))
    if s1[0] == "completa" and dev.missing_for_identification:
        s1 = ("completa", "sin " + " ni ".join(dev.missing_for_identification))
    out.append(s1)
    # 02
    set_errors = [i for i in check_curve_set(curves) if i.level == "error"] if curves else []
    if not curves:
        s2 = ("pendiente", "importe al menos una curva V–I")
    elif set_errors or mism:
        s2 = ("atencion", "conjunto con errores" if set_errors else "reimporte con la geometría actual")
    else:
        s2 = ("completa", f"{len(curves)} curva(s)")
    out.append(s2)
    # 03
    if not curves:
        s3 = ("bloqueada", "faltan datos")
    elif cfg is None:
        s3 = ("pendiente", "elija un preset o configure")
    elif any(i.level == "error" for i in structural_checks(curves, cfg)):
        s3 = ("atencion", "configuración incompatible con los datos")
    else:
        s3 = ("completa", f"{len(cfg.free_names())} libres · {cfg.n_starts} inicios")
    out.append(s3)
    # 04
    cal = _current_calibration(ws, draft)
    current_mem = ss.get("fit_result") is not None and state.result_is_current()
    if s3[0] != "completa":
        s4 = ("bloqueada", "complete la configuración")
    elif current_mem or cal is not None:
        code = cal.status_code if cal else ss.fit_result.status
        s4 = ("completa", code)
    elif draft.calibration_ids:
        s4 = ("atencion", "resultado desactualizado: datos o configuración cambiaron")
    else:
        s4 = ("pendiente", "ejecute la identificación")
    out.append(s4)
    # 05
    out.append(("completa", "resultados disponibles") if s4[0] == "completa" else ("bloqueada", "requiere calibración vigente"))
    # 06
    if s4[0] != "completa":
        s6 = ("bloqueada", "requiere calibración vigente")
    else:
        exported = cal is not None and any(e.calibration_id == cal.id for e in ws.exports.values())
        s6 = ("completa", "perfil exportado") if exported else ("progreso", "perfil listo para exportar")
    out.append(s6)
    return [{"n": n, "title": t, "state": s, "reason": r} for (n, t), (s, r) in zip(STEPS, out)]


# --------------------------------------------------------------------------- etapa 01
def _device_widgets_from(dev) -> None:
    ss = _ss()
    ss.d1_for = dev.id + f"@{dev.rev}"
    for f in ("name", "manufacturer", "model", "technology", "configuration", "datasheet_reference", "notes", "provenance"):
        ss[f"d1_{f}"] = getattr(dev, f) or ""
    ss.d1_n_cells = dev.n_cells
    ss.d1_area = dev.active_area_cm2
    ss.d1_n_origin, ss.d1_a_origin = dev.n_cells_origin, dev.active_area_origin
    ss.d1_power, ss.d1_vnom, ss.d1_inom = dev.rated_power_W, dev.nominal_voltage_V, dev.nominal_current_A


def _save_device(dev_id: str) -> None:
    ss = _ss()
    ws = persistence.workspace()
    try:
        ws.update_device(dev_id, name=ss.d1_name, manufacturer=ss.d1_manufacturer, model=ss.d1_model,
                         technology=ss.d1_technology, configuration=ss.d1_configuration,
                         n_cells=ss.d1_n_cells, n_cells_origin=ss.d1_n_origin, active_area_cm2=ss.d1_area,
                         active_area_origin=ss.d1_a_origin, rated_power_W=ss.d1_power, nominal_voltage_V=ss.d1_vnom,
                         nominal_current_A=ss.d1_inom, datasheet_reference=ss.d1_datasheet_reference,
                         notes=ss.d1_notes, provenance=ss.d1_provenance)
        ss.d1_msg = ("success", "Dispositivo actualizado.")
        dev = ws.devices[dev_id]
        if not draft_binding.geometry_mismatch() and ss.get("device") is not None:
            info = dev.to_device_info()
            if not ss.get("curves"):
                ss.device = info
        ss.d1_for = dev.id + f"@{dev.rev}"
    except (WorkspaceError, ValueError, TypeError) as exc:
        ss.d1_msg = ("error", f"No se guardó: {exc}")


def step1(dev) -> None:
    ss = _ss()
    if ss.get("d1_for") != dev.id + f"@{dev.rev}":
        _device_widgets_from(dev)
    st.markdown('<div class="pml-section-title">Identidad y configuración</div>', unsafe_allow_html=True)
    st.caption(f"Identificador interno estable: `{dev.id}` (no cambia aunque se renombre el dispositivo).")
    c = st.columns(3)
    c[0].text_input("Nombre del dispositivo *", key="d1_name")
    c[1].text_input("Fabricante", key="d1_manufacturer")
    c[2].text_input("Modelo", key="d1_model")
    c = st.columns(2)
    c[0].text_input("Tecnología", key="d1_technology", placeholder="p. ej. PEMFC de baja temperatura")
    c[1].text_input("Configuración", key="d1_configuration", placeholder="p. ej. stack refrigerado por aire")
    st.markdown('<div class="pml-section-title">Geometría</div>', unsafe_allow_html=True)
    st.caption("N_cells y A_active solo son imprescindibles si los datos se expresan como corriente total o tensión de "
               "stack; se exigen entonces antes de calibrar. Nunca se infieren. Deje vacío lo que no esté documentado.")
    c = st.columns(4)
    c[0].number_input("Número de celdas", min_value=1, max_value=5000, step=1, value=None, key="d1_n_cells")
    c[1].selectbox("Origen de N_cells", DEVICE_ORIGINS, key="d1_n_origin")
    c[2].number_input("Área activa [cm²]", min_value=0.0, value=None, format="%.6g", key="d1_area")
    c[3].selectbox("Origen del área", DEVICE_ORIGINS, key="d1_a_origin")
    st.markdown('<div class="pml-section-title">Datos nominales (documentales)</div>', unsafe_allow_html=True)
    c = st.columns(3)
    c[0].number_input("Potencia nominal [W]", min_value=0.0, value=None, format="%.6g", key="d1_power")
    c[1].number_input("Tensión nominal [V]", min_value=0.0, value=None, format="%.6g", key="d1_vnom")
    c[2].number_input("Corriente nominal [A]", min_value=0.0, value=None, format="%.6g", key="d1_inom")
    st.text_input("Referencias de datasheet", key="d1_datasheet_reference",
                  help="Solo documental: el datasheet no se usa en el ajuste.")
    c = st.columns(2)
    c[0].text_area("Observaciones", key="d1_notes", height=80)
    c[1].text_area("Procedencia de los datos", key="d1_provenance", height=80)
    st.button("Guardar cambios del dispositivo", type="primary", key="d1_save", on_click=_save_device, args=(dev.id,))
    msg = ss.pop("d1_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    mism = draft_binding.geometry_mismatch()
    if mism:
        st.warning(f"Las curvas de esta identificación se normalizaron con N_cells, A = {mism['used']}, distinto del "
                   f"dispositivo {mism['device']}. Reimporte las curvas en la etapa 02 o restaure la geometría; los "
                   "resultados obtenidos con la geometría anterior quedan como desactualizados (no se borran).")


# --------------------------------------------------------------------------- etapas 04–06 con calibración registrada
def _registered_view(ws, draft, step: int) -> bool:
    """Si no hay resultado en memoria (p. ej. tras recargar) pero existe una calibración vigente, se muestra."""
    ss = _ss()
    if ss.get("fit_result") is not None and state.result_is_current():
        return False
    cal = _current_calibration(ws, draft)
    if cal is None:
        return False
    st.info("Mostrando la calibración registrada para estos datos y esta configuración (solo lectura). Puede volver a "
            "ejecutar la identificación: se registrará como una calibración nueva, sin sobrescribir esta.")
    history_view.render_calibration(cal, key=f"reg{step}_{cal.id}", allow_actions=step == 6)
    return True


def _record_export(kind, filename, data):
    cid = draft_binding.current_calibration_id()
    if cid:
        persistence.workspace().record_export(cid, filename, data, kind)


# --------------------------------------------------------------------------- vista
def _on_stepper() -> None:
    a = shell.payload("pml_stepper")
    if a and a.get("type") == "goto":
        _go_step(int(a["step"]))


def _go_step(n: int) -> None:
    r = shell.route()
    ws = persistence.workspace()
    if r.get("draft") in ws.drafts and ws.drafts[r["draft"]].status == "abierto":
        ws.update_draft(r["draft"], stage=n)
    shell.go("device", device=r["device"], draft=r["draft"], step=n, panel="flujo")


def _save_draft() -> None:
    draft_binding.explicit_save()
    _ss()["dv_saved_msg"] = True


def _header(ws, dev, draft) -> None:
    r = shell.route()
    c1, c2 = st.columns([5, 2])
    with c1:
        if st.button("← Dispositivos", key="dv_back"):
            shell.go("catalog")
            st.rerun()
        chips = [f'<span class="pml-kv">{x}</span>' for x in
                 ([" · ".join(v for v in (dev.manufacturer, dev.model) if v)] if (dev.manufacturer or dev.model) else [])
                 + [f"N_cells {dev.n_cells or '—'}", f"A {dev.active_area_cm2 or '—'} cm²", ADM_TEXT[ws.admin_status(dev.id)]]]
        st.html(f'<div class="pml-devhead"><h2>{_esc(dev.name)}</h2>{"".join(chips)}'
                f'<span class="pml-mono" style="opacity:.6">{dev.id}</span></div>')
    with c2:
        st.segmented_control("Vista", ["Flujo de identificación", "Historial y perfiles"], key="dv_panel_sel",
                             default="Historial y perfiles" if r.get("panel") == "historial" else "Flujo de identificación",
                             on_change=_on_panel, label_visibility="collapsed")
    if r.get("panel") != "historial" and draft is not None:
        drafts = [d for d in ws.device_drafts(dev.id) if d.status == "abierto"]
        opts = {d.id: f"{d.title} · actualizado {history_view.fmt_dt(d.updated_utc)}" for d in drafts}
        cc = st.columns([4, 1.3, 1.3])
        if len(opts) > 1:
            pick = cc[0].selectbox("Identificación en curso", list(opts), index=list(opts).index(draft.id),
                                   format_func=opts.get, key=f"dv_draft_{dev.id}")
            if pick != draft.id:
                shell.go("device", device=dev.id, draft=pick, step=ws.drafts[pick].stage, panel="flujo")
                st.rerun()
        else:
            cc[0].caption(f"Identificación en curso: **{draft.title}** · borrador `{draft.id}` · último guardado explícito: "
                          f"{history_view.fmt_dt(draft.saved_explicitly_utc)}")
        if cc[2].button("Nueva identificación", key="dv_newdraft", width="stretch",
                        help="Crea otra identificación para este dispositivo sin tocar la actual ni sus calibraciones."):
            nd = ws.new_draft(dev.id)
            shell.go("device", device=dev.id, draft=nd.id, step=2, panel="flujo")
            st.rerun()


def _on_panel() -> None:
    r = shell.route()
    sel = _ss().get("dv_panel_sel")
    shell.go("device", device=r["device"], draft=r["draft"], step=r["step"],
             panel="historial" if sel == "Historial y perfiles" else "flujo")


def _esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render() -> None:
    ss = _ss()
    r = shell.route()
    ws = persistence.workspace()
    did = r.get("device")
    if did not in ws.devices:
        if not ss.get("ws_loaded"):
            st.caption("Cargando el espacio de trabajo guardado en este navegador…")
            return
        st.error("Este dispositivo no existe en el espacio de trabajo de este navegador (¿otro equipo o datos borrados?). "
                 "Importe el proyecto si dispone de una copia.")
        if st.button("Volver al catálogo"):
            shell.go("catalog")
            st.rerun()
        return
    dev = ws.devices[did]
    draft = ws.drafts.get(r.get("draft"))
    if draft is None or draft.device_id != did:
        opened = [d for d in ws.device_drafts(did) if d.status == "abierto"]
        draft = opened[0] if opened else ws.new_draft(did)
        r["draft"] = draft.id
    for w in draft_binding.ensure_open(did, draft.id):
        st.toast(w)
    export_view.set_export_hook(_record_export)
    _header(ws, dev, draft)
    if r.get("panel") == "historial":
        history_view.render(did)
        return
    states = step_states(ws, dev, draft)
    step = int(r.get("step") or 1)
    if states[step - 1]["state"] == "bloqueada":
        step = max(s["n"] for s in states if s["state"] != "bloqueada" and s["n"] <= step)
        r["step"] = step
    shell.component("stepper")(key="pml_stepper", data={"steps": states, "current": step}, on_action_change=_on_stepper)
    st.html(f'<div class="pml-eyebrow" style="margin-top:.6rem">Etapa {step:02d}</div>'
            f'<div class="pml-section-title" style="font-size:1.35rem">{STEPS[step - 1][1]}</div>')
    with st.container(border=True):
        if step == 1:
            step1(dev)
        elif step == 2:
            sug = draft_binding.align_device()
            if sug:
                txt = ", ".join(f"{k} = {v:g}" for k, v in sug.items() if v is not None)
                c1, c2 = st.columns([4, 1.3])
                c1.info(f"Los datos cargados declaran una geometría que el dispositivo no tiene ({txt}). No se copia "
                        "automáticamente: puede adoptarla de forma explícita (quedará anotada su procedencia).")
                c2.button("Adoptar en el dispositivo", key="adopt_geom", on_click=draft_binding.adopt_geometry,
                          args=(sug.get("n_cells"), sug.get("active_area_cm2")), width="stretch")
            from . import digitizer_view
            digitizer_view.use_context(f"motor1:{draft.id}")      # digitalizador propio de esta identificación
            import_view.render(with_device=False)
        elif step == 3:
            configure_view.render()
        elif step == 4:
            _registered_view(ws, draft, 4)
            fit_view.render()
        elif step == 5:
            if not _registered_view(ws, draft, 5):
                results_view.render()
        elif step == 6:
            if not _registered_view(ws, draft, 6):
                export_view.render()
    draft_binding.sync()
    states = step_states(ws, dev, draft)
    ss.dv_states = states                     # estados vigentes (también para pruebas e inspección)
    if st.query_params.get("debug") == "1":
        ss.pml_debug = True
    if ss.get("pml_debug") or os.environ.get("PML_DEBUG") == "1":
        _debug_panel(ws, draft)
    _bottom_nav(states, step)


def _bottom_nav(states, step: int) -> None:
    ss = _ss()
    st.write("")
    c = st.columns([1.2, 1.4, 3, 1.4])
    if c[0].button("← Anterior", key="nav_prev", disabled=step == 1, width="stretch"):
        _go_step(step - 1)
        st.rerun()
    c[1].button("Guardar borrador", key="nav_save", on_click=_save_draft, width="stretch",
                help="Guarda explícitamente el estado de esta identificación. Además se guarda automáticamente tras "
                     "cada cambio relevante.")
    cur = states[step - 1]
    can = step < 6 and cur["state"] == "completa" and states[step]["state"] != "bloqueada"
    reason = "" if can else (cur["reason"] if cur["state"] != "completa" else states[step]["reason"] if step < 6 else "")
    if ss.pop("dv_saved_msg", False):
        c[2].success("Borrador guardado.")
    elif reason and step < 6:
        c[2].caption(f"Para continuar: {reason}.")
    if c[3].button("Continuar →", key="nav_next", type="primary", disabled=not can, width="stretch"):
        _go_step(step + 1)
        st.rerun()


def _debug_panel(ws, draft) -> None:
    """Diagnóstico (solo con ?debug=1): huellas actuales frente a las de las calibraciones del borrador."""
    import json as _json
    ss = _ss()
    dk = state.data_key() if ss.get("curves") else ""
    cfg = fit_config_to_dict(ss.fit_config) if ss.get("fit_config") else None
    ck = config_key(dk, cfg)
    lines = [f"DBG data_key={dk[:12]} config_key={ck[:12]} device=({ss.device.n_cells},{ss.device.active_area_cm2})"]
    for cid in draft.calibration_ids:
        c = ws.calibrations.get(cid)
        if c:
            lines.append(f"DBG cal {c.label} data_key={c.data_key[:12]} config_key={c.config_key[:12]}")
            old = c.profile.get("fit", {}).get("config") or {}
            def walk(a, b, p=""):
                if isinstance(a, dict) and isinstance(b, dict):
                    for k in sorted(set(a) | set(b)):
                        walk(a.get(k), b.get(k), f"{p}/{k}")
                elif _json.dumps(a, sort_keys=True, default=str) != _json.dumps(b, sort_keys=True, default=str):
                    lines.append(f"DBG diff {p}: {a!r} -> {b!r}"[:220])
            walk(old, cfg or {})
    st.code("\n".join(lines))
    if os.environ.get("PML_DEBUG") == "1":
        print(f"[step {shell.route().get('step')}] " + " || ".join(lines), file=sys.stderr, flush=True)
