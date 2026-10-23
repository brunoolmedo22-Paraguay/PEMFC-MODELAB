"""Pestaña: Alcance y límites científicos."""
from __future__ import annotations

import streamlit as st

from pemfc_core import model as core
from pemfc_core.schemas import APP_VERSION, STATUS_DESCRIPTIONS


def render() -> None:
    st.subheader("Qué hace esta versión")
    st.markdown(
        "PEMFC ModelLab identifica los parámetros de un modelo semiempírico de PEMFC a partir de **curvas de "
        "polarización medidas o digitalizadas**, y produce un perfil trazable y reutilizable. Es el Motor 1 "
        "(identificación paramétrica).")
    st.subheader("Qué no hace")
    st.markdown(
        "- **No crea perfiles a partir de un datasheet sin curva.** La referencia de datasheet es solo documental.\n"
        "- **No implementa el Motor 2** (demanda temporal, despacho, consumo de H₂, costes, BOP).\n"
        "- **No digitaliza imágenes** en esta versión: la curva debe llegar como puntos (CSV).\n"
        "- **No ajusta potencia ni eficiencia**, porque derivan de la misma tensión.\n"
        "- No representa transitorios, envejecimiento, gestión de agua ni condiciones no medidas.")
    st.subheader("Estados de un perfil")
    for code, text in STATUS_DESCRIPTIONS.items():
        st.markdown(f"- **{code}** — {text}")
    st.subheader("Modelo")
    st.markdown(f"`{core.MODEL_ID}` v{core.MODEL_VERSION} — {core.MODEL_LABEL}. Unidades internas: j [A/cm²], "
                "V por celda [V], T [K], presión absoluta de cátodo [atm].")
    for name, eq in core.MODEL_EQUATIONS.items():
        st.markdown(f"- *{name}*: `{eq}`")
    st.markdown(
        "Hipótesis heredadas y documentadas: el término de Nernst del código original no depende de la presión "
        "total (√P se cancela), así que el efecto de presión entra por ξ4·T·ln C_O2. t_m y D_H no afectan a la curva "
        "V–I. Cuando hay pocas condiciones distintas, solo un subconjunto de parámetros es identificable; los demás "
        "se fijan en valores de referencia OTEKON con origen ASUMIDO.")
    st.subheader("Procedencia y referencias")
    st.markdown(
        "- Modelo e identificador: [PEM-FC](https://github.com/brunoolmedo22-Paraguay/PEM-FC) (commit a533432), "
        "reconstrucción de Altıntaş & Ertan, OTEKON 2024.\n"
        "- Concepto de perfil y datos 65 kW: [EnergyMultimodelv1.5](https://github.com/brunoolmedo22-Paraguay/EnergyMultimodelv1.5) "
        "(commit 761f032); Chen, H. et al., CIESC Journal 75(2), 637–646, 2024, DOI 10.11949/0438-1157.20230745.\n"
        f"- PEMFC ModelLab v{APP_VERSION}. Detalles en `docs/AUDITORIA.md` y `docs/METODOLOGIA.md` del repositorio.")
