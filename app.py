"""PEMFC ModelLab v0.3.1 — Gestión de dispositivos e identificación (Motor 1) + digitalizador.

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from ui import about_view, catalog_view, device_view, home_view, motor2_view, persistence, shell, state  # noqa: E402

st.set_page_config(page_title="PEMFC ModelLab", page_icon="⚡", layout="wide")
from digitizer import ocr as _ocr  # noqa: E402
_ocr.warmup_async()          # el modelo OCR se carga en segundo plano: la primera imagen no lo espera
state.init()
persistence.init()
shell.global_css()
shell.topbar()

route = shell.route()
st.html(home_view.HOME_CSS)
if route["view"] == "home":
    home_view.render()
elif route["view"] == "motor2":
    motor2_view.render()
elif route["view"] == "device":
    device_view.render()
elif route["view"] == "digitizer":
    from ui import digitizer_page  # noqa: E402
    digitizer_page.render()
elif route["view"] == "about":
    about_view.render()
elif route["view"] == "catalog":
    catalog_view.render()
else:
    home_view.render()

# Al final de cada ejecución: envía al navegador los registros modificados (autoguardado).
persistence.render_bridge()
