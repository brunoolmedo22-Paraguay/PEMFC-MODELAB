"""Persistencia del espacio de trabajo en el navegador (IndexedDB) + estado de guardado.

Flujo:
1. Al iniciar una sesión, el componente envía una instantánea de los registros guardados en ESTE
   navegador (sin binarios). Se fusiona con lo creado en memoria antes de que llegara.
2. Al final de cada ejecución, los registros modificados se envían en un lote con número de
   secuencia; el lote se reenvía idéntico hasta recibir confirmación (idempotente).
3. La confirmación solo marca como guardado lo que no cambió entre el envío y el acuse.
4. Conflictos (otra pestaña guardó una revisión más nueva; registro inmutable distinto) NO se
   sobrescriben: se informa al usuario.

Si IndexedDB no está disponible (modo privado estricto, políticas del navegador), la aplicación sigue
funcionando en memoria y la exportación de proyecto es el mecanismo de conservación.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

import streamlit as st

from workspace.model import Workspace, now_utc

_JS = (Path(__file__).resolve().parent / "static" / "storage_bridge.js").read_text(encoding="utf-8")
RESEND_AFTER_S = 15.0

ST_LOADING = "cargando"
ST_SAVED = "guardado"
ST_PENDING = "pendiente"
ST_SAVING = "guardando"
ST_CONFLICT = "conflicto"
ST_UNAVAILABLE = "no_disponible"


def _ss():
    return st.session_state


def init() -> None:
    ss = _ss()
    ss.setdefault("ws", Workspace())
    ss.setdefault("ws_session", secrets.token_hex(8))
    ss.setdefault("ws_loaded", False)
    ss.setdefault("ws_seq", 0)
    ss.setdefault("ws_inflight", None)
    ss.setdefault("ws_read", None)
    ss.setdefault("ws_known_blobs", set())
    ss.setdefault("ws_status", {"state": ST_LOADING, "last_saved_utc": None, "message": "", "conflicts": [],
                                "info": None, "load_problems": []})


def workspace() -> Workspace:
    init()
    return _ss().ws


def status() -> dict:
    init()
    s = dict(_ss().ws_status)
    ws = _ss().ws
    if s["state"] not in (ST_LOADING, ST_UNAVAILABLE, ST_CONFLICT):
        if _ss().ws_inflight:
            s["state"] = ST_SAVING
        elif ws.dirty:
            s["state"] = ST_PENDING
        else:
            s["state"] = ST_SAVED
    s["dirty"] = len(ws.dirty)
    return s


def request_blobs(shas) -> None:
    """Pide al navegador los binarios que aún no están en memoria (p. ej. imágenes de un borrador)."""
    ss = _ss()
    missing = [s for s in shas if s and s not in ss.ws.blobs and f"blob:{s}" in ss.ws_known_blobs]
    if missing:
        ss.ws_seq += 1
        ss.ws_read = {"seq": ss.ws_seq, "keys": [f"blob:{s}" for s in missing]}


def missing_blobs(shas) -> list[str]:
    ss = _ss()
    return [s for s in shas if s and s not in ss.ws.blobs]


# --------------------------------------------------------------------------- callbacks del componente
def _payload(name: str):
    val = _ss().get("pml_store")
    if val is None:
        return None
    try:
        return val.get(name) if hasattr(val, "get") else getattr(val, name, None)
    except Exception:  # noqa: BLE001
        return None


def _on_snapshot() -> None:
    ss = _ss()
    snap = _payload("snapshot")
    if not snap or snap.get("session") != ss.ws_session:
        return
    records, problems = {}, []
    for key, rec in (snap.get("records") or {}).items():
        try:
            records[key] = json.loads(rec["value"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            problems.append(f"{key}: ilegible ({exc})")
    loaded, load_problems = Workspace.from_records(records)
    ws = ss.ws
    for key, val in loaded.all_records().items():
        if ws.record_value(key) is None:            # lo creado en memoria antes de cargar se conserva
            ws.load_record(key, val)
    for key, rev in loaded.base_rev.items():
        ws.base_rev.setdefault(key, rev)
    ss.ws_known_blobs = set((snap.get("blobs") or {}).keys())
    ss.ws_loaded = True
    st_ = ss.ws_status
    st_["state"] = ST_SAVED
    st_["info"] = snap.get("info")
    st_["load_problems"] = problems + load_problems
    st_["loaded_utc"] = now_utc()
    st_["n_loaded"] = len(records)


def _on_ack() -> None:
    ss = _ss()
    ack = _payload("ack")
    infl = ss.ws_inflight
    if not ack or not infl or ack.get("seq") != infl["seq"]:
        return
    ws = ss.ws
    for key in ack.get("saved", []):
        sent = infl["values"].get(key)
        if sent is not None and json.dumps(ws.record_value(key), ensure_ascii=False) == sent["value"]:
            ws.mark_saved([key])
        else:
            ws.base_rev[key] = sent["rev"] if sent else ws.base_rev.get(key, 0)
    st_ = ss.ws_status
    conflicts = ack.get("conflicts") or []
    if ack.get("error"):
        st_["state"], st_["message"] = ST_UNAVAILABLE, f"No se pudo guardar en el navegador: {ack['error']}"
    elif conflicts:
        for c in conflicts:
            ws.dirty.discard(c["key"])
        st_["state"] = ST_CONFLICT
        st_["conflicts"] = conflicts
        st_["message"] = ("Otra pestaña o ventana guardó una versión más reciente de: "
                          + ", ".join(c["key"] for c in conflicts)
                          + ". Sus cambios en esos registros NO se guardaron (no se sobrescribe). Recargue la página "
                            "para ver la versión guardada o exporte el proyecto para conservar esta sesión.")
    else:
        st_["state"] = ST_SAVED
        st_["last_saved_utc"] = now_utc()
        st_["message"] = ""
    ss.ws_inflight = None


def _on_blobs() -> None:
    ss = _ss()
    got = _payload("blobs")
    if not got:
        return
    for key, rec in (got.get("items") or {}).items():
        try:
            ss.ws.load_record(key, json.loads(rec["value"]))
        except Exception as exc:  # noqa: BLE001
            ss.ws_status["load_problems"].append(f"{key}: {exc}")
    ss.ws_read = None


def _on_error() -> None:
    ss = _ss()
    err = _payload("error")
    if not err or err.get("session") != ss.ws_session:
        return
    ss.ws_status["state"] = ST_UNAVAILABLE
    ss.ws_status["message"] = (f"Persistencia del navegador no disponible ({err.get('message')}). El trabajo se "
                               "mantiene solo en esta sesión: use «Exportar proyecto» para conservarlo.")
    ss.ws_loaded = True        # se permite trabajar en memoria


def acknowledge_conflicts() -> None:
    st_ = _ss().ws_status
    st_["state"], st_["conflicts"], st_["message"] = ST_SAVED, [], ""


# --------------------------------------------------------------------------- render (al FINAL de app.py)
def render_bridge() -> None:
    """Debe llamarse al final de cada ejecución completa: envía los cambios de esta ejecución."""
    init()
    ss = _ss()
    ws = ss.ws
    infl = ss.ws_inflight
    if infl and time.time() - infl["sent"] > RESEND_AFTER_S:
        infl = ss.ws_inflight = None                    # sin acuse: se reenvía con secuencia nueva
    if infl is None and ws.dirty and ss.ws_loaded and ss.ws_status["state"] != ST_UNAVAILABLE:
        ops = ws.pending()
        if ops:
            ss.ws_seq += 1
            ss.ws_inflight = infl = {"seq": ss.ws_seq, "sent": time.time(),
                                     "values": {o["key"]: {"value": o["value"], "rev": o["rev"]} for o in ops},
                                     "payload": {"seq": ss.ws_seq, "items": ops}}
    data = {"session": ss.ws_session, "write": infl["payload"] if infl else None, "read": ss.ws_read}
    comp = st.components.v2.component("pml_storage_bridge", js=_JS)
    comp(key="pml_store", data=data, on_snapshot_change=_on_snapshot, on_ack_change=_on_ack,
         on_blobs_change=_on_blobs, on_error_change=_on_error)
