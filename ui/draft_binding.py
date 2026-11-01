"""Enlace entre el borrador persistente y el estado de sesión que usan las vistas científicas existentes.

Las vistas de v0.2.0 (importar, configurar, calibrar, resultados, exportar) siguen trabajando sobre
``st.session_state`` (``curves``, ``device``, ``originals``, ``fit_config``, ``fit_result``…). Este módulo:
- hidrata ese estado al abrir un borrador;
- vuelca los cambios al borrador tras cada ejecución (autoguardado: solo si cambió algo);
- registra cada identificación ejecutada como CALIBRACIÓN NUEVA E INMUTABLE (con su perfil).
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

from identification.profiles import build_profile
from workspace.model import WorkspaceError
from workspace.project_io import config_key, data_key
from workspace.serialization import (
    SerializationError, curve_from_dict, curve_to_dict, fit_config_from_dict, fit_config_to_dict,
)

from . import persistence, state


def _ss():
    return st.session_state


def active() -> tuple[str | None, str | None]:
    return _ss().get("wb_device_id"), _ss().get("wb_draft_id")


def _fingerprint() -> str:
    ss = _ss()
    cfg = json.dumps(fit_config_to_dict(ss.fit_config), sort_keys=True) if ss.get("fit_config") else ""
    origs = sorted((n, hashlib.sha256(b).hexdigest()) for n, b in (ss.get("originals") or {}).items())
    return hashlib.sha256(json.dumps([state.data_key() if ss.get("curves") is not None else "", cfg, origs,
                                      ss.get("dataset_label", "")]).encode()).hexdigest()


def open_draft(device_id: str, draft_id: str) -> list[str]:
    """Carga el borrador en el estado de sesión. Devuelve avisos (p. ej. binarios aún no disponibles)."""
    ss = _ss()
    ws = persistence.workspace()
    dev = ws.devices[device_id]
    dr = ws.drafts[draft_id]
    warnings = []
    try:
        curves = [curve_from_dict(c) for c in dr.curves]
    except SerializationError as exc:
        curves = []
        warnings.append(f"Curvas del borrador no reconstruibles: {exc}")
    ss.curves = curves
    ss.device = dev.to_device_info() if not dr.stage_notes.get("import_geometry") else _import_device(dev, dr)
    origs = ws.originals_bytes(dr.originals)
    missing = persistence.missing_blobs(dr.originals.values())
    if missing:
        persistence.request_blobs(missing)
        warnings.append(f"{len(missing)} archivo(s) original(es) se están recuperando del navegador.")
    ss.originals = origs
    ss.dataset_label = dr.dataset_label
    try:
        ss.fit_config = fit_config_from_dict(dr.fit_config) if dr.fit_config else None
    except SerializationError as exc:
        ss.fit_config = None
        warnings.append(str(exc))
    if ss.fit_config is not None:
        # Sin esto, la vista de configuración aplicaría el preset genérico en una sesión nueva y
        # sobrescribiría la configuración guardada (detectado en pruebas).
        from . import configure_view
        ss.cfg_version = ss.get("cfg_version", 0) + 1
        ss.cfg_base_frame = configure_view._settings_frame(ss.fit_config)
        ss.cfg_base_preset = ss.fit_config.preset
        configure_view._config_to_widgets(ss.fit_config)
    state.clear_results()
    ss.wb_device_id, ss.wb_draft_id = device_id, draft_id
    ss.wb_fp = _fingerprint()
    ss.wb_recorded = {}
    ss.wb_missing_blobs = list(missing)
    # una calibración registrada para estos mismos datos+configuración vuelve a mostrarse (solo lectura)
    return warnings


def _import_device(dev, dr):
    """Geometría con la que se normalizaron las curvas del borrador (puede diferir del dispositivo actual)."""
    g = dr.stage_notes.get("import_geometry") or {}
    info = dev.to_device_info()
    info.n_cells = g.get("n_cells", info.n_cells)
    info.active_area_cm2 = g.get("active_area_cm2", info.active_area_cm2)
    return info


def ensure_open(device_id: str, draft_id: str) -> list[str]:
    ss = _ss()
    if ss.get("wb_device_id") == device_id and ss.get("wb_draft_id") == draft_id:
        missing = [s for s in ss.get("wb_missing_blobs", []) if s not in persistence.workspace().blobs]
        if ss.get("wb_missing_blobs") and not missing:            # binarios recién llegados
            dr = persistence.workspace().drafts[draft_id]
            ss.originals = persistence.workspace().originals_bytes(dr.originals)
            ss.wb_missing_blobs = []
            ss.wb_fp = _fingerprint()
        return []
    return open_draft(device_id, draft_id)


def geometry_mismatch() -> dict | None:
    """Las curvas actuales se normalizaron con una geometría distinta de la del dispositivo."""
    ss = _ss()
    did, rid = active()
    if not did or not ss.get("curves"):
        return None
    dev = persistence.workspace().devices[did]
    used = ss.device
    needs = any(c.mapping.get("current_unit") in ("A", "mA") or c.mapping.get("voltage_basis") == "stack"
                for c in ss.curves)
    if needs and used and (used.n_cells != dev.n_cells or used.active_area_cm2 != dev.active_area_cm2):
        return {"used": (used.n_cells, used.active_area_cm2), "device": (dev.n_cells, dev.active_area_cm2)}
    return None


def align_device() -> dict | None:
    """La identidad del perfil es SIEMPRE la del dispositivo registrado; la geometría usada al normalizar se
    conserva. Devuelve una sugerencia si los datos cargados declaran geometría que el dispositivo no tiene."""
    ss = _ss()
    did, _ = active()
    ws = persistence.workspace()
    if not did or did not in ws.devices:
        return None
    rec = ws.devices[did].to_device_info()
    cur = ss.get("device")
    if cur is None or not ss.get("curves"):
        ss.device = rec
        return None
    if (cur.n_cells, cur.active_area_cm2) == (rec.n_cells, rec.active_area_cm2):
        ss.device = rec
        return None
    suggestion = None
    if (rec.n_cells is None and cur.n_cells is not None) or (rec.active_area_cm2 is None and cur.active_area_cm2 is not None):
        suggestion = {"n_cells": cur.n_cells if rec.n_cells is None else None,
                      "active_area_cm2": cur.active_area_cm2 if rec.active_area_cm2 is None else None}
    rec.n_cells, rec.active_area_cm2 = cur.n_cells, cur.active_area_cm2
    rec.n_cells_origin, rec.active_area_origin = cur.n_cells_origin, cur.active_area_origin
    ss.device = rec
    return suggestion


def adopt_geometry(n_cells, area) -> None:
    did, _ = active()
    ws = persistence.workspace()
    changes = {}
    if n_cells is not None:
        changes["n_cells"] = n_cells
    if area is not None:
        changes["active_area_cm2"] = area
    if changes:
        ws.update_device(did, **changes, provenance=(ws.devices[did].provenance + " Geometría adoptada de los datos "
                                                    "importados (declarada por la fuente de datos).").strip())


def sync() -> None:
    """Vuelca al borrador lo que cambió en esta ejecución y registra calibraciones nuevas."""
    ss = _ss()
    did, rid = active()
    ws = persistence.workspace()
    if not did or rid not in ws.drafts or ws.drafts[rid].status != "abierto":
        return
    align_device()
    dr = ws.drafts[rid]
    fp = _fingerprint()
    if fp != ss.get("wb_fp"):
        dk = state.data_key() if ss.get("curves") is not None else ""
        cfg = fit_config_to_dict(ss.fit_config) if ss.get("fit_config") else None
        notes = dict(dr.stage_notes)
        if ss.get("device") is not None:
            notes["import_geometry"] = {"n_cells": ss.device.n_cells, "active_area_cm2": ss.device.active_area_cm2}
        try:
            ws.update_draft(rid, curves=[curve_to_dict(c) for c in ss.curves], dataset_label=ss.get("dataset_label", ""),
                            fit_config=cfg, data_key=dk, config_key=config_key(dk, cfg), stage_notes=notes)
            ws.set_draft_originals(rid, ss.get("originals") or {})
        except WorkspaceError as exc:
            st.toast(f"No se pudo actualizar el borrador: {exc}")
        ss.wb_fp = fp
    # calibración nueva → registro inmutable (una vez por huella de ajuste)
    res, fk = ss.get("fit_result"), ss.get("fit_key")
    # cada EJECUCIÓN del optimizador es una calibración nueva (también si repite datos y configuración)
    if res is not None and fk and id(res) != ss.get("wb_last_res_id") and state.result_is_current():
        ss.wb_last_res_id = id(res)
        curves = [c for c in ss.curves if c.curve_id in res.curve_ids]
        _register_dataset(ws, dr, ss.curves)
        prof = build_profile(res, curves, ss.device)
        dk = state.data_key()
        cal = ws.record_calibration(rid, prof, dk, config_key(dk, fit_config_to_dict(ss.fit_config)))
        ss.profile, ss.profile_key = prof, fk
        ss.wb_recorded = {**ss.get("wb_recorded", {}), fk: cal.id}
        st.toast(f"Calibración registrada: {cal.label} · {cal.status_code}")


def _register_dataset(ws, dr, curves) -> None:
    """Las curvas usadas en una calibración quedan registradas como conjunto de datos inmutable (sin duplicar)."""
    from workspace.model import canonical_sha256
    dicts = [curve_to_dict(c) for c in curves]
    origs = {n: hashlib.sha256(b).hexdigest() for n, b in (_ss().get("originals") or {}).items()}
    sha = canonical_sha256({"curves": dicts, "originals": origs})
    if any(d.content_sha256 == sha for d in ws.device_datasets(dr.device_id)):
        return
    kinds = {c.mapping.get("source_kind") or ("ejemplo" if "ejemplo" in (dr.dataset_label or "").lower() else "csv")
             for c in curves}
    ds = ws.add_dataset(dr.device_id, dr.dataset_label or f"Datos de {dr.title}",
                        "imagen" if "imagen_digitalizada" in kinds else sorted(kinds)[0], dicts,
                        _ss().get("originals") or {})
    if ds.id not in dr.dataset_ids:
        dr.dataset_ids = list(dr.dataset_ids) + [ds.id]


def current_calibration_id() -> str | None:
    fk = _ss().get("fit_key")
    return _ss().get("wb_recorded", {}).get(fk) if fk else None


def explicit_save() -> None:
    did, rid = active()
    if rid:
        sync()
        persistence.workspace().update_draft(rid, explicit=True)
