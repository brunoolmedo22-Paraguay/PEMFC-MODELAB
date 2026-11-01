"""Motor 2 — Laboratorio Virtual: bancadas experimentales sobre perfiles calibrados del Motor 1."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from simulation import runner
from simulation import timeseries as tsm
from simulation.benches import BENCHES, OBJECTIVES, POLICIES, BenchResult
from simulation.stack import FLOW_UNITS, SimulationError

from . import persistence, shell

CSS = (Path(__file__).parent / "static" / "motor2.css").read_text(encoding="utf-8")
TEAL, ORANGE, RED, BLUE, VIOLET, GREEN, GREY = "#0f8b8d", "#e0891e", "#d1495b", "#2f6fed", "#7a4fd1", "#3c9d5d", "#7a8796"
ICON = {
    "reproduccion": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 20h18M4 19V5"/><circle cx="7" cy="9" r="1.3"/><circle cx="11" cy="11" r="1.3"/><circle cx="15" cy="13" r="1.3"/><circle cx="19" cy="17" r="1.3"/><path d="M5 7.5c4 3 9 5.5 15 10"/></svg>',
    "carga": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 20h18M4 19V5"/><path d="M5 15h3v-5h4v7h3V8h4"/></svg>',
    "hidrogeno": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3c3.5 4.2 6 7.4 6 10.5A6 6 0 0 1 6 13.5C6 10.4 8.5 7.2 12 3z"/><path d="M10 11v5M14 11v5M10 13.5h4"/></svg>',
    "optimizacion": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 20h18M4 19V5"/><path d="M5 18c3-9 6-12 8-12s4 4 6 9"/><circle cx="13" cy="6" r="1.8"/></svg>',
    "sensibilidad": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="7" cy="18" r="2"/></svg>',
    "mapa": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M4 14c4-1 6-6 16-7M4 18c5-1 8-5 16-5"/></svg>',
}
CARDS = [("reproduccion", "01", TEAL, "Reproducción experimental", "Recalcula con el modelo identificado el experimento de "
          "calibración: curvas V–I y P–I, residuos y métricas, distinguiendo calibración de validación independiente."),
         ("carga", "02", BLUE, "Seguimiento de carga", "Somete el stack a un perfil temporal de demanda: potencia entregada, "
          "déficit, margen, tensión, corriente, H₂ y eficiencia, con restricciones y eventos."),
         ("hidrogeno", "03", GREEN, "Alimentación de hidrógeno", "El caudal de H₂ es la entrada: política de operación, "
          "utilización, energía producida y operación limitada por combustible."),
         ("optimizacion", "04", ORANGE, "Optimización operacional", "Busca puntos de operación admisibles: máxima potencia, "
          "máxima eficiencia, mínimo consumo específico, potencia objetivo y frontera de compromiso."),
         ("sensibilidad", "05", VIOLET, "Sensibilidad y comparación de escenarios", "Variación sistemática de condiciones y "
          "parámetros con comparación de escenarios."),
         ("mapa", "06", RED, "Mapa operacional", "Mapas de potencia, eficiencia y consumo en función de las condiciones de "
          "operación.")]
FUTURE = {"sensibilidad", "mapa"}
SCOPE = {
    "general": ["Simulación CUASIESTACIONARIA: cada instante se evalúa con la curva de polarización estacionaria identificada "
                "en el Motor 1 (mismas ecuaciones y parámetros; no hay ecuaciones nuevas).",
                "No representa transitorios electroquímicos, dinámica de gases, térmica ni de humidificación, degradación, "
                "auxiliares (BoP) ni electrónica de potencia.",
                "Fuera del dominio calibrado (corriente, temperatura, presión) los resultados son extrapolaciones y se marcan.",
                "Consumo de H₂ teórico (faradaico) N·I/(2F); eficiencia del stack referida al poder calorífico indicado.",
                "Un ajuste a datos de calibración no es una validación independiente."],
    "reproduccion": ["Evalúa el perfil sobre los mismos puntos experimentales normalizados que usó el Motor 1.",
                     "Las métricas deben coincidir exactamente con las almacenadas en el perfil (se comprueba)."],
    "carga": ["La potencia entregada nunca supera la potencia estacionaria disponible: el exceso se registra como déficit.",
              "Para cada potencia se usa la menor corriente que la entrega (rama de mayor eficiencia).",
              "Sin rampas documentadas no se evalúa la capacidad dinámica (no significa que sea ilimitada).",
              "Modo ideal: solo la capacidad del modelo. Modo restringido: además, límites documentados por el usuario."],
    "hidrogeno": ["El caudal alimentado no determina por sí solo el punto de operación: la política lo cierra.",
                  "No se supone que todo el H₂ alimentado reacciona: utilización = consumido / alimentado ≤ u_máx.",
                  "El caudal solo limita la corriente por conservación de masa; no se modelan presión ni estequiometría del ánodo."],
    "optimizacion": ["Solo se consideran puntos del dominio admisible (dominio calibrado y límites documentados).",
                     "Maximizar η equivale a minimizar el consumo específico (ambos dependen solo de V_celda).",
                     "Sin potencia mínima útil, el óptimo de eficiencia es trivial (mínima corriente) y se advierte."]}


def _ss():
    return st.session_state


def _m2() -> dict:
    ss = _ss()
    if "m2" not in ss:
        ss.m2 = {"device": None, "cal": None, "tab": "Bancadas", "bench": None}
    return ss.m2


def _cfgs() -> dict:
    return _ss().setdefault("m2_cfg", {})


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sec(text: str) -> None:
    st.html(f'<div class="m2x"><div class="m2x-sec">{_esc(text)}</div></div>')


# ===================================================================================================== selección
def usable_calibrations(ws, did: str) -> list:
    out = []
    for c in ws.device_calibrations(did):
        st_ = (c.profile or {}).get("status", {})
        dev = (c.profile or {}).get("device", {})
        if st_.get("usable_for_simulation") and dev.get("n_cells") and dev.get("active_area_cm2"):
            out.append(c)
    return out


def _hero() -> None:
    st.html(f"<style>{CSS}</style>" + """<div class="m2x"><div class="m2x-hero"><div>
      <span class="m2x-chip"><i></i>MOTOR 2 · LABORATORIO VIRTUAL</span>
      <h1>Motor 2 — Laboratorio Virtual</h1>
      <p>Bancada experimental computacional: somete un dispositivo PEMFC calibrado en el Motor 1 a experimentos de
      reproducción, seguimiento de carga, alimentación de hidrógeno y optimización operacional, con el mismo modelo
      científico, hipótesis explícitas, alertas trazables y resultados exportables.</p></div>
      <svg class="m2x-art" viewBox="0 0 200 120" fill="none" stroke="currentColor" stroke-width="1.6">
        <rect x="6" y="18" width="70" height="84" rx="8" stroke-opacity=".55"/><path d="M18 34h46M18 48h46M18 62h46M18 76h46M18 90h46" stroke-opacity=".35"/>
        <path d="M76 60h22" stroke="#0E7C86" stroke-width="2.4"/><circle cx="104" cy="60" r="6" stroke="#0E7C86" stroke-width="2.2"/>
        <path d="M118 96V24M118 96h76" stroke-opacity=".55"/><path d="M122 40c14 2 26 10 34 22s18 22 34 26" stroke="#0E7C86" stroke-width="2.4"/>
        <path d="M122 84h10v-16h12v10h12V56h12v14h14" stroke="#e0891e" stroke-width="1.8" stroke-dasharray="3 3"/></svg>
      </div></div>""")


def _selector(ws):
    m = _m2()
    devs = {d.id: d for d in ws.devices.values() if usable_calibrations(ws, d.id)}
    if not devs:
        st.info("Todavía no hay dispositivos con un perfil calibrado utilizable para simulación (con N_celdas y área "
                "activa declarados). Registre un dispositivo e identifique sus parámetros en el Motor 1.")
        if st.button("Ir al Motor 1", type="primary", key="m2_go_m1"):
            shell.go("catalog")
            st.rerun()
        return None, None
    if m["device"] not in devs:
        m["device"] = sorted(devs.values(), key=lambda d: d.updated_utc, reverse=True)[0].id
    c1, c2, c3 = st.columns([1.2, 1.6, 0.7])
    did = c1.selectbox("Dispositivo registrado", list(devs), index=list(devs).index(m["device"]),
                       format_func=lambda i: devs[i].name, key="m2_dev_sel")
    if did != m["device"]:
        m.update(device=did, cal=None, bench=None)
    dev = devs[did]
    cals = usable_calibrations(ws, did)
    ids = [c.id for c in cals]
    if m["cal"] not in ids:
        m["cal"] = dev.active_calibration_id if dev.active_calibration_id in ids else ids[0]
    lab = {c.id: f"{c.label} · {c.profile_id} · {c.status_code}" + (" · ★ activo" if c.id == dev.active_calibration_id else "")
           for c in cals}
    cid = c2.selectbox("Perfil calibrado", ids, index=ids.index(m["cal"]), format_func=lab.get, key=f"m2_cal_sel_{did}")
    if cid != m["cal"]:
        m["cal"] = cid
    c3.write("")
    if c3.button("Catálogo ↗", key="m2_to_cat", width="stretch", help="Volver al catálogo de dispositivos del Motor 1."):
        shell.go("catalog")
        st.rerun()
    return dev, ws.calibrations[cid]


def _profile_card(dev, cal) -> None:
    p = cal.profile
    stc = p["status"]
    dom = p["domain"]["calibration"]
    m = (p.get("fit") or {}).get("metrics_calibration") or {}
    d = p["device"]
    cls = "m2x-ok" if stc["code"].startswith("VALIDADO") else "m2x-info"
    conds = "; ".join(f"{c['temperature_K']:g} K · {c['cathode_pressure_atm']:g} atm" for c in dom.get("conditions", []))
    st.html(f"""<div class="m2x"><div class="m2x-prof">
      <span class="m2x-badge {cls}">{stc['code']}</span>
      <span style="margin-left:.6rem;font-size:.86rem;opacity:.8">capacidad predictiva: <b>{stc.get('predictive_capability', '—')}</b></span>
      <div class="row">
        <div><span class="k">Dispositivo</span><b>{_esc(dev.name)}</b></div>
        <div><span class="k">N celdas</span><b>{d['n_cells']}</b> <small>({d.get('n_cells_origin')})</small></div>
        <div><span class="k">Área activa</span><b>{d['active_area_cm2']:g} cm²</b> <small>({d.get('active_area_origin')})</small></div>
        <div><span class="k">Dominio j calibrado</span><b>{dom['j_A_cm2'][0]:.3g}–{dom['j_A_cm2'][1]:.3g} A/cm²</b></div>
        <div><span class="k">RMSE de calibración</span><b>{1000 * m.get('rmse_V', float('nan')):.2f} mV/celda</b></div>
        <div><span class="k">Perfil</span><b>{p['profile_id']}</b></div>
      </div><div class="row"><div><span class="k">Condiciones calibradas</span>{_esc(conds)}</div></div></div></div>""")


# ===================================================================================================== página
def render() -> None:
    _hero()
    ws = persistence.workspace()
    if not _ss().get("ws_loaded") and not ws.devices:
        st.caption("Cargando el espacio de trabajo guardado en este navegador…")
    dev, cal = _selector(ws)
    if dev is None:
        with st.expander("Alcance científico y limitaciones"):
            _scope_tab()
        return
    _profile_card(dev, cal)
    m = _m2()
    if m.get("bench"):
        _bench_page(m["bench"], ws, dev, cal)
        return
    tabs = ["Bancadas", "Estudio completo", "Historial", "Exportaciones e informes", "Alcance y limitaciones"]
    tab = st.segmented_control("Sección", tabs, default=m.get("tab") or "Bancadas", key="m2_tab_sel",
                               label_visibility="collapsed")
    m["tab"] = tab or "Bancadas"
    if m["tab"] == "Bancadas":
        _bench_grid()
    elif m["tab"] == "Estudio completo":
        _study_tab(ws, dev, cal)
    elif m["tab"] == "Historial":
        _history_tab(ws, dev)
    elif m["tab"] == "Exportaciones e informes":
        _exports_tab(ws, dev)
    else:
        _scope_tab()


def _bench_grid() -> None:
    for row in (CARDS[:3], CARDS[3:]):
        cols = st.columns(3)
        for col, (key, num, color, title, desc) in zip(cols, row):
            with col:
                fut = key in FUTURE
                st.html(f"""<div class="m2x"><div class="m2x-card{' future' if fut else ''}" style="--c:{color}">
                  {'<span class="m2x-soon">PRÓXIMAMENTE</span>' if fut else ''}<div class="num">BANCADA {num}</div>
                  <h3>{ICON[key]}{title}</h3><p>{desc}</p></div></div>""")
                if fut:
                    st.button("Funcionalidad futura", key=f"m2_open_{key}", disabled=True, width="stretch",
                              help="Prevista para una versión posterior: no se simula ninguna ejecución.")
                elif st.button("Abrir bancada", key=f"m2_open_{key}", type="primary", width="stretch"):
                    _m2()["bench"] = key
                    st.rerun()


# ===================================================================================================== entradas comunes
def _cond_ui(profile: dict, key: str, prefill: dict | None) -> tuple[dict, dict, str]:
    ss = _ss()
    dom = profile["domain"]["calibration"]
    conds = dom.get("conditions") or []
    labels = [f"T = {c['temperature_K']:g} K · P = {c['cathode_pressure_atm']:g} atm (calibrada)" for c in conds]
    labels.append("Otras condiciones (interpolación/extrapolación)")
    pf = (prefill or {}).get("cond") or {}
    if pf and not ss.get(f"{key}_pf_done"):
        idx = next((i for i, c in enumerate(conds) if abs(c["temperature_K"] - (pf.get("temperature_K") or -1)) < 1e-9
                    and abs(c["cathode_pressure_atm"] - (pf.get("cathode_pressure_atm") or -1)) < 1e-9), len(conds))
        ss[f"{key}_cond"] = labels[idx]
        ss[f"{key}_T"], ss[f"{key}_P"] = pf.get("temperature_K"), pf.get("cathode_pressure_atm")
        if pf.get("j_max_extrapolated"):
            ss[f"{key}_ext"], ss[f"{key}_jext"] = True, pf["j_max_extrapolated"]
        ss[f"{key}_basis"] = prefill.get("basis", "LHV")
        for k, v in (prefill.get("limits") or {}).items():
            ss[f"{key}_{k}" if k != "source" else f"{key}_lsrc"] = v if k != "source" else (v or "")
        ss[f"{key}_pf_done"] = True
    _sec("Condiciones de operación")
    sel = st.selectbox("Condiciones", labels, key=f"{key}_cond", label_visibility="collapsed")
    i = labels.index(sel)
    if i < len(conds):
        cond = {"temperature_K": conds[i]["temperature_K"], "cathode_pressure_atm": conds[i]["cathode_pressure_atm"]}
    else:
        c1, c2 = st.columns(2)
        t = c1.number_input("Temperatura [K]", min_value=200.0, max_value=500.0, value=None, key=f"{key}_T", format="%.2f")
        p = c2.number_input("Presión de cátodo [atm abs]", min_value=0.05, max_value=20.0, value=None, key=f"{key}_P")
        st.caption(f"Rango calibrado: T {dom['temperature_K'][0]:g}–{dom['temperature_K'][1]:g} K, P "
                   f"{dom['cathode_pressure_atm'][0]:g}–{dom['cathode_pressure_atm'][1]:g} atm. Fuera de él se marca EXTRAPOLACIÓN.")
        cond = {"temperature_K": t, "cathode_pressure_atm": p}
    c1, c2 = st.columns([1.4, 1])
    ext = c1.checkbox(f"Permitir extrapolación en corriente (dominio calibrado hasta {dom['j_A_cm2'][1]:.3g} A/cm²)",
                      key=f"{key}_ext")
    if ext:
        cond["j_max_extrapolated"] = c2.number_input("j máxima extrapolada [A/cm²]", min_value=float(dom["j_A_cm2"][1]),
                                                     value=float(dom["j_A_cm2"][1]) * 1.2, key=f"{key}_jext")
    basis = st.radio("Poder calorífico para la eficiencia", ["LHV", "HHV"], horizontal=True, key=f"{key}_basis",
                     help="LHV (agua vapor, 241,83 kJ/mol) o HHV (agua líquida, 285,83 kJ/mol). η = V_celda/(PC/2F).")
    with st.expander("Límites operacionales documentados (opcionales)"):
        st.caption("Solo límites con respaldo (datasheet, ensayo, criterio de diseño). Vacío = no evaluado, NO ilimitado.")
        c = st.columns(3)
        vals = {}
        for col, (k, label) in zip(c * 2, [("current_max_A", "Corriente máxima [A]"), ("power_max_W", "Potencia máxima [W]"),
                                           ("v_cell_min_V", "Tensión mínima de celda [V]"), ("ramp_up_W_s", "Rampa de subida [W/s]"),
                                           ("ramp_down_W_s", "Rampa de bajada [W/s]")]):
            vals[k] = col.number_input(label, min_value=0.0, value=None, key=f"{key}_{k}", format="%.6g")
        vals["source"] = c[2].text_input("Procedencia", key=f"{key}_lsrc")
        if any(vals[k] is not None for k in vals if k != "source") and not vals["source"]:
            st.warning("Indique la procedencia de los límites para que queden trazados en el experimento.")
    return cond, vals, basis


def _ts_input(kind: str, key: str, prefill: dict | None) -> dict | None:
    """Perfil temporal (potencia o caudal de H₂). Devuelve TimeSeries.to_dict() validado, o None."""
    quantity = "potencia" if kind == "demanda" else "caudal_H2"
    vunits = list(tsm.POWER_UNITS) if quantity == "potencia" else list(FLOW_UNITS)
    methods = ["Generador", "Tabla editable", "Archivo CSV/Excel", "Imagen (digitalizador)"]
    dup = (prefill or {}).get("demand" if kind == "demanda" else "feed")
    if dup:
        methods.insert(0, "Del experimento duplicado")
    _sec("Perfil de demanda eléctrica" if kind == "demanda" else "Caudal de H₂ alimentado")
    method = st.radio("Método de entrada", methods, horizontal=True, key=f"{key}_method")
    if method == "Del experimento duplicado":
        ts = tsm.TimeSeries.from_dict(dup)
        st.caption(f"Perfil del experimento duplicado: {len(ts.t_s)} puntos, {ts.duration_s:g} s, {ts.source}.")
        return dup
    c1, c2, c3 = st.columns(3)
    tu = c1.selectbox("Unidad de tiempo", list(tsm.TIME_UNITS), key=f"{key}_tu")
    vu = c2.selectbox("Unidad", vunits, key=f"{key}_vu")
    interp = c3.selectbox("Entre puntos", tsm.INTERP, key=f"{key}_interp",
                          help="lineal: interpolación; escalonado: el valor se mantiene hasta el siguiente punto.")
    try:
        if method == "Generador":
            g = st.selectbox("Tipo", ["Constante", "Escalón", "Rampa", "Secuencia", "Ciclo periódico"], key=f"{key}_gen")
            c = st.columns(4)
            dv = 1000.0 if quantity == "potencia" else 20.0
            if g == "Constante":
                t, v = tsm.constant(c[0].number_input("Valor", value=dv, key=f"{key}_c_v"),
                                    c[1].number_input("Duración", min_value=0.0, value=60.0, key=f"{key}_c_d"))
            elif g == "Escalón":
                t, v = tsm.step(c[0].number_input("Valor inicial", value=dv / 2, key=f"{key}_s_0"),
                                c[1].number_input("Valor final", value=dv * 3, key=f"{key}_s_1"),
                                c[2].number_input("Instante del escalón", value=20.0, key=f"{key}_s_t"),
                                c[3].number_input("Duración", value=60.0, key=f"{key}_s_d"))
            elif g == "Rampa":
                cc = st.columns(5)
                t, v = tsm.ramp(cc[0].number_input("Valor inicial", value=dv / 2, key=f"{key}_r_0"),
                                cc[1].number_input("Valor final", value=dv * 4, key=f"{key}_r_1"),
                                cc[2].number_input("Inicio", value=10.0, key=f"{key}_r_a"),
                                cc[3].number_input("Fin", value=50.0, key=f"{key}_r_b"),
                                cc[4].number_input("Duración", value=60.0, key=f"{key}_r_d"))
            elif g == "Secuencia":
                lv = st.text_input("Niveles (separados por ;)", "500; 2000; 5000; 0; 3000" if quantity == "potencia"
                                   else "20; 30; 10", key=f"{key}_q_l")
                du = st.text_input("Duraciones (separadas por ;)", "60; 60; 60; 30; 60" if quantity == "potencia"
                                   else "60; 60; 60", key=f"{key}_q_d")
                t, v = tsm.sequence([float(x.replace(",", ".")) for x in lv.split(";") if x.strip()],
                                    [float(x.replace(",", ".")) for x in du.split(";") if x.strip()])
            else:
                shape = c[0].selectbox("Forma", ["seno", "cuadrada", "triangular"], key=f"{key}_p_s")
                t, v = tsm.periodic(c[1].number_input("Valor medio", value=dv * 2.5, key=f"{key}_p_b"),
                                    c[2].number_input("Amplitud", value=dv * 1.5, key=f"{key}_p_a"),
                                    c[3].number_input("Periodo", min_value=0.0, value=60.0, key=f"{key}_p_t"),
                                    st.number_input("Duración", min_value=0.0, value=240.0, key=f"{key}_p_d"), shape)
            source = f"generador: {g}"
        elif method == "Tabla editable":
            base = pd.DataFrame({"tiempo": [0.0, 30.0, 60.0, 90.0],
                                 "valor": [500.0, 2500.0, 2500.0, 1000.0] if quantity == "potencia" else [20.0, 25.0, 25.0, 10.0]})
            df = st.data_editor(base, num_rows="dynamic", key=f"{key}_tbl", width="stretch")
            t, v = df["tiempo"].tolist(), df["valor"].tolist()
            source = "tabla editable"
        elif method == "Archivo CSV/Excel":
            up = st.file_uploader("CSV o Excel con columnas de tiempo y valor", type=["csv", "txt", "xlsx", "xls"], key=f"{key}_file")
            if up is None:
                return None
            df = tsm.read_table(up.getvalue(), up.name)
            cols = list(df.columns)
            a, b = st.columns(2)
            ct = a.selectbox("Columna de tiempo", cols, key=f"{key}_ct")
            cv = b.selectbox("Columna de valor", cols, index=min(1, len(cols) - 1), key=f"{key}_cv")
            t, v = df[ct].tolist(), df[cv].tolist()
            source = f"archivo {up.name}"
        else:
            from . import digitizer_view
            res = digitizer_view.render_series_entry(f"m2:{key}")
            if res:
                _ss()[f"{key}_img"] = res
            img = _ss().get(f"{key}_img")
            if not img:
                st.caption("Digitalice la curva (eje X = tiempo, eje Y = magnitud), confirme ejes y unidades y pulse «Usar "
                           "esta curva como perfil temporal». Después elija aquí las unidades físicas correspondientes.")
                return None
            st.caption(f"Curva digitalizada de **{_esc(img['image'])}** ({img['n']} puntos; unidades declaradas en la imagen: "
                       f"X «{img['x_unit']}», Y «{img['y_unit']}»). Las unidades seleccionadas arriba deben corresponder.")
            t, v = img["x"], img["y"]
            source = f"imagen {img['image']} (SHA-256 {img['sha256'][:12]}…, digitalizada)"
        ts = tsm.validate(t, v, quantity, tu, vu, source, interp)
    except SimulationError as exc:
        st.error(str(exc))
        return None
    except Exception as exc:  # noqa: BLE001
        st.error(f"Entrada no válida: {exc}")
        return None
    for n in ts.notes:
        st.warning(n)
    y = ts.values if quantity == "potencia" else ts.values * 2.01588
    fig = go.Figure(go.Scatter(x=ts.t_s, y=y, mode="lines+markers", marker=dict(size=4),
                               line=dict(color=TEAL, shape="hv" if interp == "escalonado" else "linear")))
    fig.update_layout(height=190, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="t [s]",
                      yaxis_title="P [W]" if quantity == "potencia" else "H₂ [g/s]")
    st.plotly_chart(fig, width="stretch", key=f"{key}_prev")
    return ts.to_dict()


# ===================================================================================================== bancada
def _bench_page(bench: str, ws, dev, cal) -> None:
    m = _m2()
    key = f"m2b_{bench}"
    ss = _ss()
    new_pf = ss.pop(f"m2_prefill_{bench}", None)
    if new_pf is not None:
        for k in [k for k in ss.keys() if str(k).startswith(key + "_")]:
            del ss[k]
        ss[f"m2_prefill_keep_{bench}"] = new_pf
    prefill = ss.get(f"m2_prefill_keep_{bench}")
    num, color, title = next((c[1], c[2], c[3]) for c in CARDS if c[0] == bench)
    c1, c2 = st.columns([1, 5])
    if c1.button("← Bancadas", key="m2_back", width="stretch"):
        m["bench"] = None
        ss.pop(f"m2_prefill_keep_{bench}", None)
        st.rerun()
    with c2:
        st.html(f'<div class="m2x"><div class="m2x-bench-head" style="--c:{color}">{ICON[bench]}<div><span class="num">'
                f'BANCADA {num}</span><h2>{title}</h2></div></div></div>')
    if prefill and prefill.get("_from"):
        st.info(f"Configuración duplicada del experimento `{prefill['_from']}`. Modifíquela y ejecute: se registrará como un "
                "experimento nuevo; el original no cambia.")
    with st.expander("Hipótesis, alcance y limitaciones de esta bancada"):
        for s in SCOPE[bench] + SCOPE["general"]:
            st.markdown(f"- {s}")
    profile = cal.profile
    config = None
    if bench == "reproduccion":
        sets = profile.get("datasets", [])
        lab = {d["curve_id"]: f"{d['curve_id']} · {d.get('role')} · {d['conditions']['temperature_K']:g} K · "
                              f"{d['conditions']['cathode_pressure_atm']:g} atm · {d['n_points']} pts" for d in sets}
        pf = [c for c in ((prefill or {}).get("curve_ids") or []) if c in lab]
        pick = st.multiselect("Experimentos del perfil", list(lab), default=pf or list(lab), format_func=lab.get,
                              key=f"{key}_curves")
        st.caption("Rol «calibración»: reproducción de los datos del ajuste. Rol «validación»: datos no usados en el ajuste "
                   "(validación independiente).")
        config = {"curve_ids": pick} if pick else None
    else:
        cond, limits, basis = _cond_ui(profile, key, prefill)
        if cond.get("temperature_K") is None or cond.get("cathode_pressure_atm") is None:
            cond = None
        if bench == "carga":
            demand = _ts_input("demanda", key, prefill)
            dt = st.number_input("Paso de evaluación [s] (vacío = automático)", min_value=0.0, value=None, key=f"{key}_dt",
                                 format="%.6g")
            config = {"cond": cond, "limits": limits, "basis": basis, "demand": demand, "dt_s": dt or None}
        elif bench == "hidrogeno":
            feed = _ts_input("alimentacion", key, prefill)
            _sec("Política de operación")
            pol_keys = list(POLICIES)
            if prefill and prefill.get("policy") in pol_keys and f"{key}_pol" not in ss:
                ss[f"{key}_pol"] = prefill["policy"]
            pol = st.selectbox("Política", pol_keys, format_func=POLICIES.get, key=f"{key}_pol")
            c = st.columns(3)
            val = None
            if pol != "max_potencia":
                val = c[0].number_input(POLICIES[pol], min_value=0.0, value=(prefill or {}).get("value"), key=f"{key}_pv",
                                        format="%.6g")
            umax = c[1].number_input("Utilización máxima u_máx [–]" + (" (obligatoria)" if pol == "max_potencia" else ""),
                                     min_value=0.0, max_value=1.0, value=(prefill or {}).get("u_max"), key=f"{key}_umax",
                                     help="Dato del dispositivo o criterio de operación. Vacío = solo cota estequiométrica u ≤ 1.")
            dt = c[2].number_input("Paso [s] (vacío = auto)", min_value=0.0, value=None, key=f"{key}_dt", format="%.6g")
            config = {"cond": cond, "limits": limits, "basis": basis, "feed": feed, "policy": pol, "value": val,
                      "u_max": umax, "dt_s": dt or None}
        else:
            _sec("Objetivo y restricciones")
            if prefill and prefill.get("objective") in OBJECTIVES and f"{key}_obj" not in ss:
                ss[f"{key}_obj"] = prefill["objective"]
            obj = st.selectbox("Objetivo", list(OBJECTIVES), format_func=OBJECTIVES.get, key=f"{key}_obj")
            c = st.columns(3)
            pmin = c[0].number_input("Potencia mínima útil [W]", min_value=0.0, value=(prefill or {}).get("p_min_useful_W"),
                                     key=f"{key}_pmin", format="%.6g")
            ptg = c[1].number_input("Potencia objetivo [W]", min_value=0.0, value=(prefill or {}).get("p_target_W"),
                                    key=f"{key}_ptg", format="%.6g", disabled=obj != "potencia_objetivo")
            h2u = c[2].selectbox("Unidad del caudal máximo de H₂", list(FLOW_UNITS), key=f"{key}_h2u")
            c = st.columns(3)
            h2v = c[0].number_input("Caudal máximo de H₂ disponible (opcional)", min_value=0.0, value=None, key=f"{key}_h2v",
                                    format="%.6g")
            umax = c[1].number_input("Utilización máxima u_máx [–]", min_value=0.0, max_value=1.0,
                                     value=(prefill or {}).get("u_max"), key=f"{key}_umax")
            from simulation.stack import flow_to_mol_s
            config = {"cond": cond, "limits": limits, "basis": basis, "objective": obj, "p_min_useful_W": pmin or None,
                      "p_target_W": ptg if obj == "potencia_objetivo" else None,
                      "h2_feed_max_mol_s": float(flow_to_mol_s(h2v, h2u)) if h2v else
                      (prefill or {}).get("h2_feed_max_mol_s"), "u_max": umax}
    if config is not None:
        _cfgs()[bench] = config
    miss = runner.missing(bench, config)
    st.write("")
    c1, c2 = st.columns([3, 1.3])
    name = c1.text_input("Nombre del experimento", value=f"{title} · {dev.name}", key=f"{key}_name")
    run = c2.button("▶ Ejecutar experimento", type="primary", key=f"{key}_run", width="stretch", disabled=bool(miss))
    if miss:
        st.caption("Para ejecutar faltan: " + ", ".join(miss) + ". No se ejecuta con datos inventados.")
    if run:
        try:
            with st.spinner("Ejecutando la bancada…"):
                res = runner.run(bench, profile, config)
            ex = ws.add_experiment(dev.id, cal.id, bench, name, res.to_dict(),
                                   model=res.context.get("model", {}).get("model") or {},
                                   duplicated_from=(prefill or {}).get("_from"))
            ss[f"m2_last_{bench}_{cal.id}"] = ex.id
        except SimulationError as exc:
            st.error(str(exc))
    last = ss.get(f"m2_last_{bench}_{cal.id}")
    if last in ws.experiments:
        st.divider()
        render_experiment(ws.experiments[last], ws, key=f"{key}_res")


# ===================================================================================================== resultados
def _validity_box(r: BenchResult) -> None:
    cls = {"VALIDO": ("m2x-ok", "Válido"), "VALIDO_CON_ADVERTENCIAS": ("m2x-warn", "Válido con advertencias"),
           "EXTRAPOLADO": ("m2x-bad", "Extrapolado"), "NO_EJECUTABLE": ("m2x-bad", "No ejecutable")}.get(r.validity, ("m2x-info", r.validity))
    why = "; ".join(r.validity_reasons) if r.validity_reasons else "Dentro del dominio; revise las advertencias si las hay."
    st.html(f'<div class="m2x"><div class="m2x-validity"><span class="m2x-badge {cls[0]}">{cls[1]}</span> '
            f'<span style="margin-left:.5rem">{_esc(why)}</span></div></div>')


def _fmt(v: float) -> str:
    return f"{v:.4g}" if abs(v) < 1e5 else f"{v:.4e}"


def _kpis(r: BenchResult, keys: list[str] | None = None) -> None:
    ks = [k for k in r.kpis if keys is None or k["key"] in keys]
    if keys:
        ks.sort(key=lambda k: keys.index(k["key"]))
    for i in range(0, len(ks), 4):
        cols = st.columns(4)
        for col, k in zip(cols, ks[i:i + 4]):
            v = k["value"]
            col.metric(k["label"], "—" if v is None else _fmt(v) + (f" {k['unit']}" if k["unit"] else ""),
                       help=k["definition"])


def render_experiment(ex, ws, key: str) -> None:
    r = BenchResult.from_dict(ex.result)
    st.markdown(f"#### {_esc(ex.name)}")
    st.caption(f"{BENCHES[r.bench]} · {ex.created_utc} · experimento `{ex.id}` · perfil `{ex.profile_id}`"
               + (f" · duplicado de `{ex.duplicated_from}`" if ex.duplicated_from else ""))
    _validity_box(r)
    for w in r.warnings:
        st.warning(w)
    {"reproduccion": _res_repro, "carga": _res_load, "hidrogeno": _res_h2, "optimizacion": _res_opt}[r.bench](r, key)
    if r.events:
        with st.expander(f"Eventos ({len(r.events)})", expanded=len(r.events) <= 6):
            st.dataframe(pd.DataFrame([{"evento": e["type"], "inicio [s]": e["t_start_s"], "fin [s]": e["t_end_s"],
                                        "duración [s]": e["duration_s"], "magnitud": f"{e['max_magnitude']:.4g} {e['unit']}",
                                        "causa": e.get("cause"), "consecuencia": e.get("consequence")} for e in r.events]),
                         hide_index=True, width="stretch")
    with st.expander("Hipótesis aplicadas en este experimento"):
        for h in r.hypotheses:
            st.markdown(f"- {h}")
    _export_buttons(ex, ws, key)


def _layout(fig, h, title=None, **kw):
    fig.update_layout(height=h, title=title, margin=dict(l=10, r=10, t=40 if title else 10, b=10), **kw)
    return fig


def _res_repro(r: BenchResult, key: str) -> None:
    _kpis(r, ["rmse_V", "mae_V", "bias_V", "max_abs_V", "n", "max_delta_motor1_V"])
    st.caption(f"Tipo de evaluación: **{r.context['evaluation_kind']}**. "
               + ("Consistente con el Motor 1: métricas idénticas a las del perfil." if r.context.get("consistent_with_motor1") else ""))
    pal = [TEAL, ORANGE, BLUE, VIOLET, RED, GREEN, GREY]
    f1, f2, f3 = go.Figure(), go.Figure(), go.Figure()
    for i, (cid, s) in enumerate(r.series.items()):
        c = pal[i % len(pal)]
        f1.add_trace(go.Scatter(x=s["j_obs"], y=s["V_obs"], mode="markers", marker=dict(color=c, size=5), name=f"{cid} exp."))
        f1.add_trace(go.Scatter(x=s["j_curve"], y=s["V_curve"], mode="lines", line=dict(color=c, width=2), name=f"{cid} modelo"))
        f3.add_trace(go.Scatter(x=s["j_obs"], y=np.array(s["residual_V"]) * 1000, mode="markers", marker=dict(color=c, size=5), name=cid))
        if "P_obs_W" in s:
            f2.add_trace(go.Scatter(x=s["I_obs_A"], y=s["P_obs_W"], mode="markers", marker=dict(color=c, size=5), name=f"{cid} exp."))
            f2.add_trace(go.Scatter(x=s["I_curve_A"], y=s["P_curve_W"], mode="lines", line=dict(color=c, width=2), name=f"{cid} modelo"))
    st.plotly_chart(_layout(f1, 430, "Curva V–I: experimental frente a modelo", xaxis_title="j [A/cm²]", yaxis_title="V celda [V]"),
                    width="stretch", key=f"{key}_vi")
    c1, c2 = st.columns(2)
    if r.context.get("geometry"):
        c1.plotly_chart(_layout(f2, 340, "Curva P–I del stack", xaxis_title="I [A]", yaxis_title="P [W]"), width="stretch", key=f"{key}_pi")
    f3.add_hline(y=0, line_color="#888")
    c2.plotly_chart(_layout(f3, 340, "Residuos V_modelo − V_exp", xaxis_title="j [A/cm²]", yaxis_title="mV"), width="stretch",
                    key=f"{key}_rs")
    _sec("Métricas por experimento y condiciones del ensayo")
    st.dataframe(pd.DataFrame(r.tables["por_curva"]), hide_index=True, width="stretch")
    with st.expander("Tabla experimental frente a calculado"):
        st.dataframe(pd.DataFrame(r.tables["comparacion"]), hide_index=True, width="stretch", height=300)
    with st.expander("Parámetros utilizados"):
        st.dataframe(pd.DataFrame(r.context.get("parameters") or []), hide_index=True, width="stretch")


def _tx(s):
    t = np.array(s["t_s"], float)
    return (t / 60, "t [min]") if t[-1] > 600 else (t, "t [s]")


def _vrects(fig, r, row, types=("incumplimiento_demanda", "limitado_por_combustible")):
    k = 60.0 if np.array(r.series["t_s"])[-1] > 600 else 1.0
    for e in r.events:
        if e["type"] in types:
            fig.add_vrect(x0=e["t_start_s"] / k, x1=max(e["t_end_s"], e["t_start_s"] + 1e-6) / k, fillcolor=RED,
                          opacity=0.1, line_width=0, row=row, col=1)


def _res_load(r: BenchResult, key: str) -> None:
    _kpis(r, ["E_dem", "E_del", "E_uns", "pct_energy", "P_dem_max", "P_del_max", "P_avail", "H2_g",
              "eta_energy", "eta_time", "t_limited_s", "n_deficit_events", "n_ramp_events", "t_low_s", "pct_time", "H2_NL"])
    s = r.series
    x, xl = _tx(s)
    f = make_subplots(rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.035,
                      specs=[[{}], [{}], [{"secondary_y": True}], [{"secondary_y": True}], [{}]],
                      subplot_titles=("Potencia demandada, disponible y entregada", "Déficit de potencia",
                                      "Tensión y corriente del stack", "Consumo teórico de H₂ (instantáneo y acumulado)",
                                      "Eficiencia (no definida con P = 0)"))
    f.add_trace(go.Scatter(x=x, y=s["P_dem_W"], name="Demandada", line=dict(color=GREY, width=2)), 1, 1)
    f.add_trace(go.Scatter(x=x, y=s["P_avail_W"], name="Disponible", line=dict(color=ORANGE, dash="dot")), 1, 1)
    f.add_trace(go.Scatter(x=x, y=s["P_del_W_ideal"], name="Entregada (ideal)", line=dict(color=TEAL, dash="dash", width=1)), 1, 1)
    f.add_trace(go.Scatter(x=x, y=s["P_del_W"], name="Entregada (restringida)", line=dict(color=TEAL, width=2.4)), 1, 1)
    f.add_trace(go.Scatter(x=x, y=s["deficit_W"], name="Déficit", fill="tozeroy", line=dict(color=RED)), 2, 1)
    f.add_trace(go.Scatter(x=x, y=s["V_stack_V"], name="V stack", line=dict(color=BLUE)), 3, 1, secondary_y=False)
    f.add_trace(go.Scatter(x=x, y=s["I_A"], name="I", line=dict(color=VIOLET)), 3, 1, secondary_y=True)
    f.add_trace(go.Scatter(x=x, y=s["H2_g_s"], name="H₂ [g/s]", line=dict(color=GREEN)), 4, 1, secondary_y=False)
    f.add_trace(go.Scatter(x=x, y=s["H2_cum_g"], name="H₂ acumulado [g]", line=dict(color=TEAL, dash="dash")), 4, 1, secondary_y=True)
    f.add_trace(go.Scatter(x=x, y=[None if v is None else 100 * v for v in s["eta"]], name="η [%]", line=dict(color=VIOLET)), 5, 1)
    _vrects(f, r, 1)
    for row, t1, t2 in ((1, "W", None), (2, "W", None), (3, "V", "A"), (4, "g/s", "g"), (5, "%", None)):
        f.update_yaxes(title_text=t1, row=row, col=1, secondary_y=False)
        if t2:
            f.update_yaxes(title_text=t2, row=row, col=1, secondary_y=True)
    f.update_xaxes(title_text=xl, row=5, col=1)
    f.update_yaxes(rangemode="tozero")          # magnitudes no negativas: el eje nunca sugiere valores < 0
    _layout(f, 1100, None, hovermode="x unified", legend=dict(orientation="h", y=-0.055, yanchor="top"))
    f.update_layout(margin=dict(l=10, r=10, t=40, b=110))
    st.plotly_chart(f, width="stretch", key=f"{key}_load")
    st.caption("Zonas rojas: incumplimiento de demanda. Margen de capacidad = disponible − entregada: capacidad no usada, "
               "no energía generada.")


def _res_h2(r: BenchResult, key: str) -> None:
    _kpis(r)
    s = r.series
    x, xl = _tx(s)
    f = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04, specs=[[{}], [{}], [{"secondary_y": True}], [{}]],
                      subplot_titles=("H₂ alimentado y consumido", "H₂ acumulado", "Potencia y corriente", "Utilización y eficiencia"))
    f.add_trace(go.Scatter(x=x, y=s["H2_fed_g_s"], name="Alimentado [g/s]", line=dict(color=GREY, width=2)), 1, 1)
    f.add_trace(go.Scatter(x=x, y=s["H2_cons_g_s"], name="Consumido [g/s]", line=dict(color=GREEN, width=2)), 1, 1)
    f.add_trace(go.Scatter(x=x, y=s["H2_fed_cum_g"], name="Alimentado [g]", line=dict(color=GREY)), 2, 1)
    f.add_trace(go.Scatter(x=x, y=s["H2_cons_cum_g"], name="Consumido [g]", line=dict(color=GREEN)), 2, 1)
    f.add_trace(go.Scatter(x=x, y=s["P_W"], name="P [W]", line=dict(color=TEAL, width=2)), 3, 1)
    f.add_trace(go.Scatter(x=x, y=s["I_A"], name="I [A]", line=dict(color=VIOLET)), 3, 1, secondary_y=True)
    for name, k, c, d in (("Utilización [%]", "utilization", GREEN, None), ("η consumido [%]", "eta_cons", VIOLET, None),
                          ("η alimentado [%]", "eta_fed", VIOLET, "dash")):
        f.add_trace(go.Scatter(x=x, y=[None if v is None else 100 * v for v in s[k]], name=name, line=dict(color=c, dash=d)), 4, 1)
    _vrects(f, r, 1)
    f.update_xaxes(title_text=xl, row=4, col=1)
    f.update_yaxes(rangemode="tozero")
    _layout(f, 920, None, hovermode="x unified", legend=dict(orientation="h", y=-0.055, yanchor="top"))
    f.update_layout(margin=dict(l=10, r=10, t=40, b=110))
    st.plotly_chart(f, width="stretch", key=f"{key}_h2")


def _res_opt(r: BenchResult, key: str) -> None:
    _kpis(r)
    ctx = r.context
    st.info(ctx.get("explanation", ""))
    st.caption("Restricciones activas: " + (", ".join(ctx.get("active_constraints") or []) or "ninguna (óptimo interior)")
               + f" · cota superior del dominio: {ctx.get('upper_binding')}.")
    s = r.series
    j, p, eta, feas = np.array(s["j_A_cm2"]), np.array(s["P_W"]), np.array(s["eta"]) * 100, np.array(s["feasible"], bool)
    sel = ctx["selected"]
    f = make_subplots(specs=[[{"secondary_y": True}]])
    f.add_trace(go.Scatter(x=j, y=p, name="P(j)", line=dict(color=TEAL, width=2.4)))
    f.add_trace(go.Scatter(x=j, y=eta, name="η(j)", line=dict(color=VIOLET)), secondary_y=True)
    if (~feas).any():
        f.add_trace(go.Scatter(x=j[~feas], y=p[~feas], mode="markers", name="No admisible", marker=dict(color="#bbb", size=3)))
    f.add_trace(go.Scatter(x=[sel["j_A_cm2"]], y=[sel["P_W"]], mode="markers", name="Seleccionado",
                           marker=dict(color=RED, size=14, symbol="star")))
    f.add_vline(x=sel["j_A_cm2"], line_dash="dash", line_color=RED)
    f.update_yaxes(title_text="P [W]", secondary_y=False)
    f.update_yaxes(title_text="η [%]", secondary_y=True)
    st.plotly_chart(_layout(f, 420, OBJECTIVES[r.inputs["objective"]], xaxis_title="j [A/cm²]"), width="stretch", key=f"{key}_opt")
    c1, c2 = st.columns(2)
    g = go.Figure(go.Scatter(x=p[feas], y=eta[feas], mode="lines", line=dict(color="#9aa5b1"), name="Admisibles"))
    fr = s.get("frontier_idx") or []
    if fr:
        g.add_trace(go.Scatter(x=p[fr], y=eta[fr], mode="lines", line=dict(color=TEAL, width=3), name="Frontera de Pareto"))
    g.add_trace(go.Scatter(x=[sel["P_W"]], y=[100 * sel["eta"]], mode="markers", marker=dict(color=RED, size=12, symbol="star"),
                           name="Seleccionado"))
    c1.plotly_chart(_layout(g, 340, "Potencia frente a eficiencia", xaxis_title="P [W]", yaxis_title="η [%]"), width="stretch",
                    key=f"{key}_par")
    h = go.Figure(go.Scatter(x=j, y=s["SFC_g_kWh"], line=dict(color=GREEN), name="SFC"))
    h.add_vline(x=sel["j_A_cm2"], line_dash="dash", line_color=RED)
    c2.plotly_chart(_layout(h, 340, "Consumo específico de H₂", xaxis_title="j [A/cm²]", yaxis_title="g/kWh"), width="stretch",
                    key=f"{key}_sfc")
    _sec("Comparación con otros puntos de operación")
    st.dataframe(pd.DataFrame(r.tables["comparacion"]), hide_index=True, width="stretch")


# ===================================================================================================== exportación
def _record(ex) -> dict:
    from dataclasses import asdict
    return asdict(ex)


def _export_buttons(ex, ws, key: str) -> None:
    from simulation import report
    _sec("Exportar este experimento")
    cache = _ss().setdefault("m2_exp_cache", {})
    if ex.id not in cache:
        if st.button("Preparar exportaciones (ZIP, PDF, CSV, Excel, JSON, PNG, SVG)", key=f"{key}_prep"):
            with st.spinner("Generando figuras, informe y paquete…"):
                rec = _record(ex)
                r = BenchResult.from_dict(ex.result)
                prof = ws.calibrations[ex.calibration_id].profile if ex.calibration_id in ws.calibrations else None
                figs = report.figures(r)
                main = next(iter(figs.values()))
                cache[ex.id] = {"zip": report.experiment_zip(rec, prof), "pdf": report.report_pdf(r, rec, prof, figs),
                                "csv": report.to_csv(r), "xlsx": report.to_xlsx(r, rec),
                                "json": json.dumps(rec, ensure_ascii=False, indent=1, default=str).encode(),
                                "png": report.fig_bytes(main, "png"), "svg": report.fig_bytes(main, "svg")}
                import matplotlib.pyplot as plt
                for f_ in figs.values():
                    plt.close(f_)
            st.rerun()
        return
    files = cache[ex.id]
    stem = report._safe(ex.name)
    spec = [("ZIP completo", "zip", "application/zip"), ("Informe PDF", "pdf", "application/pdf"), ("CSV", "csv", "text/csv"),
            ("Excel", "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("JSON", "json", "application/json"), ("PNG", "png", "image/png"), ("SVG", "svg", "image/svg+xml")]
    cols = st.columns(len(spec))
    for col, (lab, ext, mime) in zip(cols, spec):
        col.download_button(lab, files[ext], file_name=f"{stem}.{ext}", mime=mime, key=f"{key}_dl_{ext}", width="stretch")


# ===================================================================================================== historial
def _history_tab(ws, dev) -> None:
    exps = ws.device_experiments(dev.id)
    if not exps:
        st.info("Este dispositivo todavía no tiene experimentos del Motor 2. Abra una bancada y ejecute un experimento.")
        return
    rows = [{"experimento": e.name, "bancada": BENCHES.get(e.bench, e.bench), "fecha (UTC)": e.created_utc,
             "validez": e.result.get("validity"), "perfil": e.profile_id, "advertencias": len(e.result.get("warnings") or []),
             "estudio": e.study_id or "", "duplicado de": e.duplicated_from or ""} for e in exps]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    lab = {e.id: f"{e.name} · {BENCHES.get(e.bench)} · {e.created_utc}" for e in exps}
    pick = st.selectbox("Consultar experimento", list(lab), format_func=lab.get, key=f"m2_hist_{dev.id}")
    ex = ws.experiments[pick]
    if st.button("Duplicar configuración", key=f"m2_dup_{pick}",
                 help="Abre la bancada con las mismas entradas para modificarlas y ejecutar un experimento nuevo."):
        cfg = dict((ex.result.get("inputs") or {}).get("config") or {})
        cfg["_from"] = ex.id
        _ss()[f"m2_prefill_{ex.bench}"] = cfg
        m = _m2()
        m["bench"] = ex.bench
        if ex.calibration_id in ws.calibrations:
            m["cal"] = ex.calibration_id
        st.rerun()
    with st.container(border=True):
        render_experiment(ex, ws, key=f"m2h_{pick}")
    same = [e for e in exps if e.bench == ex.bench]
    if len(same) >= 2:
        with st.expander("Comparar experimentos de la misma bancada"):
            sel = st.multiselect("Experimentos", [e.id for e in same], default=[e.id for e in same[:2]],
                                 format_func=lab.get, key=f"m2_cmp_{dev.id}_{ex.bench}")
            if len(sel) >= 2:
                comp = []
                for i in sel:
                    r = BenchResult.from_dict(ws.experiments[i].result)
                    comp.append({"experimento": ws.experiments[i].name, "validez": r.validity,
                                 **{f"{k['label']} [{k['unit']}]": k["value"] for k in r.kpis}})
                st.dataframe(pd.DataFrame(comp), hide_index=True, width="stretch")
                if ex.bench in ("carga", "hidrogeno"):
                    f = go.Figure()
                    yk = "P_del_W" if ex.bench == "carga" else "P_W"
                    for i in sel:
                        s = ws.experiments[i].result["series"]
                        f.add_trace(go.Scatter(x=s["t_s"], y=s[yk], name=ws.experiments[i].name))
                    st.plotly_chart(_layout(f, 320, "Potencia entregada", xaxis_title="t [s]", yaxis_title="W"),
                                    width="stretch", key=f"m2_cmpf_{dev.id}")


def _exports_tab(ws, dev) -> None:
    from simulation import report
    exps = ws.device_experiments(dev.id)
    if not exps:
        st.info("Sin experimentos que exportar todavía.")
        return
    st.caption("Cada experimento se exporta con datos, figuras (PNG y SVG), informe técnico PDF, perfil usado y el registro "
               "JSON con el que se reconstruyen los gráficos. Los experimentos también viajan en el paquete ZIP del "
               "dispositivo (Motor 1 → gestión de dispositivos).")
    lab = {e.id: f"{e.name} · {BENCHES.get(e.bench)} · {e.created_utc}" for e in exps}
    sel = st.multiselect("Experimentos a exportar conjuntamente", list(lab), default=list(lab)[:4], format_func=lab.get,
                         key=f"m2_exsel_{dev.id}")
    if sel and st.button("Generar paquete conjunto (ZIP)", type="primary", key=f"m2_exzip_{dev.id}"):
        with st.spinner("Generando informes y paquetes…"):
            recs = [_record(ws.experiments[i]) for i in sel]
            profs = {ws.experiments[i].profile_id: ws.calibrations[ws.experiments[i].calibration_id].profile
                     for i in sel if ws.experiments[i].calibration_id in ws.calibrations}
            _ss()["m2_joint_zip"] = (report.study_zip(recs, [], profs), len(sel))
    if _ss().get("m2_joint_zip"):
        data, n = _ss()["m2_joint_zip"]
        st.download_button(f"Descargar paquete conjunto ({n} experimentos)", data, file_name="motor2_experimentos.zip",
                           mime="application/zip", key=f"m2_exdl_{dev.id}")


# ===================================================================================================== estudio completo
def _study_tab(ws, dev, cal) -> None:
    from simulation import report
    st.markdown("Ejecute varias bancadas con su configuración actual (la definida en cada bancada) y obtenga un resumen "
                "integrado. Una bancada sin las entradas necesarias **se omite y se indica el motivo**: nunca se ejecuta "
                "con datos inventados.")
    cfgs = _cfgs()
    sel = []
    for b in BENCHES:
        cfg = cfgs.get(b) if b != "reproduccion" else (cfgs.get(b) or {"curve_ids": None})
        miss = runner.missing(b, cfg)
        c1, c2, c3 = st.columns([2.2, 3.5, 1.2])
        on = c1.checkbox(BENCHES[b], value=not miss, key=f"m2_st_{b}")
        c2.caption("Configuración lista." if not miss else "Falta: " + ", ".join(miss) + " (configúrela en la bancada).")
        if c3.button("Configurar", key=f"m2_stcfg_{b}", width="stretch"):
            _m2()["bench"] = b
            st.rerun()
        if on:
            sel.append(b)
    if st.button("▶ Ejecutar estudio completo", type="primary", key="m2_study_run", disabled=not sel):
        from workspace.model import new_id
        sid = new_id("std")
        done, skipped = [], []
        prog = st.progress(0.0)
        for k, b in enumerate(sel):
            cfg = cfgs.get(b) if b != "reproduccion" else (cfgs.get(b) or {"curve_ids": None})
            miss = runner.missing(b, cfg)
            if miss:
                skipped.append({"bench": b, "reason": "faltan " + ", ".join(miss)})
            else:
                try:
                    res = runner.run(b, cal.profile, cfg)
                    ex = ws.add_experiment(dev.id, cal.id, b, f"Estudio {sid[-5:]} · {BENCHES[b]}", res.to_dict(),
                                           model=res.context.get("model", {}).get("model") or {}, study_id=sid)
                    done.append(ex.id)
                except SimulationError as exc:
                    skipped.append({"bench": b, "reason": str(exc)})
            prog.progress((k + 1) / len(sel))
        for b in BENCHES:
            if b not in sel:
                skipped.append({"bench": b, "reason": "no seleccionada por el usuario"})
        _ss()["m2_study"] = {"id": sid, "done": done, "skipped": skipped}
        _ss().pop("m2_study_zip", None)
    stdy = _ss().get("m2_study")
    if stdy:
        st.markdown(f"#### Resumen integrado del estudio `{stdy['id']}`")
        rows = []
        for i in stdy["done"]:
            ex = ws.experiments.get(i)
            if ex is None:
                continue
            r = BenchResult.from_dict(ex.result)
            rows.append({"bancada": BENCHES[r.bench], "estado": "ejecutada", "validez": r.validity,
                         "advertencias": len(r.warnings), "eventos": len(r.events),
                         "indicadores principales": " · ".join(f"{k['label']}: {_fmt(k['value'])} {k['unit']}"
                                                               for k in r.kpis[:3] if k["value"] is not None)})
        rows += [{"bancada": BENCHES[s["bench"]], "estado": "omitida", "validez": "NO_EJECUTABLE", "advertencias": 0,
                  "eventos": 0, "indicadores principales": s["reason"]} for s in stdy["skipped"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for i in stdy["done"]:
            ex = ws.experiments.get(i)
            if ex:
                for w in ex.result.get("warnings", [])[:3]:
                    st.warning(f"{BENCHES[ex.bench]}: {w}")
        st.caption("Cada experimento del estudio queda en el Historial (con su identificador de estudio) para consultarlo y compararlo.")
        if st.button("Preparar exportación conjunta del estudio", key="m2_study_zipb"):
            with st.spinner("Generando…"):
                recs = [_record(ws.experiments[i]) for i in stdy["done"] if i in ws.experiments]
                _ss()["m2_study_zip"] = report.study_zip(recs, stdy["skipped"], {cal.profile_id: cal.profile})
        if _ss().get("m2_study_zip"):
            st.download_button("Descargar estudio (ZIP)", _ss()["m2_study_zip"], file_name=f"estudio_{stdy['id']}.zip",
                               mime="application/zip", key="m2_study_dl")


# ===================================================================================================== alcance
def _scope_tab() -> None:
    st.markdown("#### Alcance científico y limitaciones del Motor 2")
    for s in SCOPE["general"]:
        st.markdown(f"- {s}")
    st.markdown("**Persistencia.** Los experimentos se guardan en este navegador (IndexedDB) junto con el dispositivo y "
                "viajan en su paquete ZIP. En Streamlit Cloud el servidor no conserva datos: exporte los experimentos o "
                "el dispositivo para conservarlos de forma independiente.")
    for b in ("carga", "hidrogeno", "optimizacion"):
        st.markdown(f"**{BENCHES[b]}**")
        for s in SCOPE[b]:
            st.markdown(f"- {s}")
