"""Estado de sesión compartido entre pestañas (sin persistencia en servidor)."""
from __future__ import annotations

import hashlib
import json

import streamlit as st

from identification.datasets import ValidationIssue
from pemfc_core.schemas import DeviceInfo

DEFAULTS = {
    "device": None,          # DeviceInfo usada para normalizar las curvas actuales
    "curves": [],            # list[PolarizationCurve]
    "originals": {},         # nombre de archivo -> bytes originales
    "dataset_label": "",
    "fit_config": None,      # FitConfig
    "fit_result": None,      # FitResult
    "fit_key": None,         # huella de datos+configuración del resultado
    "profile": None,         # dict
    "profile_key": None,
}


WIDGET_DEFAULTS = {
    "dev_name": "", "dev_manufacturer": "", "dev_model": "", "dev_n_known": False, "dev_n": 1,
    "dev_n_origin": "MEDIDO", "dev_a_known": False, "dev_a": 1.0, "dev_a_unit": "cm²", "dev_a_origin": "MEDIDO",
    "dev_datasheet": "", "dev_notes": "",
}


def init() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v.copy() if isinstance(v, (dict, list)) else v
    if st.session_state.device is None:
        st.session_state.device = DeviceInfo()
    for key, value in WIDGET_DEFAULTS.items():
        st.session_state.setdefault(key, value)


def set_dataset(curves, device: DeviceInfo, originals: dict[str, bytes], label: str) -> None:
    st.session_state.curves = list(curves)
    st.session_state.device = device
    st.session_state.originals = dict(originals)
    st.session_state.dataset_label = label
    st.session_state.fit_config = None
    clear_results()


def clear_results() -> None:
    st.session_state.fit_result = None
    st.session_state.fit_key = None
    st.session_state.profile = None
    st.session_state.profile_key = None


def data_key() -> str:
    dev = st.session_state.device
    payload = {
        "curves": [(c.curve_id, c.meta.role, c.meta.quality, c.meta.sigma_V, c.normalized_sha256,
                    c.conditions.to_dict()) for c in st.session_state.curves],
        "device": (dev.n_cells, dev.active_area_cm2) if dev else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def fit_key(config) -> str:
    cfg = json.dumps(config.to_dict(), sort_keys=True, default=str) if config else ""
    return hashlib.sha256((data_key() + cfg).encode()).hexdigest()


def result_is_current() -> bool:
    r = st.session_state.fit_result
    return r is not None and st.session_state.fit_key == fit_key(st.session_state.fit_config)


def show_issues(issues: list[ValidationIssue]) -> bool:
    """Muestra errores y avisos. Devuelve True si hay errores."""
    errors = [str(i) for i in issues if i.level == "error"]
    warns = [str(i) for i in issues if i.level != "error"]
    if errors:
        st.error("**No se puede continuar:**\n\n" + "\n".join(f"- {e}" for e in errors))
    if warns:
        st.warning("**Avisos:**\n\n" + "\n".join(f"- {w}" for w in warns))
    return bool(errors)
