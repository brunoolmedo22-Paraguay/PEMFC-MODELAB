"""Motor 2 — Simulación y análisis operacional (página PROVISIONAL).

Módulo deliberadamente aislado: cuando exista el Motor 2 real, basta con sustituir ``render()``. Nada de lo que se
muestra aquí está implementado todavía y así se indica.
"""
from __future__ import annotations

import streamlit as st

from . import shell

PLANNED = [
    ("Dispositivos identificados como entrada", "Usar los perfiles calibrados del Motor 1 (contrato de perfil) como "
     "modelo de cada stack."),
    ("Condiciones operativas", "Definir temperatura, presiones, composición del oxidante y demanda de corriente o potencia."),
    ("Estudio del comportamiento", "Curvas de operación, eficiencia y sensibilidad dentro del dominio identificado."),
]


def render() -> None:
    st.html("""<div class="m2-hero"><div class="m1-chip m2-chip"><span class="m1-dot"></span>MOTOR 2 · EN DESARROLLO</div>
      <h1>Motor 2 — Simulación y análisis operacional</h1>
      <p class="m2-lead">Estamos preparando el entorno de simulación de PEMFC ModelLab.</p>
      <p>Próximamente podrás incorporar dispositivos previamente identificados, definir condiciones operativas y estudiar
      su comportamiento mediante modelos computacionales.</p></div>""")
    items = "".join(f'<li><span class="m2-tag">Previsto</span><div><b>{t}</b><br><span>{d}</span></div></li>'
                     for t, d in PLANNED)
    st.html(f"""<div class="m2-plan"><div class="m2-plan-title">Objetivos previstos (no disponibles todavía)</div>
      <ul>{items}</ul><p class="m2-note">Ninguna de estas funciones está implementada en esta versión. Los perfiles que
      generes hoy en el Motor 1 siguen un contrato versionado pensado para alimentar el Motor 2 cuando exista.</p></div>""")
    c1, c2, _ = st.columns([1.3, 1.3, 3])
    if c1.button("← Volver a la página principal", key="m2_home", width="stretch"):
        shell.go("home")
        st.rerun()
    if c2.button("Ir al Motor 1", key="m2_m1", type="primary", width="stretch"):
        shell.go("catalog")
        st.rerun()
