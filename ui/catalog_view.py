"""Pantalla inicial del Motor 1: bienvenida, catálogo de dispositivos y copias de seguridad."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from workspace.model import ADM_TEXT, WorkspaceError
from workspace.project_io import PROJECT_SUFFIX, export_project, import_project, import_v020_profile

from . import device_admin, persistence, shell

INTRO = ("Registra tus dispositivos PEMFC, incorpora datos experimentales e identifica sus parámetros para construir "
         "modelos digitales calibrados y reproducibles.")

# Curva de polarización estilizada (recurso gráfico del módulo; no representa datos).
MOTOR1_ART = """<svg class="m1-art" viewBox="0 0 220 120" aria-hidden="true">
  <defs><linearGradient id="m1g" x1="0" x2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".9"/>
  <stop offset="1" stop-color="currentColor" stop-opacity=".35"/></linearGradient></defs>
  <path d="M14 14 V106 H210" fill="none" stroke="currentColor" stroke-opacity=".28" stroke-width="1.6"/>
  <path d="M16 22 C26 40 34 46 52 52 S120 66 150 74 S188 88 200 104" fill="none" stroke="url(#m1g)" stroke-width="3" stroke-linecap="round"/>
  <g fill="currentColor" fill-opacity=".75"><circle cx="30" cy="40" r="2.6"/><circle cx="60" cy="54" r="2.6"/><circle cx="96" cy="61" r="2.6"/>
  <circle cx="132" cy="69" r="2.6"/><circle cx="166" cy="80" r="2.6"/><circle cx="192" cy="96" r="2.6"/></g>
  <text x="18" y="118" font-size="8" fill="currentColor" fill-opacity=".55">j</text><text x="4" y="20" font-size="8" fill="currentColor" fill-opacity=".55">V</text>
</svg>"""


def _ss():
    return st.session_state


def _open_device(device_id: str) -> None:
    ws = persistence.workspace()
    drafts = [d for d in ws.device_drafts(device_id) if d.status == "abierto"]
    shell.go("device", device=device_id, draft=drafts[0].id if drafts else None, step=drafts[0].stage if drafts else 1,
             panel="flujo")


def _on_catalog() -> None:
    a = shell.payload("pml_catalog")
    if not a:
        return
    if a.get("type") == "open" and a.get("id") in persistence.workspace().devices:
        _open_device(a["id"])
    elif a.get("type") == "manage":
        _ss()["show_manage"] = True
        ws = persistence.workspace()
        refs = set()
        for did in ws.devices:
            refs |= ws.device_blob_refs(did)
        persistence.request_blobs(persistence.missing_blobs(refs))     # para poder exportar sin esperas
    elif a.get("type") == "add":
        _ss()["show_new_device"] = True


@st.dialog("Nuevo dispositivo", width="small", on_dismiss=lambda: _ss().__setitem__("show_new_device", False))
def _new_device_dialog() -> None:
    st.caption("Solo el nombre es obligatorio. Las propiedades técnicas se completan después, en la etapa 01; "
               "las imprescindibles se exigirán antes de calibrar, nunca se inventan.")
    name = st.text_input("Nombre del dispositivo *", key="nd_name", placeholder="p. ej. Stack de laboratorio 1 kW")
    man = st.text_input("Fabricante", key="nd_man", placeholder="opcional")
    mod = st.text_input("Modelo", key="nd_mod", placeholder="opcional")
    c1, c2 = st.columns(2)
    if c1.button("Crear dispositivo", type="primary", width="stretch", disabled=not str(name).strip()):
        try:
            d = persistence.workspace().create_device(name, man, mod, provenance="Creado en PEMFC ModelLab.")
        except WorkspaceError as exc:
            st.error(str(exc))
            return
        dr = persistence.workspace().new_draft(d.id)
        for k in ("nd_name", "nd_man", "nd_mod"):
            _ss().pop(k, None)
        _ss()["show_new_device"] = False
        shell.go("device", device=d.id, draft=dr.id, step=1, panel="flujo")
        st.rerun()
    if c2.button("Cancelar", width="stretch"):
        _ss()["show_new_device"] = False
        st.rerun()


def _backups() -> None:
    ws = persistence.workspace()
    with st.expander("Proyectos, copias de seguridad y compatibilidad"):
        st.markdown(
            "Los dispositivos se guardan **en este navegador** (IndexedDB): sobreviven a recargas y cierres, pero se "
            "pierden si se borran los datos del sitio y no se sincronizan entre equipos. Para una copia independiente "
            f"exporte el proyecto (`{PROJECT_SUFFIX}`) y vuelva a importarlo cuando lo necesite.")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Exportar proyecto**")
            if ws.devices:
                if st.button("Preparar copia de todo el espacio de trabajo", key="bk_prep", width="stretch"):
                    _ss()["bk_blob"] = export_project(ws)
                    _ss()["bk_name"] = f"pemfc_modellab_{datetime.now():%Y%m%d_%H%M}{PROJECT_SUFFIX}"
                if _ss().get("bk_blob"):
                    st.download_button("Descargar proyecto", _ss()["bk_blob"], file_name=_ss()["bk_name"],
                                       mime="application/zip", key="bk_dl", width="stretch")
            else:
                st.caption("Aún no hay dispositivos.")
        with c2:
            st.markdown("**Importar proyecto**")
            up = st.file_uploader("Proyecto .pmlproj.zip", type=["zip"], key="bk_up", label_visibility="collapsed")
            if up is not None and st.button("Importar sin sobrescribir", key="bk_imp", width="stretch"):
                try:
                    rep = import_project(ws, up.getvalue())
                    (st.success if rep.ok else st.warning)("\n".join(rep.messages + rep.rejected))
                except WorkspaceError as exc:
                    st.error(str(exc))
        with c3:
            st.markdown("**Perfil de v0.1/v0.2**")
            upp = st.file_uploader("profile.json", type=["json"], key="bk_prof", label_visibility="collapsed")
            if upp is not None and st.button("Migrar como dispositivo nuevo", key="bk_mig", width="stretch"):
                try:
                    m = import_v020_profile(ws, upp.getvalue(), upp.name)
                    st.success(f"Dispositivo creado con la calibración migrada. " + " ".join(m.messages))
                except WorkspaceError as exc:
                    st.error(str(exc))


def render() -> None:
    ws = persistence.workspace()
    st.html(f"""<div class="m1-hero"><div class="m1-text">
      <div class="m1-chip"><span class="m1-dot"></span>MOTOR 1 · IDENTIFICACIÓN Y CALIBRACIÓN</div>
      <h1>Bienvenido al Motor 1</h1><p>{INTRO}</p></div>{MOTOR1_ART}</div>""")
    st.html(device_admin.ADMIN_CSS)
    loaded = st.session_state.get("ws_loaded", False)
    devices = ws.list_devices(sort="recientes")
    if not loaded and not devices:
        st.caption("Cargando los dispositivos guardados en este navegador…")
    data = {"devices": devices, "statuses": [[k, v] for k, v in ADM_TEXT.items()]}
    shell.component("catalog")(key="pml_catalog", data=data, on_action_change=_on_catalog)
    _backups()
    if _ss().get("show_new_device"):
        _new_device_dialog()
    elif _ss().get("show_manage"):
        device_admin.manage_dialog()
