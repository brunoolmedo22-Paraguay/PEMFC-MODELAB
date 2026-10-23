"""PEMFC ModelLab — Hito 1: Motor de identificación paramétrica.

Ejecutar:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from pemfc_core.schemas import APP_VERSION  # noqa: E402
from ui import about_view, configure_view, export_view, fit_view, import_view, results_view, state  # noqa: E402

st.set_page_config(page_title="PEMFC ModelLab", page_icon="⚡", layout="wide")
state.init()

st.title("PEMFC ModelLab")
st.markdown("Identificación paramétrica de células de combustible PEM a partir de curvas de polarización medidas. "
            f"Motor 1 · v{APP_VERSION}")

tabs = st.tabs(["1. Importar curva", "2. Configurar identificación", "3. Calibrar", "4. Resultados",
                "5. Exportar perfil", "Alcance y límites"])
with tabs[0]:
    import_view.render()
with tabs[1]:
    configure_view.render()
with tabs[2]:
    fit_view.render()
with tabs[3]:
    results_view.render()
with tabs[4]:
    export_view.render()
with tabs[5]:
    about_view.render()
