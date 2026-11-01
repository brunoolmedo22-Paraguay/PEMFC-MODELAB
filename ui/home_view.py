"""Página principal de PEMFC ModelLab: presentación, selector de motores y cuatro secciones informativas."""
from __future__ import annotations

from dataclasses import fields

import pandas as pd
import streamlit as st

from pemfc_core import model as core
from pemfc_core.parameters import PARAMETER_INFO, ModelParameters

from . import shell

CARDS = [
    {"kind": "identify", "icon": "identify", "view": "catalog", "available": True, "eyebrow": "Motor 1",
     "title": "Identificación y calibración",
     "description": "Registra tus dispositivos PEMFC e identifica sus parámetros experimentales para incorporarlos a un "
                    "modelo digital calibrado.",
     "action": "Acceder al Motor 1"},
    {"kind": "simulate", "icon": "simulate", "view": "motor2", "available": True, "eyebrow": "Motor 2",
     "title": "Simulación y análisis operacional",
     "description": "Integra tus dispositivos registrados en un entorno de simulación para estudiar y visualizar su "
                    "comportamiento bajo diferentes condiciones operativas.",
     "action": "Acceder al Motor 2"},
]


def _on_engine() -> None:
    a = shell.payload("pml_engines")
    if a and a.get("type") == "open" and a.get("view") in ("catalog", "motor2"):
        shell.go(a["view"])


def render() -> None:
    st.html("""<div class="home-hero">
      <div class="home-mark" aria-hidden="true"><svg viewBox="0 0 48 48"><rect x="6" y="10" width="36" height="28" rx="6"
        fill="none" stroke="currentColor" stroke-width="2.6"/><path d="M15 10v28M21 10v28M27 10v28M33 10v28" stroke="currentColor"
        stroke-width="1.8" stroke-opacity=".6"/><path d="M24 4v6M24 38v6" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg></div>
      <h1>Bienvenido a PEMFC ModelLab</h1>
      <p>Una plataforma científica para la identificación, calibración y simulación de sistemas de celdas de combustible de
      membrana de intercambio protónico.</p>
      <div class="home-q">¿Qué deseas hacer hoy?</div></div>""")
    shell.component("engines")(key="pml_engines", data={"cards": CARDS}, on_action_change=_on_engine)
    st.write("")
    t1, t2, t3, t4 = st.tabs(["Acerca de ModelLab", "Motor 1", "Motor 2", "Modelo implementado"])
    with t1:
        _about()
    with t2:
        _motor1()
    with t3:
        _motor2()
    with t4:
        _model()


def _about() -> None:
    st.markdown("""
**PEMFC ModelLab** convierte mediciones de celdas y stacks PEMFC en **modelos electroquímicos calibrados, reproducibles y
auditables**, y permite experimentar computacionalmente con ellos.

- **Motor 1 — Identificación y calibración.** Registra dispositivos, incorpora curvas V–I (CSV o digitalizadas), identifica
  los parámetros del modelo por mínimos cuadrados y produce **perfiles calibrados** versionados (JSON) con su dominio de
  validez, su estado y la reproducción de sus curvas.
- **Motor 2 — Laboratorio virtual.** Usa esos perfiles **sin modificar el modelo**: reproduce los experimentos de calibración,
  simula seguimiento de carga, estudia la alimentación de hidrógeno y busca puntos de operación óptimos, con hipótesis,
  alertas y exportación.
- **Modelo electroquímico.** V_celda = E_Nernst − V_act − V_óhm − V_conc (detalle completo en «Modelo implementado»).
- **Parámetros identificados experimentalmente.** Los marcados como libres en la configuración (p. ej. ξ₁–ξ₄, resistencia de
  membrana y su dependencia térmica, coeficientes de concentración); los demás son fijados o asumidos y su origen se declara.
- **Variables calculadas directamente por el modelo:** tensión de celda y de stack, corriente (I = j·A), potencia
  (P = N·V·I), pérdidas por activación, óhmicas y de concentración.
- **Resultados que dependen de hipótesis adicionales:** consumo de H₂ (faradaico, N·I/2F: sin purgas ni fugas), eficiencia
  (respecto al PCI/PCS elegido, sin auxiliares), utilización de combustible (requiere el caudal alimentado y una política),
  límites de rampa, corriente o potencia (solo si el usuario los documenta).
- **Simulación cuasiestacionaria.** Cada instante de un perfil temporal se evalúa con la curva de polarización estacionaria:
  la respuesta se ajusta instantáneamente a la demanda dentro de la capacidad disponible. No es una simulación dinámica.
- **Fenómenos no representados.** Transitorios electroquímicos (doble capa), dinámica de gases y de presión, térmica,
  gestión de agua e hidratación de membrana, degradación, auxiliares (compresor, humidificador, refrigeración), electrónica
  de potencia y balance de planta.
- **Calibración frente a validación.** Reproducir las curvas usadas en el ajuste mide la calidad del ajuste, no la capacidad
  predictiva. Solo curvas no usadas en el ajuste (rol «validación») permiten una validación independiente.
- **Extrapolación.** Fuera del dominio calibrado (corriente, temperatura, presión) el modelo se evalúa por extrapolación: los
  resultados se marcan como tales y deben interpretarse con cautela, sin atribuirles validez experimental.
- **Trazabilidad y honestidad.** Calibraciones y experimentos son inmutables y sellados (SHA‑256); nada se inventa (geometría,
  unidades, valores de ejes, incertidumbres, límites operacionales). Si falta información, la aplicación lo indica.
""")


