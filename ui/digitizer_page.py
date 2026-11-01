"""Digitalizador autónomo: de una figura científica a una tabla X–Y, sin Motor 1 ni perfil PEMFC."""
from __future__ import annotations

import streamlit as st

from . import digitizer_view


@st.fragment
def _body() -> None:
    digitizer_view.render_body("standalone")


def render() -> None:
    st.html("""<div class="pml-hero"><div class="pml-eyebrow">Herramienta autónoma</div>
      <h1>Digitalizador de figuras científicas</h1>
      <p>Cargue una figura (PNG, JPEG o WebP): se detectan localmente los paneles, los ejes, los números de las
      escalas y los trazos. Revise y corrija lo necesario y exporte los datos X–Y en CSV, XLSX, JSON, PNG o un ZIP
      científico completo. No requiere crear dispositivos ni ejecutar el Motor 1; nada sale de este servidor.</p></div>""")
    digitizer_view.use_context("standalone")
    flash = st.session_state.pop("dz_flash", None)
    if flash:
        getattr(st, flash[0])(flash[1])
    _body()
