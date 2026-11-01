"""Gestión de dispositivos registrados: exportar (ZIP individual), importar con resolución de conflictos y
eliminar de forma deliberada. Todas las operaciones pasan por ``workspace`` (sin lógica científica aquí)."""
from __future__ import annotations

from html import escape

import streamlit as st

from workspace.model import ADM_TEXT, WorkspaceError
from workspace.project_io import (
    DEVICE_SUFFIX, PROJECT_SUFFIX, analyze_package, export_device, import_project,
)

from . import persistence
from .history_view import fmt_dt

STRATEGY_TEXT = {"copia": "Importar como copia independiente (id nuevo)",
                 "reemplazar": "Reemplazar el dispositivo existente",
                 "omitir": "No importar este dispositivo"}


def _ss():
    return st.session_state


def _close() -> None:
    for k in [k for k in _ss().keys() if str(k).startswith("mg_")]:
        if not str(k).startswith("mg_up_"):
            del _ss()[k]
    _ss()["show_manage"] = False


def _ask_delete(device_id: str) -> None:
    _ss()["mg_delete"] = device_id
    _ss()["mg_delete_name"] = ""


def _do_delete(device_id: str) -> None:
    ws = persistence.workspace()
    name = _ss().get("mg_delete_name", "")
    try:
        s = ws.delete_device(device_id, name)
    except WorkspaceError as exc:
        _ss()["mg_msg"] = ("error", str(exc))
        return
    _ss()["mg_delete"] = None
    _ss()["mg_msg"] = ("success", f"Dispositivo «{s['device']}» eliminado: {s['calibrations']} calibración(es), "
                                  f"{s['drafts']} identificación(es), {s['datasets']} conjunto(s) de datos y "
                                  f"{s['exports']} registro(s) de exportación. El catálogo ya está actualizado.")
    r = _ss().get("route") or {}
    if r.get("device") == device_id:
        from . import shell
        shell.go("catalog")


def _device_card(ws, s: dict) -> None:
    did = s["id"]
    act = s["active_profile"]
    with st.container(border=True, key=f"mg_card_{did}"):
        c1, c2 = st.columns([3.2, 1.6], vertical_alignment="center")
        c1.html(
            f'<div class="mg-card"><div class="mg-name">{escape(s["name"])}</div>'
            f'<div class="mg-sub">{escape(" · ".join(v for v in (s["manufacturer"], s["model"]) if v) or "Fabricante y modelo sin declarar")}</div>'
            f'<div class="mg-meta"><span class="mg-badge s-{s["admin_status"]}">{escape(s["admin_text"])}</span>'
            f'<span>{s["n_calibrations"]} calibración(es)</span><span>{s["n_drafts"]} identificación(es)</span>'
            f'<span>{s["n_datasets"]} conjunto(s) de datos</span>'
            f'<span>perfil activo: {escape(act["status_code"]) if act else "ninguno"}</span>'
            f'<span class="mg-id">{escape(did)}</span><span>modificado {escape(fmt_dt(s["last_modified_utc"]))}</span></div></div>')
        with c2:
            prepared = _ss().get("mg_export", {}).get(did)
            if prepared:
                st.download_button("Descargar ZIP", prepared[1], file_name=prepared[0], mime="application/zip",
                                   key=f"mg_dl_{did}", width="stretch", type="primary")
            else:
                st.button("Exportar ZIP", key=f"mg_exp_{did}", width="stretch", on_click=_export, args=(did,),
                          help="Paquete autosuficiente: metadatos, curvas, calibraciones, perfiles, borradores y originales.")
            st.button("Eliminar…", key=f"mg_del_{did}", width="stretch", on_click=_ask_delete, args=(did,))
        if _ss().get("mg_delete") == did:
            _delete_panel(ws, s)