def _motor1() -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
#### Disponible en esta versión
- **Gestión de dispositivos PEMFC**: catálogo, metadatos, exportación, importación y eliminación.
- **Datos experimentales**: CSV o datos pegados (unidades y geometría explícitas), ejemplos documentados.
- **Digitalización de curvas**: detección de ejes, números (OCR local verificado geométricamente), unidades y trazos;
  edición manual completa; también como herramienta autónoma con exportación X–Y.
- **Identificación paramétrica**: mínimos cuadrados multi‑inicio con límites, presets y diagnóstico de identificabilidad.
- **Calibración y análisis**: residuos, métricas, validación con curvas independientes, historial y comparación.
- **Exportación** de perfiles (`profile.json`) y del experimento completo (ZIP).
""")
    with c2:
        st.markdown("""
#### No incluido (fuera del alcance actual)
- Modelos dinámicos o transitorios, gestión de agua e hidratación de membrana.
- Identificación a partir de espectroscopía de impedancia u otras técnicas distintas de la curva V–I.
- Sincronización en la nube entre equipos (los datos se guardan en el navegador y se exportan como paquetes).
""")
    if st.button("Acceder al Motor 1 →", key="home_go_m1", type="primary"):
        shell.go("catalog")
        st.rerun()


def _motor2() -> None:
    st.markdown("""
El **Motor 2 — Laboratorio Virtual** somete un dispositivo calibrado a experimentos computacionales con el modelo y los
parámetros de su perfil (sin ecuaciones nuevas). Disponible en esta versión:

- **01 Reproducción experimental:** curvas V–I y P–I, residuos, RMSE, MAE, sesgo y error máximo, idénticos al Motor 1;
  distingue reproducción de calibración y validación independiente.
- **02 Seguimiento de carga:** perfil temporal (generadores, tabla, CSV/Excel o imagen digitalizada); potencia demandada,
  disponible, entregada, déficit y margen; tensión, corriente, H₂ y eficiencia; eventos y restricciones (rampa solo si se
  documenta); modos ideal y restringido.
- **03 Alimentación de hidrógeno:** caudal como entrada y política de operación (corriente, potencia, utilización o máxima
  potencia con u_máx); H₂ alimentado frente a consumido y operación limitada por combustible.
- **04 Optimización operacional:** máxima potencia, máxima eficiencia, mínimo consumo específico, potencia objetivo y frontera
  de Pareto, siempre dentro del dominio admisible.
- **Estudio completo, historial, duplicación, comparación** y exportación (CSV, Excel, JSON, PNG/SVG, PDF y ZIP).

**Previsto:** sensibilidad y comparación de escenarios; mapa operacional.
""")
    if st.button("Acceder al Motor 2 →", key="home_go_m2", type="primary"):
        shell.go("motor2")
        st.rerun()


def _model() -> None:
    st.markdown(f"""
**{core.MODEL_LABEL}** · identificador `{core.MODEL_ID}` v{core.MODEL_VERSION}.

