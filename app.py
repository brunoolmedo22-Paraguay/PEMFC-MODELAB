"""PEMFC ModelLab v0.3.0 — Gestión de dispositivos e identificación (Motor 1) + digitalizador.

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui import about_view, catalog_view, device_view, persistence, shell, state  # noqa: E402

st.set_page_config(page_title="PEMFC ModelLab", page_icon="⚡", layout="wide")
state.init()
persistence.init()
shell.global_css()
shell.topbar()

route = shell.route()
if route["view"] == "device":
    device_view.render()
elif route["view"] == "digitizer":
    from ui import digitizer_page  # noqa: E402
    digitizer_page.render()
elif route["view"] == "about":
    about_view.render()
else:
    catalog_view.render()

# Al final de cada ejecución: envía al navegador los registros modificados (autoguardado).
persistence.render_bridge()