def _export(did: str) -> None:
    ws = persistence.workspace()
    missing = persistence.missing_blobs(ws.device_blob_refs(did))
    if missing:
        persistence.request_blobs(missing)
        _ss()["mg_msg"] = ("warning", "Recuperando del navegador los archivos originales de este dispositivo; vuelva a "
                                      "pulsar «Exportar ZIP» en unos segundos.")
        return
    try:
        name, data = export_device(ws, did)
    except WorkspaceError as exc:
        _ss()["mg_msg"] = ("error", str(exc))
        return
    _ss().setdefault("mg_export", {})[did] = (name, data)


def _delete_panel(ws, s: dict) -> None:
    did = s["id"]
    st.error(f"**Eliminar «{s['name']}»** (`{did}`). Se borrarán definitivamente de este navegador el dispositivo, "
             f"sus {s['n_calibrations']} calibración(es) y perfiles, {s['n_drafts']} identificación(es) en curso y "
             f"{s['n_datasets']} conjunto(s) de datos experimentales. No se puede deshacer.")
    c1, c2 = st.columns(2)
    with c1:
        st.caption("Recomendado: descargue antes una copia de respaldo.")
        prepared = _ss().get("mg_export", {}).get(did)
        if prepared:
            st.download_button("Descargar copia de respaldo", prepared[1], file_name=prepared[0],
                               mime="application/zip", key=f"mg_bk_{did}", width="stretch")
        else:
            st.button("Preparar copia de respaldo", key=f"mg_bkp_{did}", width="stretch", on_click=_export, args=(did,))
    with c2:
        st.text_input(f"Escriba el nombre exacto para confirmar: {s['name']}", key="mg_delete_name")
    d1, d2 = st.columns(2)
    ok = _ss().get("mg_delete_name", "").strip() == s["name"].strip()
    d1.button("Eliminar definitivamente", key=f"mg_go_{did}", type="primary", disabled=not ok, width="stretch",
              on_click=_do_delete, args=(did,))
    d2.button("Cancelar", key=f"mg_cancel_{did}", width="stretch",
              on_click=lambda: _ss().__setitem__("mg_delete", None))


def _import_section(ws) -> None:
    st.markdown('<div class="pml-section-title">Importar dispositivo</div>', unsafe_allow_html=True)
    st.caption(f"Paquetes `{DEVICE_SUFFIX}` (un dispositivo) o `{PROJECT_SUFFIX}` (proyecto completo) exportados por "
               "PEMFC ModelLab. Se validan integridad (SHA-256 por registro), rutas, tamaño y versión antes de importar.")
    nonce = _ss().setdefault("mg_up_nonce", 0)
    up = st.file_uploader("Paquete ZIP", type=["zip"], key=f"mg_up_{nonce}", label_visibility="collapsed")
    if up is None:
        return
    data = up.getvalue()
    try:
        an = analyze_package(ws, data)
    except WorkspaceError as exc:
        st.error(f"Paquete rechazado: {exc}")
        return
    st.info(f"Paquete válido: {len(an.devices)} dispositivo(s), {an.n_records} registro(s), {an.n_blobs} archivo(s) "
            f"original(es). Creado con ModelLab {an.manifest.get('app_version')} el {fmt_dt(an.manifest.get('created_utc'))}."
            + ("\n\n" + "\n".join(an.warnings) if an.warnings else ""))
    strategy, ready = {}, True
    for dv in an.devices:
        with st.container(border=True, key=f"mg_imp_{dv['id']}"):
            st.html(f'<div class="mg-card"><div class="mg-name">{escape(dv["name"])}</div>'
                    f'<div class="mg-meta"><span>{dv["n_calibrations"]} calibración(es)</span>'
                    f'<span>{dv["n_drafts"]} identificación(es)</span><span>{dv["n_datasets"]} conjunto(s) de datos</span>'
                    f'<span class="mg-id">{escape(dv["id"])}</span></div></div>')
            if not dv["conflict"]:
                st.caption("Sin conflicto: se importará con su identificador.")
                continue
            st.warning(f"Ya existe un dispositivo con este identificador: «{dv['existing_name']}»"
                       + (" (contenido idéntico)." if dv["identical"] else " (contenido distinto)."))
            choice = st.radio("¿Qué desea hacer?", list(STRATEGY_TEXT), format_func=STRATEGY_TEXT.get,
                              key=f"mg_strat_{dv['id']}", index=0)
            strategy[dv["id"]] = choice
            if choice == "reemplazar":
                ok = st.checkbox(f"Confirmo reemplazar «{dv['existing_name']}»: se eliminarán su versión actual y todo "
                                 "lo asociado, y se sustituirán por el contenido del paquete.",
                                 key=f"mg_conf_{dv['id']}")
                ready = ready and ok
    c1, c2 = st.columns(2)
    c1.button("Importar", key="mg_do_import", type="primary", disabled=not ready, width="stretch",
              on_click=_do_import, args=(f"mg_up_{nonce}", strategy))
    c2.button("Cancelar importación", key="mg_cancel_import", width="stretch", on_click=_reset_import)