Modelo **semiempírico, estacionario y de parámetros concentrados** (0‑D) de la tensión de una celda. La implementación
(`pemfc_core/model.py`) reproduce, ecuación por ecuación, el modelo reconstruido de Altıntaş & Ertan (OTEKON 2024) y su
equivalencia numérica se verifica en las pruebas contra curvas de referencia. Unidades: j en A/cm², tensiones en V por
celda, T en K y presiones en atm absolutas.
""")
    st.markdown("##### 1. Tensión de la celda")
    st.latex(r"V_{cell}=\max\left(E_{Nernst}-V_{act}-V_{ohm}-V_{conc},\;0\right)")
    st.markdown("##### 2. Tensión reversible (Nernst)")
    st.latex(r"E_{Nernst}=E_0-0.85\times10^{-3}\,(T-T_{ref})+\frac{RT}{2F}\,"
             r"\ln\!\left[\frac{p_{H_2}\,\sqrt{y_{O_2}P}}{p_{H_2O}\,\sqrt{P}}\right]")
    st.caption("P: presión absoluta del cátodo; y_O2: fracción molar de O₂ del oxidante; p_H2 e y_O2 pueden declararse por "
               "curva (si no, se usan los valores globales); p_H2O es una hipótesis fija del modelo de referencia.")
    st.markdown("##### 3. Pérdidas por activación")
    st.latex(r"C_{O_2}=\frac{y_{O_2}P}{5.08\times10^{6}\,\exp(-498/T)}")
    st.latex(r"V_{act}=\max\!\Big(-\big[\xi_1+\xi_2T+\xi_3T\,\ln(1000\,\max(j,\,j_{floor}))+\xi_4T\,\ln C_{O_2}\big],\;0\Big)")
    st.caption("Forma semiempírica con coeficientes ξ₁–ξ₄ (corriente en mA/cm² dentro del logaritmo). j_floor evita el "
               "logaritmo de valores nulos; el recorte max(·,0) se señala en el diagnóstico porque anula el gradiente.")
    st.markdown("##### 4. Pérdidas óhmicas")
    st.latex(r"V_{ohm}=j\,R_{mem}(T),\qquad R_{mem}(T)=R_{mem,ref}\left(\frac{T}{T_{ref}}\right)^{n_R}")
    st.caption("Se implementa mediante la cadena σ = F²·D_H·C_H(T)/(R·T) con C_H(T) = C_H,ref·(T/T_ref)^(1−n_R); t_m y D_H se "
               "cancelan, por lo que no afectan a la curva V–I en esta parametrización.")
    st.markdown("##### 5. Pérdidas por concentración")
    st.latex(r"V_{conc}=\max\!\big(a_{ref}+a_T\,(T-T_{ref}),\;0\big)\,\exp(b\,j)")
    st.markdown("##### 6. Magnitudes de stack")
    st.latex(r"V_{stack}=N_{cells}\,V_{cell},\qquad I=j\,A_{active},\qquad P=V_{stack}\,I")
    st.markdown("##### Parámetros (generado desde el código)")
    defaults = {f.name: getattr(ModelParameters(), f.name) for f in fields(ModelParameters)}
    rows = [{"parámetro": i.name, "símbolo": i.symbol, "unidad": i.unit, "grupo": i.category,
             "identificable": "sí" if i.fittable else "no", "valor por defecto": defaults.get(i.name),
             "origen": i.reference_origin, "descripción": i.description} for i in PARAMETER_INFO.values()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown("""
##### Variables operativas
Densidad de corriente *j*, temperatura de la celda *T*, presión absoluta del cátodo *P* y, opcionalmente por curva,
presión parcial de hidrógeno *p<sub>H2</sub>* y fracción de oxígeno *y<sub>O2</sub>*. En un stack, *N<sub>cells</sub>* y
*A<sub>active</sub>* solo convierten entre magnitudes de celda y de stack; nunca se infieren.

##### Hipótesis y limitaciones
- Régimen **estacionario** e isotermo por curva; modelo 0‑D sin distribución espacial.
- Sin gestión de agua ni dinámica de hidratación de la membrana (p<sub>H2O</sub> fija); sin cruce de gases ni degradación.
- Los términos son **semiempíricos**: sus parámetros describen el dispositivo en el dominio medido; extrapolar fuera del
  rango de T, P y j identificado no está validado.
