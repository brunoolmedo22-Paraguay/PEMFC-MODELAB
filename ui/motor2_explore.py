"""Interfaz de las Bancadas 05 (sensibilidad y escenarios) y 06 (mapas operacionales)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from simulation.maps import AXES, COND, PAIRS, QUANTITIES, TP_EXTRA, estimate, point_details
from simulation.scenarios import MODES, OPER_VARS, RESPONSES, base_values, param_info, uncertainty_available
from simulation.stack import OperatingLimits

PAL = ["#0f8b8d", "#e0891e", "#2f6fed", "#7a4fd1", "#d1495b", "#3c9d5d", "#7a8796", "#b7791f"]


def _ss():
    return st.session_state


def _v(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


# ===================================================================================================== Bancada 05
def config_sens(profile: dict, key: str, prefill: dict | None, cond: dict | None, limits: dict, basis: str) -> dict | None:
    from .motor2_view import _sec
    ss = _ss()
    pf = prefill or {}
    if pf.get("mode") and f"{key}_mode" not in ss:
        ss[f"{key}_mode"] = pf["mode"]
    mode = st.segmented_control("Análisis", list(MODES), format_func=MODES.get, key=f"{key}_mode", default="escenarios")
    mode = mode or "escenarios"
    dom = profile["domain"]["calibration"]
    j_mid = round(0.5 * (dom["j_A_cm2"][0] + dom["j_A_cm2"][1]), 4)
    if cond is None:
        st.info("Indique las condiciones base (temperatura y presión).")
        return None
    if mode == "escenarios":
        _sec("Escenarios")
        st.caption("Variables OPERACIONALES (cambios físicos realizables). p_H₂ e y_O₂ vacíos = valor del perfil. "
                   "Edite, añada o elimine filas; marque «activo» para incluir el escenario en la comparación.")
        if f"{key}_scen" not in ss:
            ss[f"{key}_scen"] = pf.get("scenarios") or [{"name": "Referencia", "active": True,
                                                        "temperature_K": cond["temperature_K"],
                                                        "cathode_pressure_atm": cond["cathode_pressure_atm"]}]
        for s in ss.pop("m2_scen_add", []) or []:
            names = {x["name"] for x in ss[f"{key}_scen"]}
            if s["name"] in names:
                s["name"] += " (mapa)"
            ss[f"{key}_scen"].append(s)
            ss[f"{key}_ver"] = ss.get(f"{key}_ver", 0) + 1
        scen = ss[f"{key}_scen"]
        df = pd.DataFrame([{"nombre": s["name"], "activo": s.get("active", True), "T [K]": s.get("temperature_K"),
                            "P cátodo [atm]": s.get("cathode_pressure_atm"), "p_H₂ [atm]": s.get("p_h2_atm"),
                            "y_O₂ [–]": s.get("oxygen_fraction")} for s in scen])
        ed = st.data_editor(df, num_rows="dynamic", width="stretch", key=f"{key}_tbl_{ss.get(f'{key}_ver', 0)}",
                            column_config={"activo": st.column_config.CheckboxColumn(default=True)})
        params = {s["name"]: s.get("params") or {} for s in scen}
        new = []
        for _, row in ed.iterrows():
            if not str(row["nombre"] or "").strip():
                continue
            new.append({"name": str(row["nombre"]).strip(), "active": bool(row["activo"]) if row["activo"] is not None else True,
                        "temperature_K": _v(row["T [K]"]), "cathode_pressure_atm": _v(row["P cátodo [atm]"]),
                        "p_h2_atm": _v(row["p_H₂ [atm]"]), "oxygen_fraction": _v(row["y_O₂ [–]"]),
                        "params": params.get(str(row["nombre"]).strip()) or {}})
        ss[f"{key}_scen"] = new
        names = [s["name"] for s in new]
        c1, c2, c3 = st.columns([2, 1.2, 1.2])
        dup = c1.selectbox("Escenario", names, key=f"{key}_dupsel") if names else None
        if c2.button("Duplicar", key=f"{key}_dup", width="stretch", disabled=not dup):
            src = next(s for s in new if s["name"] == dup)
            ss[f"{key}_scen"] = new + [dict(src, name=f"{dup} (copia)", params=dict(src.get("params") or {}))]
            ss[f"{key}_ver"] = ss.get(f"{key}_ver", 0) + 1
            st.rerun()
        if c3.button("Generar mapa con él", key=f"{key}_tomap", width="stretch", disabled=not dup,
                     help="Abre la Bancada 06 con las condiciones de este escenario como condiciones fijas."):
            src = next(s for s in new if s["name"] == dup)
            ss["m2_prefill_mapa"] = {"fixed": {k: src.get(k) for k in COND.values()}, "_from_scenario": dup}
            ss.m2["bench"] = "mapa"
            st.rerun()
        with st.expander("Perturbación de parámetros del modelo (análisis MATEMÁTICO, no cambio físico)"):
            pinfo = param_info(profile)
            st.caption("Asigne a un escenario valores alternativos de parámetros identificados para estudiar la sensibilidad "
                       "del modelo. No representan un cambio realizable del dispositivo.")
            rows = [{"escenario": s["name"], "parámetro": k, "valor": v} for s in new for k, v in (s.get("params") or {}).items()]
            pe = st.data_editor(pd.DataFrame(rows, columns=["escenario", "parámetro", "valor"]), num_rows="dynamic",
                                key=f"{key}_ptbl_{ss.get(f'{key}_ver', 0)}", width="stretch",
                                column_config={"escenario": st.column_config.SelectboxColumn(options=names),
                                               "parámetro": st.column_config.SelectboxColumn(options=list(pinfo)),
                                               "valor": st.column_config.NumberColumn(format="%.6g")})
            for s in ss[f"{key}_scen"]:
                s["params"] = {r["parámetro"]: float(r["valor"]) for _, r in pe.iterrows()
                               if r["escenario"] == s["name"] and r["parámetro"] in pinfo and _v(r["valor"]) is not None}
            st.dataframe(pd.DataFrame([{"parámetro": k, "valor del perfil": v["value"], "unidad": v["unit"],
                                        "libre": v["free"], "identificación": v["identifiability"],
                                        "error estándar": v["std_error"]} for k, v in pinfo.items()]),
                         hide_index=True, width="stretch")
        c1, c2 = st.columns(2)
        ref = c1.selectbox("Escenario de referencia", [s["name"] for s in ss[f"{key}_scen"] if s["active"]] or ["—"],
                           key=f"{key}_ref")
        jref = c2.number_input("Punto de comparación j_ref [A/cm²]", min_value=float(dom["j_A_cm2"][0]),
                               max_value=float(dom["j_A_cm2"][1]), value=float(pf.get("j_ref") or j_mid), key=f"{key}_jref",
                               help="Todos los escenarios se comparan a esta MISMA densidad de corriente.")
        sc = [s for s in ss[f"{key}_scen"]]
        if any(s["temperature_K"] is None or s["cathode_pressure_atm"] is None for s in sc if s["active"]):
            st.warning("Complete T y P en todos los escenarios activos.")
            return None
        return {"mode": "escenarios", "scenarios": sc, "reference": ref if ref != "—" else None, "j_ref": jref,
                "limits": limits, "basis": basis, "cond": cond}
    if mode == "sensibilidad":
        _sec("Variables, intervalos y respuesta")
        c1, c2 = st.columns([1.6, 1])
        resp = c1.selectbox("Variable de respuesta", list(RESPONSES), format_func=lambda k: f"{RESPONSES[k][0]} [{RESPONSES[k][1]}]",
                            key=f"{key}_resp")
        jev = None
        if resp in ("V_cell", "P", "eta"):
            jev = c2.number_input("j_eval [A/cm²]", min_value=float(dom["j_A_cm2"][0]), max_value=float(dom["j_A_cm2"][1]),
                                  value=float(pf.get("j_eval") or j_mid), key=f"{key}_jev")
        pinfo = param_info(profile)
        bv = base_values(profile, cond)
        opts = [("oper", k) for k in OPER_VARS] + [("param", k) for k in pinfo]
        lab = {f"{k}:{n}": (f"{OPER_VARS[n][0]} [{OPER_VARS[n][1]}] — operacional" if k == "oper"
                            else f"{n} [{pinfo[n]['unit']}] — parámetro (matemático)" + (" · identificación débil" if pinfo[n]["weak"] else ""))
               for k, n in opts}
        default = [f"oper:{k}" for k in ("temperature_K", "cathode_pressure_atm")] + [f"param:{k}" for k in ("xi1", "R_mem_ref_ohm_cm2") if k in pinfo]
        sel = st.multiselect("Variables", list(lab), default=[d for d in default if d in lab], format_func=lab.get, key=f"{key}_vars")
        rows = []
        for s_ in sel:
            k, n = s_.split(":", 1)
            x0 = bv[n] if k == "oper" else pinfo[n]["value"]
            se = pinfo.get(n, {}).get("std_error") if k == "param" else None
            if k == "oper":
                lo, hi = {"temperature_K": (x0 - 10, x0 + 10), "oxygen_fraction": (max(x0 - 0.02, 0.01), min(x0 + 0.02, 1.0))}.get(n, (0.8 * x0, 1.2 * x0))
                why = "±10 K" if n == "temperature_K" else ("±0,02" if n == "oxygen_fraction" else "±20 %")
            elif se:
                lo, hi, why = x0 - 2 * se, x0 + 2 * se, "±2σ (error estándar del perfil)"
            else:
                d = 0.1 * abs(x0) if x0 else 0.1
                lo, hi, why = x0 - d, x0 + d, "±10 % (sin error estándar en el perfil)"
            rows.append({"variable": s_, "valor base": x0, "mínimo": lo, "máximo": hi, "intervalo por defecto": why})
        if not rows:
            return None
        ed = st.data_editor(pd.DataFrame(rows), disabled=["variable", "valor base", "intervalo por defecto"], hide_index=True,
                            width="stretch", key=f"{key}_rng_{'|'.join(sel)}")
        st.caption("Los intervalos son una elección del análisis (editables), no datos del dispositivo. El tornado compara "
                   "amplitudes sobre ESTOS intervalos.")
        npts = st.slider("Puntos por barrido", 7, 61, 21, 2, key=f"{key}_npts")
        variables = [{"kind": r["variable"].split(":")[0], "name": r["variable"].split(":", 1)[1], "lo": float(r["mínimo"]),
                      "hi": float(r["máximo"])} for _, r in ed.iterrows()]
        return {"mode": "sensibilidad", "cond": cond, "variables": variables, "response": resp, "j_eval": jev,
                "limits": limits, "basis": basis, "n_points": npts}
    _sec("Incertidumbre estadística de los parámetros identificados")
    ok, txt, _ = uncertainty_available(profile)
    if not ok:
        st.error("No disponible: " + txt + " Use el análisis de sensibilidad (perturbación determinista).")
        return None
    st.caption(f"Base estadística del perfil: {txt}. Se propaga con Monte Carlo la covarianza (σ y correlaciones) de los "
               "parámetros libres. Es distinto de la sensibilidad determinista.")
    c = st.columns(3)
    n = c[0].slider("Muestras", 100, 2000, 400, 100, key=f"{key}_ns")
    seed = c[1].number_input("Semilla", value=20260720, step=1, key=f"{key}_seed")
    jr = c[2].number_input("j_ref [A/cm²]", min_value=float(dom["j_A_cm2"][0]), max_value=float(dom["j_A_cm2"][1]),
                           value=float(pf.get("j_ref") or j_mid), key=f"{key}_ujr")
    return {"mode": "incertidumbre", "cond": cond, "j_ref": jr, "n_samples": n, "seed": int(seed), "limits": limits, "basis": basis}


def render_sens(r, key: str) -> None:
    from .motor2_view import _kpis, _layout, _sec
    mode = r.context.get("mode")
    s = r.series
    _kpis(r)
    if mode == "escenarios":
        j = s["j_A_cm2"]
        f = make_subplots(rows=2, cols=2, shared_xaxes=True, vertical_spacing=0.09, horizontal_spacing=0.08,
                          subplot_titles=("Tensión de celda [V]", "Potencia del stack [W]", "ΔV vs referencia [mV]",
                                          "ΔP vs referencia [W]"))
        for k, name in enumerate(s["scenarios"]):
            d, c = s[name], PAL[k % len(PAL)]
            w = 3 if name == s["reference"] else 1.8
            for (row, col), y in zip(((1, 1), (1, 2), (2, 1), (2, 2)),
                                     (d["V_cell_V"], d["P_W"], [None if v is None else 1000 * v for v in d["dV_V"]], d["dP_W"])):
                f.add_trace(go.Scatter(x=j, y=y, name=name, legendgroup=name, showlegend=(row, col) == (1, 1),
                                       line=dict(color=c, width=w)), row, col)
        f.add_vline(x=r.inputs["j_ref"], line_dash="dot", line_color="#888")
        f.update_xaxes(title_text="j [A/cm²]", row=2)
        st.plotly_chart(_layout(f, 640, None, hovermode="x unified", legend=dict(orientation="h", y=-0.12)), width="stretch",
                        key=f"{key}_esc")
        st.caption("Pulse un escenario en la leyenda para ocultarlo o mostrarlo. Línea punteada: j_ref.")
        g = go.Figure()
        for k, name in enumerate(s["scenarios"]):
            g.add_trace(go.Scatter(x=j, y=[None if v is None else 100 * v for v in s[name]["eta"]], name=name,
                                   line=dict(color=PAL[k % len(PAL)])))
        st.plotly_chart(_layout(g, 300, "Eficiencia (H₂ consumido)", xaxis_title="j [A/cm²]", yaxis_title="%"), width="stretch",
                        key=f"{key}_eta")
        _sec(f"Indicadores comparativos (P máx. en el j propio de cada escenario; resto en j_ref = {r.inputs['j_ref']:g} A/cm²)")
        st.dataframe(pd.DataFrame(r.tables["indicadores"]), hide_index=True, width="stretch")
    elif mode == "sensibilidad":
        rows = sorted([x for x in r.tables["sensibilidades"] if x["rango_R"] is not None], key=lambda x: x["rango_R"])
        r0 = r.kpi("R0")
        f = go.Figure()
        f.add_trace(go.Bar(y=[x["variable"] for x in rows], x=[x["R_en_x_max"] - r0 for x in rows], orientation="h",
                           name="extremo superior", marker_color=PAL[0]))
        f.add_trace(go.Bar(y=[x["variable"] for x in rows], x=[x["R_en_x_min"] - r0 for x in rows], orientation="h",
                           name="extremo inferior", marker_color=PAL[1]))
        f.update_layout(barmode="overlay")
        st.plotly_chart(_layout(f, 120 + 42 * len(rows), "Tornado: ΔR respecto a la base", xaxis_title="ΔR"), width="stretch",
                        key=f"{key}_tor")
        st.caption(f"Variable dominante (amplitud en los intervalos elegidos): **{r.context.get('dominant')}**.")
        names = [k for k in s if isinstance(s[k], dict)]
        g = make_subplots(rows=1, cols=len(names), subplot_titles=[s[n]["label"] for n in names])
        for k, n in enumerate(names):
            g.add_trace(go.Scatter(x=s[n]["x"], y=s[n]["y"], name=n, line=dict(color=PAL[k % len(PAL)])), 1, k + 1)
            g.add_vline(x=s[n]["x0"], line_dash="dot", line_color="#d1495b", row=1, col=k + 1)
        st.plotly_chart(_layout(g, 300, None, showlegend=False), width="stretch", key=f"{key}_resp")
        st.dataframe(pd.DataFrame(r.tables["sensibilidades"]), hide_index=True, width="stretch")
    else:
        j = s["j_A_cm2"]
        f = make_subplots(rows=1, cols=2, subplot_titles=("Tensión de celda: banda 95 %", "Potencia: banda 95 %"))
        for col, (a, b, c, nom, color) in enumerate((("V_p025", "V_p975", "V_nominal", "V", PAL[0]),
                                                     ("P_p025", "P_p975", "P_nominal", "P", PAL[1])), start=1):
            f.add_trace(go.Scatter(x=j, y=s[b], line=dict(width=0), showlegend=False), 1, col)
            f.add_trace(go.Scatter(x=j, y=s[a], fill="tonexty", line=dict(width=0), fillcolor="rgba(15,139,141,0.2)" if col == 1
                                   else "rgba(224,137,30,0.2)", name=f"{nom} 2,5–97,5 %"), 1, col)
            f.add_trace(go.Scatter(x=j, y=s[c], line=dict(color=color), name=f"{nom} nominal"), 1, col)
        f.update_xaxes(title_text="j [A/cm²]")
        st.plotly_chart(_layout(f, 380, None), width="stretch", key=f"{key}_band")
        h = go.Figure(go.Histogram(x=s["Pmax_samples"], marker_color=PAL[3], nbinsx=35))
        st.plotly_chart(_layout(h, 280, "Distribución de la potencia máxima", xaxis_title="W", yaxis_title="muestras"),
                        width="stretch", key=f"{key}_hist")
        st.dataframe(pd.DataFrame(r.tables["parametros"]), hide_index=True, width="stretch")


# ===================================================================================================== Bancada 06
def config_map(profile: dict, key: str, prefill: dict | None, cond: dict | None, limits: dict, basis: str) -> dict | None:
    from .motor2_view import _sec
    ss = _ss()
    pf = prefill or {}
    dom = profile["domain"]["calibration"]
    bv0 = base_values(profile, dom["conditions"][0])
    if pf.get("_from_scenario"):
        st.info(f"Condiciones fijas tomadas del escenario «{pf['_from_scenario']}» de la Bancada 05.")
    _sec("Espacio operacional")
    pair_lab = {f"{a}|{b}": f"{AXES[a][0]} × {AXES[b][0]}" for a, b in PAIRS}
    if pf.get("x_axis") and f"{key}_pair" not in ss:
        ss[f"{key}_pair"] = f"{pf['x_axis']}|{pf['y_axis']}"
    pair = st.selectbox("Ejes (X × Y)", list(pair_lab), format_func=pair_lab.get, key=f"{key}_pair")
    xa, ya = pair.split("|")
    default_rng = {"j": dom["j_A_cm2"], "T": dom["temperature_K"], "P": dom["cathode_pressure_atm"],
                   "pH2": [0.5 * bv0["p_h2_atm"], 1.5 * bv0["p_h2_atm"]], "yO2": [0.15, 0.30]}
    c = st.columns(4)
    rng = {}
    for col, a in zip((c[0:2], c[2:4]), (xa, ya)):
        d0 = (pf.get("x_range") if a == xa else pf.get("y_range")) if pf.get("x_axis") == xa and pf.get("y_axis") == ya else None
        d0 = d0 or default_rng[a]
        lo = col[0].number_input(f"{a} mín [{AXES[a][1]}]", value=float(d0[0]), key=f"{key}_{pair}_{a}_lo", format="%.6g")
        hi = col[1].number_input(f"{a} máx [{AXES[a][1]}]", value=float(d0[1]), key=f"{key}_{pair}_{a}_hi", format="%.6g")
        rng[a] = [lo, hi]
    cal_txt = {"j": dom["j_A_cm2"], "T": dom["temperature_K"], "P": dom["cathode_pressure_atm"], "pH2": [bv0["p_h2_atm"]] * 2,
               "yO2": [bv0["oxygen_fraction"]] * 2}
    st.caption("Rango calibrado: " + " · ".join(f"{AXES[a][0]} {cal_txt[a][0]:g}–{cal_txt[a][1]:g} {AXES[a][1]}" for a in (xa, ya))
               + ". Fuera de él, las celdas se marcan como extrapoladas.")
    c = st.columns(3)
    nx = c[0].slider("Resolución X", 10, 300 if xa == "j" else 70, 120 if xa == "j" else 30, key=f"{key}_nx")
    ny = c[1].slider("Resolución Y", 5, 120 if xa == "j" else 70, 40 if xa == "j" else 20, key=f"{key}_ny")
    est = estimate(xa, nx, ny)
    msg = f"{est['cells']} celdas · ≈ {est['seconds']:.1f} s"
    (c[2].warning if est["seconds"] > 5 or not est["allowed"] else c[2].caption)(
        msg + ("" if est["allowed"] else f" · supera el máximo ({est['limit']})"))
    fixed = {}
    pff = pf.get("fixed") or {}
    for a in ("T", "P", "pH2", "yO2"):
        if a in (xa, ya):
            continue
        k = COND[a]
        if a in ("T", "P"):
            fixed[k] = pff.get(k) if pff.get(k) is not None else (cond or {}).get(k)
        else:
            fixed[k] = pff.get(k)
    with st.expander("Condiciones fijas (variables que no están en los ejes)", expanded=True):
        cc = st.columns(4)
        for i, a in enumerate(("T", "P", "pH2", "yO2")):
            if a in (xa, ya):
                cc[i].caption(f"{AXES[a][0]}: eje del mapa")
                continue
            k = COND[a]
            v = cc[i].number_input(f"{AXES[a][0]} [{AXES[a][1]}]", value=fixed[k], key=f"{key}_fx_{a}", format="%.6g",
                                   help="Vacío = valor del perfil (para p_H₂ e y_O₂)." if a in ("pH2", "yO2") else None)
            fixed[k] = v
        if xa == "T":
            fixed["j_A_cm2"] = cc[0].number_input("j fija [A/cm²] (magnitudes puntuales)", value=float(pf.get("fixed", {}).get("j_A_cm2") or
                                                  round(0.5 * (dom["j_A_cm2"][0] + dom["j_A_cm2"][1]), 4)), key=f"{key}_fx_j")
    _sec("Punto destacado")
    c = st.columns(3)
    obj = c[0].selectbox("Óptimo a destacar", ["max_potencia", "max_eficiencia", "min_consumo", "ninguno"],
                         format_func={"max_potencia": "Máxima potencia", "max_eficiencia": "Máxima eficiencia",
                                      "min_consumo": "Mínimo consumo específico", "ninguno": "Ninguno"}.get, key=f"{key}_obj")
    pmin = c[1].number_input("Potencia mínima útil [W]", min_value=0.0, value=None, key=f"{key}_pmin", format="%.6g",
                             help="Evita el óptimo trivial de eficiencia (mínima corriente). Igual que en la Bancada 04.")
    only = c[2].checkbox("Buscar el óptimo solo en el dominio calibrado", value=True, key=f"{key}_only")
    if any(fixed.get(COND[a]) is None for a in ("T", "P") if a not in (xa, ya)):
        st.warning("Indique las condiciones fijas de temperatura y presión.")
        return None
    return {"x_axis": xa, "y_axis": ya, "x_range": rng[xa], "y_range": rng[ya], "nx": nx, "ny": ny, "fixed": fixed,
            "limits": limits, "basis": basis, "objective": None if obj == "ninguno" else obj, "p_min_useful_W": pmin or None,
            "optimum_calibrated_only": only}


def render_map(r, key: str, ws=None, ex=None) -> None:
    from .motor2_view import _kpis, _layout, _sec
    s, inp = r.series, r.inputs
    _kpis(r)
    st.caption(" · ".join(h for h in r.hypotheses if h.startswith("Condiciones fijas") or h.startswith("Ejes")))
    qs = {k: v for k, v in {**QUANTITIES, **TP_EXTRA}.items() if s.get(k) is not None and k != "category"}
    c = st.columns([1.6, 1, 1, 1, 1])
    q = c[0].selectbox("Magnitud representada", list(qs), format_func=lambda k: f"{qs[k][0]} [{qs[k][1]}]",
                       index=list(qs).index("P_max" if "P_max" in qs else "P"), key=f"{key}_q")
    cont = c[1].toggle("Curvas de nivel", True, key=f"{key}_ct")
    regions = c[2].toggle("Regiones", True, key=f"{key}_rg")
    tested = c[3].toggle("Condiciones ensayadas", True, key=f"{key}_ts")
    opt_on = c[4].toggle("Óptimo", True, key=f"{key}_op")
    x, y = s["x"], s["y"]
    cat = np.array(s["category"])
    z = np.array([[np.nan if v is None else v for v in row] for row in s[q]], float)
    z = np.where(cat >= 1 if regions else cat >= 0, z, np.nan)
    f = go.Figure(go.Heatmap(x=x, y=y, z=z, colorscale="Viridis", colorbar=dict(title=qs[q][1]),
                             hovertemplate="x=%{x:.4g}<br>y=%{y:.4g}<br>valor=%{z:.5g}<extra></extra>"))
    if cont and np.isfinite(z).sum() > 4:
        f.add_trace(go.Contour(x=x, y=y, z=z, contours=dict(coloring="none", showlabels=True), line=dict(color="white", width=1),
                               showscale=False, hoverinfo="skip", name="Curvas de nivel"))
    if regions:
        for val, col, name in ((0, "rgba(120,120,120,0.55)", "No calculable"), (1, "rgba(209,73,91,0.45)", "Inadmisible"),
                               (2, "rgba(255,255,255,0.45)", "Extrapolado")):
            m = np.where(cat == val, 1.0, np.nan)
            if np.isfinite(m).any():
                f.add_trace(go.Heatmap(x=x, y=y, z=m, colorscale=[[0, col], [1, col]], showscale=False, name=name,
                                       hovertemplate=name + "<extra></extra>"))
    if tested:
        for t in s.get("tested") or []:
            if inp["y_axis"] in ("T", "P") and inp["x_axis"] == "j":
                yy = t["T"] if inp["y_axis"] == "T" else t["P"]
                f.add_hline(y=yy, line=dict(color="white", dash="dot", width=1))
            elif inp["x_axis"] == "T":
                f.add_trace(go.Scatter(x=[t["T"]], y=[t["P"]], mode="markers", marker=dict(color="white", size=9,
                                       line=dict(color="black", width=1)), name="Condición ensayada"))
    loc = [p for p in (s.get("locus") or []) if p.get("j") is not None]
    if opt_on and loc:
        f.add_trace(go.Scatter(x=[p["j"] for p in loc], y=[p["y"] for p in loc], mode="lines", name="Óptimo por fila (B04)",
                               line=dict(color="#e0891e", dash="dash", width=2)))
    opt = r.context.get("optimum")
    if opt_on and opt:
        f.add_trace(go.Scatter(x=[opt["x"]], y=[opt["y"]], mode="markers", name="Óptimo", marker=dict(symbol="star", size=18,
                               color="#d1495b", line=dict(color="white", width=1))))
    if opt_on and ws is not None and ex is not None and inp["x_axis"] == "j":
        b4 = [e for e in ws.device_experiments(ex.device_id) if e.bench == "optimizacion" and e.calibration_id == ex.calibration_id]
        for e in b4[:1]:
            cfg = (e.result.get("inputs") or {}).get("config") or {}
            yv = base_values(_profile_of(ws, e), cfg.get("cond") or {})[COND[inp["y_axis"]]] if cfg.get("cond") else None
            if yv is not None:
                sel = e.result["context"]["selected"]
                f.add_trace(go.Scatter(x=[sel["j_A_cm2"]], y=[yv], mode="markers", name=f"Bancada 04: {e.name[:30]}",
                                       marker=dict(symbol="diamond", size=13, color="#2f6fed", line=dict(color="white", width=1))))
    pt = _ss().get(f"{key}_pt")
    if pt:
        f.add_trace(go.Scatter(x=[pt[0]], y=[pt[1]], mode="markers", name="Punto seleccionado",
                               marker=dict(symbol="x", size=14, color="black")))
    gx, gy = np.meshgrid(x, y)
    step = max(1, int(np.ceil(np.sqrt(gx.size / 3000))))
    sx, sy = gx[::step, ::step], gy[::step, ::step]
    # Capa de selección: marcadores transparentes que cubren la malla. hoverinfo="none" (no "skip") para que
    # el clic genere el evento de selección; tamaño según la densidad de la malla para no dejar huecos.
    msize = int(np.clip(900 / max(sx.shape[1], 1), 8, 26))
    f.add_trace(go.Scatter(x=sx.ravel(), y=sy.ravel(), mode="markers", name="selección", showlegend=False,
                           marker=dict(size=msize, opacity=0.0, symbol="square"), hoverinfo="none"))
    f.update_layout(clickmode="event+select")
    f.update_layout(xaxis_title=f"{AXES[inp['x_axis']][0]} [{AXES[inp['x_axis']][1]}]",
                    yaxis_title=f"{AXES[inp['y_axis']][0]} [{AXES[inp['y_axis']][1]}]")
    ev = st.plotly_chart(_layout(f, 560, f"{qs[q][0]} [{qs[q][1]}]", legend=dict(orientation="h", y=-0.18)), width="stretch",
                         key=f"{key}_map", on_select="rerun", selection_mode=("points",))
    try:
        pts = ev.selection.points if ev and ev.selection else []
    except AttributeError:
        pts = []
    if pts:
        _ss()[f"{key}_pt"] = (float(pts[0]["x"]), float(pts[0]["y"]))
        st.rerun()
    st.caption("Leyenda de regiones: gris = no calculable (V ≤ 0) · rojo = inadmisible (límites documentados) · velo blanco = "
               "extrapolado (fuera de los rangos calibrados) · sin velo = dominio calibrado. Las celdas no calculables o "
               "inadmisibles no se rellenan. Pulse un punto del mapa para inspeccionarlo.")
    if opt:
        st.info(r.context.get("optimum_note", ""))
    st.dataframe(pd.DataFrame(r.tables["categorias"]), hide_index=True, width="stretch")
    _sec("Exploración de un punto (evaluación exacta, no interpolada)")
    cur = _ss().get(f"{key}_pt") or (x[len(x) // 2], y[len(y) // 2])
    c = st.columns([1, 1, 1.2, 1.4])
    px = c[0].number_input(f"{AXES[inp['x_axis']][0]}", value=float(cur[0]), key=f"{key}_px_{cur[0]}", format="%.6g")
    py = c[1].number_input(f"{AXES[inp['y_axis']][0]}", value=float(cur[1]), key=f"{key}_py_{cur[1]}", format="%.6g")
    if (px, py) != tuple(cur):
        _ss()[f"{key}_pt"] = (px, py)
    if ws is None or ex is None:
        return
    prof = _profile_of(ws, ex)
    try:
        det = point_details(prof, inp["x_axis"], inp["y_axis"], px, py, inp["fixed"], OperatingLimits.from_dict(inp["limits"]),
                            inp["basis"])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Punto no evaluable: {exc}")
        return
    cols = st.columns(4)
    for col, (lab, v, u) in zip(cols * 2, [("Corriente", det["I_A"], "A"), ("Tensión de celda", det["V_cell_V"], "V"),
                                           ("Potencia", det["P_W"], "W"), ("Eficiencia", 100 * det["eta"], "%"),
                                           ("H₂", det["H2_g_s"], "g/s"), ("SFC", det["SFC_g_kWh"], "g/kWh"),
                                           ("j", det["j_A_cm2"], "A/cm²"), ("Validez", None, det["category"])]):
        col.metric(lab, f"{v:.4g} {u}" if v is not None and np.isfinite(v) else u)
    st.caption("Condiciones: " + ", ".join(f"{k} = {v:g}" for k, v in det["conditions"].items() if v is not None)
               + (". Límites violados: " + ", ".join(det["violated_limits"]) if det["violated_limits"] else ". Sin límites violados."))
    c1, c2 = st.columns(2)
    cond = {k: v for k, v in det["conditions"].items()}
    if c1.button("Enviar a la Bancada 04 (potencia objetivo)", key=f"{key}_to04", width="stretch",
                 disabled=not np.isfinite(det["P_W"]) or det["P_W"] <= 0):
        _ss()["m2_prefill_optimizacion"] = {"cond": cond, "objective": "potencia_objetivo", "p_target_W": float(det["P_W"]),
                                            "limits": inp["limits"], "basis": inp["basis"], "_from_map": ex.id}
        _ss().m2["bench"] = "optimizacion"
        st.rerun()
    if c2.button("Guardar como escenario (Bancada 05)", key=f"{key}_to05", width="stretch"):
        _ss().setdefault("m2_scen_add", []).append({"name": f"Mapa ({px:.4g}, {py:.4g})", "active": True, **cond})
        st.success("Escenario añadido: se verá en la Bancada 05 → Comparación de escenarios.")


def _profile_of(ws, ex):
    return ws.calibrations[ex.calibration_id].profile if ex.calibration_id in ws.calibrations else None