def _reset_import() -> None:
    _ss()["mg_up_nonce"] = _ss().get("mg_up_nonce", 0) + 1


def _do_import(upload_key: str, strategy: dict) -> None:
    up = _ss().get(upload_key)
    if up is None:
        return
    try:
        rep = import_project(persistence.workspace(), up.getvalue(), strategy)
    except WorkspaceError as exc:
        _ss()["mg_msg"] = ("error", str(exc))
        return
    _ss()["mg_msg"] = ("success" if rep.ok else "warning", " ".join(rep.messages + rep.rejected))
    _reset_import()


@st.dialog("Gestionar dispositivos", width="large", on_dismiss=_close)
def manage_dialog() -> None:
    ws = persistence.workspace()
    msg = _ss().pop("mg_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    tab_list, tab_import = st.tabs(["Dispositivos registrados", "Importar"])
    with tab_list:
        c1, c2 = st.columns([3, 1.4])
        q = c1.text_input("Buscar", key="mg_q", placeholder="Nombre, fabricante, modelo o id…", label_visibility="collapsed")
        sort = c2.selectbox("Ordenar", ["recientes", "nombre", "fabricante", "estado"], key="mg_sort",
                            format_func={"recientes": "Más recientes", "nombre": "Nombre", "fabricante": "Fabricante",
                                         "estado": "Estado"}.get, label_visibility="collapsed")
        rows = ws.list_devices(query=q or "", sort=sort)
        if not ws.devices:
            st.info("No hay dispositivos registrados en este navegador. Puede crear uno desde el catálogo o importar un "
                    "paquete en la pestaña «Importar».")
        elif not rows:
            st.caption("Ningún dispositivo coincide con la búsqueda.")
        for s in rows:
            _device_card(ws, s)
        st.caption("Los dispositivos se guardan en este navegador (IndexedDB): sobreviven a recargas, no se sincronizan "
                   "entre equipos y se pierden si se borran los datos del sitio. Exporte un ZIP para conservarlos de forma "
                   "independiente. El servidor (p. ej. Streamlit Community Cloud) no guarda ningún dispositivo.")
    with tab_import:
        _import_section(ws)
    st.divider()
    if st.button("Cerrar", key="mg_close", width="stretch"):
        _close()
        st.rerun()


ADMIN_CSS = """
<style>
.mg-card .mg-name { font-weight: 700; font-size: 1.02rem; }
.mg-card .mg-sub { opacity: .72; font-size: .86rem; margin-top: 1px; }
.mg-card .mg-meta { display: flex; flex-wrap: wrap; gap: .3rem .9rem; margin-top: .45rem; font-size: .8rem; opacity: .85; align-items: center; }
.mg-card .mg-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .75rem; opacity: .7; }
.mg-badge { font-weight: 650; font-size: .74rem; padding: .08rem .55rem; border-radius: 999px; border: 1px solid currentColor; }
.mg-badge.s-NUEVO { color: #5B6B7C; } .mg-badge.s-CONFIGURACION_INCOMPLETA { color: #C77700; }
.mg-badge.s-EN_CALIBRACION { color: #2F6FED; } .mg-badge.s-PERFIL_AJUSTADO { color: #0E7C86; }
.mg-badge.s-PERFIL_CON_VALIDACION { color: #2E8B57; }
</style>
"""
_ = ADM_TEXT