- Identificabilidad: ξ₂, n<sub>R</sub> y a<sub>T</sub> requieren curvas a ≥ 2 temperaturas; ξ₄, a ≥ 2 presiones de O₂. Con
  menos información, la aplicación lo advierte y recomienda fijarlos.
- El recorte max(·, 0) hace la función no suave en sus bordes; el identificador lo detecta y lo informa.

##### Referencias
- N. Altıntaş, R. Ertan, OTEKON 2024 — estructura del modelo reconstruida en el repositorio PEM‑FC (commit a533432), base
  de esta implementación.
- J. C. Amphlett *et al.*, «Performance modeling of the Ballard Mark IV solid polymer electrolyte fuel cell I»,
  *J. Electrochem. Soc.* 142 (1995) 1–8 — forma semiempírica de la sobretensión de activación (coeficientes ξ).
- R. F. Mann *et al.*, «Development and application of a generalised steady-state electrochemical model for a PEM fuel
  cell», *J. Power Sources* 86 (2000) 173–180 — modelo generalizado y concentración de O₂ en la interfaz
  (5.08·10⁶·exp(−498/T)).
- J. Kim *et al.*, «Modeling of proton exchange membrane fuel cell performance with an empirical equation»,
  *J. Electrochem. Soc.* 142 (1995) 2670–2674 — término exponencial de pérdidas por concentración.
- H. Chen *et al.*, *CIESC Journal* 75(2) (2024) 637–646, DOI 10.11949/0438‑1157.20230745 — datos del ejemplo de stack
  incluido.

Las tres referencias clásicas se citan como **origen de la forma funcional**; la implementación sigue la reconstrucción
OTEKON tal como se describe arriba.
""", unsafe_allow_html=True)


HOME_CSS = """
<style>
.home-hero { text-align: center; max-width: 860px; margin: 1.2rem auto 1.4rem auto; }
.home-mark { width: 62px; height: 62px; margin: 0 auto .7rem auto; border-radius: 18px; display: grid; place-items: center;
  color: var(--primary-color, #0E7C86); background: color-mix(in srgb, var(--primary-color, #0E7C86) 11%, transparent); }
.home-mark svg { width: 40px; height: 40px; }
.home-hero h1 { font-size: clamp(1.9rem, 1.3rem + 2.4vw, 2.9rem); line-height: 1.08; letter-spacing: -.028em; margin: 0 0 .7rem 0; }
.home-hero p { font-size: 1.08rem; line-height: 1.6; opacity: .78; margin: 0 auto; max-width: 720px; }
.home-q { margin-top: 2rem; font-size: .8rem; font-weight: 750; letter-spacing: .16em; text-transform: uppercase;
  color: var(--primary-color, #0E7C86); }
.m2-hero { max-width: 880px; margin: .8rem 0 1rem 0; padding: 1.3rem 1.5rem; border-radius: 16px; position: relative; overflow: hidden;
  border: 1px solid rgba(47,111,237,.28); background: linear-gradient(120deg, rgba(47,111,237,.09), transparent 65%); }
.m2-hero::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: #2F6FED; }
.m2-chip { color: #2F6FED !important; }
.m2-hero h1 { font-size: clamp(1.5rem, 1.1rem + 1.5vw, 2.1rem); margin: .4rem 0 .5rem 0; letter-spacing: -.02em; }
.m2-hero p { margin: .2rem 0; opacity: .82; line-height: 1.55; } .m2-lead { font-weight: 650; opacity: 1 !important; }
.m2-plan { max-width: 880px; padding: 1rem 1.3rem; border-radius: 14px; border: 1px dashed rgba(128,128,128,.4); margin-bottom: 1rem; }
.m2-plan-title { font-weight: 700; margin-bottom: .5rem; }
.m2-plan ul { list-style: none; padding: 0; margin: 0; display: grid; gap: .6rem; }
.m2-plan li { display: flex; gap: .8rem; align-items: flex-start; line-height: 1.45; } .m2-plan li span { opacity: .78; }
.m2-tag { flex: none; font-size: .7rem; font-weight: 750; padding: .15rem .5rem; border-radius: 999px; color: #a35c00 !important;
  background: rgba(214,137,16,.15); opacity: 1 !important; margin-top: .1rem; }
.m2-note { font-size: .85rem; opacity: .7; margin: .8rem 0 0 0; }
</style>
"""
