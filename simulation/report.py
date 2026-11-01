"""Exportación de experimentos del Motor 2: CSV, XLSX, JSON, PNG/SVG, informe PDF y ZIP reproducible."""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from pemfc_core import model as core  # noqa: E402
from pemfc_core.schemas import APP_VERSION  # noqa: E402

from .benches import BENCHES, OBJECTIVES, POLICIES, BenchResult  # noqa: E402

C = {"dem": "#7a8796", "del": "#0f8b8d", "avail": "#e0891e", "def": "#d1495b", "v": "#2f6fed", "i": "#7a4fd1",
     "h2": "#3c9d5d", "h2b": "#0f8b8d", "eta": "#7a4fd1", "obs": "#1d2433", "sel": "#d1495b"}
plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.25, "axes.spines.top": False,
                     "axes.spines.right": False, "figure.dpi": 110})


def _a(s, k):
    return np.array([np.nan if v is None else v for v in s[k]], float)


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("_")[:60] or "experimento"


# ===================================================================================================== figuras
def figures(r: BenchResult) -> dict[str, plt.Figure]:
    s, figs = r.series, {}
    if r.bench == "reproduccion":
        geo = r.context.get("geometry")
        f1, ax = plt.subplots(figsize=(7, 4.2))
        f3, ax3 = plt.subplots(figsize=(7, 3.2))
        f2, ax2 = (plt.subplots(figsize=(7, 4.2)) if geo else (None, None))
        for k, (cid, d) in enumerate(s.items()):
            col = plt.cm.tab10(k % 10)
            ax.plot(d["j_obs"], d["V_obs"], "o", ms=3, color=col, alpha=0.75, label=f"{cid} exp.")
            ax.plot(d["j_curve"], d["V_curve"], "-", color=col, lw=1.6, label=f"{cid} modelo")
            ax3.plot(d["j_obs"], np.array(d["residual_V"]) * 1000, "o", ms=3, color=col, label=cid)
            if geo:
                ax2.plot(d["I_obs_A"], d["P_obs_W"], "o", ms=3, color=col, alpha=0.75)
                ax2.plot(d["I_curve_A"], d["P_curve_W"], "-", color=col, lw=1.6, label=cid)
        ax.set(xlabel="j [A/cm²]", ylabel="V celda [V]", title="Curva V–I: experimental frente a modelo")
        ax.legend(fontsize=7, ncol=2)
        ax3.axhline(0, color="k", lw=0.8)
        ax3.set(xlabel="j [A/cm²]", ylabel="Residuo V_modelo − V_exp [mV]", title="Residuos")
        figs["VI"], figs["residuos"] = f1, f3
        if geo:
            ax2.set(xlabel="I stack [A]", ylabel="P stack [W]", title="Curva P–I (N·V·I)")
            ax2.legend(fontsize=7)
            figs["PI"] = f2
    elif r.bench == "carga":
        t = _a(s, "t_s")
        tu, tl = (t / 60, "t [min]") if t[-1] > 600 else (t, "t [s]")
        f, axs = plt.subplots(4, 1, figsize=(7.5, 8.6), sharex=True)
        axs[0].plot(tu, _a(s, "P_dem_W"), color=C["dem"], lw=1.4, label="Demandada")
        axs[0].plot(tu, _a(s, "P_del_W"), color=C["del"], lw=1.6, label="Entregada (restringida)")
        axs[0].plot(tu, _a(s, "P_del_W_ideal"), "--", color=C["del"], lw=0.9, alpha=0.6, label="Entregada (ideal)")
        axs[0].plot(tu, _a(s, "P_avail_W"), ":", color=C["avail"], lw=1.4, label="Disponible")
        axs[0].fill_between(tu, _a(s, "P_del_W"), _a(s, "P_dem_W"), where=_a(s, "deficit_W") > 0, color=C["def"], alpha=0.2,
                            label="Déficit")
        axs[0].set(ylabel="P [W]")
        axs[0].legend(fontsize=7, ncol=3)
        axs[1].fill_between(tu, 0, _a(s, "deficit_W"), color=C["def"], alpha=0.5)
        axs[1].set(ylabel="Déficit [W]")
        axs[2].plot(tu, _a(s, "V_stack_V"), color=C["v"])
        axs[2].set_ylabel("V stack [V]", color=C["v"])
        b = axs[2].twinx()
        b.plot(tu, _a(s, "I_A"), color=C["i"])
        b.set_ylabel("I [A]", color=C["i"])
        axs[3].plot(tu, _a(s, "H2_g_s"), color=C["h2"])
        axs[3].set_ylabel("H₂ [g/s]", color=C["h2"])
        b = axs[3].twinx()
        b.plot(tu, _a(s, "H2_cum_g"), color=C["h2b"], ls="--")
        b.set_ylabel("H₂ acumulado [g]", color=C["h2b"])
        axs[3].set_xlabel(tl)
        for a_ in list(axs) + [x_ for x_ in f.axes if x_ not in axs]:
            a_.set_ylim(bottom=0)
        f.suptitle("Seguimiento de carga (cuasiestacionario)")
        f.tight_layout()
        figs["seguimiento"] = f
        g, ax = plt.subplots(figsize=(7.5, 2.8))
        ax.plot(tu, 100 * _a(s, "eta"), color=C["eta"])
        ax.set(xlabel=tl, ylabel="η [%]", title="Eficiencia (H₂ consumido; no definida con P = 0)")
        figs["eficiencia"] = g
    elif r.bench == "hidrogeno":
        t = _a(s, "t_s")
        tu, tl = (t / 60, "t [min]") if t[-1] > 600 else (t, "t [s]")
        f, axs = plt.subplots(3, 1, figsize=(7.5, 7.4), sharex=True)
        axs[0].plot(tu, _a(s, "H2_fed_g_s"), color=C["dem"], lw=1.6, label="Alimentado")
        axs[0].plot(tu, _a(s, "H2_cons_g_s"), color=C["h2"], lw=1.6, label="Consumido (faradaico)")
        axs[0].set(ylabel="H₂ [g/s]")
        axs[0].legend(fontsize=7)
        axs[1].plot(tu, _a(s, "H2_fed_cum_g"), color=C["dem"], label="Alimentado acumulado")
        axs[1].plot(tu, _a(s, "H2_cons_cum_g"), color=C["h2"], label="Consumido acumulado")
        axs[1].set(ylabel="H₂ [g]")
        axs[1].legend(fontsize=7)
        axs[2].plot(tu, _a(s, "P_W"), color=C["del"])
        axs[2].set_ylabel("P [W]", color=C["del"])
        b = axs[2].twinx()
        b.plot(tu, _a(s, "I_A"), color=C["i"])
        b.set_ylabel("I [A]", color=C["i"])
        axs[2].set_xlabel(tl)
        for a_ in f.axes:
            a_.set_ylim(bottom=0)
        f.suptitle("Alimentación de hidrógeno")
        f.tight_layout()
        figs["hidrogeno"] = f
        g, ax = plt.subplots(figsize=(7.5, 2.8))
        ax.plot(tu, 100 * _a(s, "utilization"), color=C["h2"], label="Utilización")
        ax.plot(tu, 100 * _a(s, "eta_cons"), color=C["eta"], label="η (consumido)")
        ax.plot(tu, 100 * _a(s, "eta_fed"), "--", color=C["eta"], label="η (alimentado)")
        ax.set(xlabel=tl, ylabel="[%]")
        ax.legend(fontsize=7)
        figs["utilizacion"] = g
    elif r.bench == "optimizacion":
        j, p, eta, feas = _a(s, "j_A_cm2"), _a(s, "P_W"), _a(s, "eta"), np.array(s["feasible"], bool)
        sel = r.context["selected"]
        f, ax = plt.subplots(figsize=(7.5, 4.2))
        ax.plot(j, p, color=C["del"], lw=1.8, label="P(j)")
        ax.fill_between(j, 0, p.max() * 1.05, where=~feas, color="#888", alpha=0.12, label="No admisible")
        ax.set(xlabel="j [A/cm²]", ylabel="P [W]")
        b = ax.twinx()
        b.plot(j, 100 * eta, color=C["eta"], lw=1.4, label="η(j)")
        b.set_ylabel("η [%]", color=C["eta"])
        ax.axvline(sel["j_A_cm2"], color=C["sel"], ls="--")
        ax.plot([sel["j_A_cm2"]], [sel["P_W"]], "o", color=C["sel"], ms=8, label="Seleccionado")
        ax.legend(fontsize=7, loc="upper left")
        ax.set_title(OBJECTIVES[r.inputs["objective"]])
        figs["P_eta_j"] = f
        g, ax = plt.subplots(figsize=(6.5, 4))
        ax.plot(p[feas], 100 * eta[feas], color="#9aa5b1", lw=1, label="Admisibles")
        fr = s.get("frontier_idx") or []
        if fr:
            ax.plot(p[fr], 100 * eta[fr], color=C["del"], lw=2.2, label="Frontera de Pareto")
        ax.plot([sel["P_W"]], [100 * sel["eta"]], "o", color=C["sel"], ms=8, label="Seleccionado")
        ax.set(xlabel="P [W]", ylabel="η [%]", title="Compromiso potencia–eficiencia")
        ax.legend(fontsize=7)
        figs["pareto"] = g
    return figs


def fig_bytes(fig, fmt: str = "png") -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format=fmt, bbox_inches="tight", dpi=150 if fmt == "png" else None)
    return buf.getvalue()


# ===================================================================================================== tablas
def data_frame(r: BenchResult) -> pd.DataFrame:
    if r.bench == "reproduccion":
        return pd.DataFrame(r.tables["comparacion"])
    s = {k: v for k, v in r.series.items() if isinstance(v, list) and k != "frontier_idx"}
    n = max(len(v) for v in s.values())
    return pd.DataFrame({k: v for k, v in s.items() if len(v) == n})


def to_csv(r: BenchResult) -> bytes:
    return data_frame(r).to_csv(index=False, float_format="%.17g").encode("utf-8")


def to_xlsx(r: BenchResult, record: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame([{"indicador": k["label"], "valor": k["value"], "unidad": k["unit"], "definición": k["definition"]}
                      for k in r.kpis]).to_excel(xw, sheet_name="Indicadores", index=False)
        data_frame(r).to_excel(xw, sheet_name="Datos", index=False)
        if r.events:
            pd.DataFrame(r.events).to_excel(xw, sheet_name="Eventos", index=False)
        for name, rows in r.tables.items():
            if rows:
                pd.DataFrame(rows).to_excel(xw, sheet_name=name[:31].capitalize(), index=False)
        pd.DataFrame({"tipo": ["hipótesis"] * len(r.hypotheses) + ["advertencia"] * len(r.warnings),
                      "texto": r.hypotheses + r.warnings}).to_excel(xw, sheet_name="Hipótesis y advertencias", index=False)
        tr = [("experimento", record.get("id")), ("nombre", record.get("name")), ("bancada", BENCHES[r.bench]),
              ("dispositivo", record.get("device_id")), ("calibración", record.get("calibration_id")),
              ("perfil", record.get("profile_id")), ("fecha (UTC)", record.get("created_utc")),
              ("aplicación", f"PEMFC ModelLab {record.get('app_version') or APP_VERSION}"),
              ("modelo", f"{core.MODEL_ID} {core.MODEL_VERSION}"), ("validez", r.validity),
              ("huella del experimento", record.get("content_sha256")),
              ("entradas (JSON)", json.dumps(_short_inputs(r.inputs), ensure_ascii=False)[:32000])]
        pd.DataFrame(tr, columns=["campo", "valor"]).to_excel(xw, sheet_name="Trazabilidad", index=False)
    return buf.getvalue()


def _short_inputs(inputs: dict) -> dict:
    out = {}
    for k, v in inputs.items():
        if isinstance(v, dict) and "t_s" in v:
            out[k] = {kk: vv for kk, vv in v.items() if kk not in ("t_s", "values")} | {"n_puntos": len(v["t_s"])}
        else:
            out[k] = v
    return out


# ===================================================================================================== interpretación
def interpretation(r: BenchResult) -> tuple[list[str], list[str]]:
    """Interpretación y conclusiones PRUDENTES, derivadas solo de los indicadores calculados."""
    k = {x["key"]: x["value"] for x in r.kpis}
    it, cc = [], []
    hedge = ("Las conclusiones dependen de las hipótesis declaradas (modelo cuasiestacionario, perfil "
             f"{r.context.get('model', {}).get('status') or r.context.get('evaluation_kind', '')}).")
    if r.bench == "reproduccion":
        it.append(f"El modelo reproduce los {int(k['n'])} puntos con RMSE {1000 * k['rmse_V']:.2f} mV/celda, sesgo "
                  f"{1000 * k['bias_V']:+.2f} mV y error máximo {1000 * k['max_abs_V']:.2f} mV.")
        if r.context.get("consistent_with_motor1"):
            it.append("Los indicadores coinciden exactamente con los registrados por el Motor 1 (misma implementación).")
        kind = r.context.get("evaluation_kind", "")
        cc.append("Se trata de una " + kind.lower() + "." + (" No constituye validación independiente: un buen ajuste "
                  "sobre datos de calibración no demuestra capacidad predictiva." if "CALIBRACIÓN" in kind else ""))
    elif r.bench == "carga":
        it.append(f"Se demandaron {k['E_dem']:.4g} kWh y se entregaron {k['E_del']:.4g} kWh "
                  f"({k['pct_energy']:.1f} % de la energía); quedaron sin atender {k['E_uns']:.4g} kWh.")
        it.append(f"La potencia estacionaria disponible es {k['P_avail']:.4g} W; la demanda máxima fue {k['P_dem_max']:.4g} W.")
        if k.get("eta_energy") is not None:
            it.append(f"Eficiencia media ponderada por energía {k['eta_energy']:.1f} % (stack, LHV/HHV según se indica, sin BoP); "
                      f"consumo teórico de H₂ {k['H2_g']:.4g} g.")
        nd = int(k.get("n_deficit_events") or 0)
        cc.append(("El dispositivo, según el modelo, NO cubre todo el perfil: " + f"{nd} evento(s) de déficit." if nd else
                   "Según el modelo estacionario, la capacidad del dispositivo cubre el perfil de demanda.")
                  + (" Sin límites de rampa documentados, no se evalúa la capacidad dinámica." if k.get("n_ramp_events") is None else ""))
    elif r.bench == "hidrogeno":
        it.append(f"Se alimentaron {k['H2_fed_g']:.4g} g de H₂ y se consumieron electroquímicamente {k['H2_cons_g']:.4g} g "
                  f"(utilización global {k['u_mean']:.1f} %); {k['H2_excess_g']:.4g} g salen sin reaccionar.")
        it.append(f"Energía producida {k['E_prod']:.4g} kWh; η referida al H₂ consumido {k['eta_cons']:.1f} % y al "
                  f"alimentado {k['eta_fed']:.1f} %.")
        if (k.get("t_fuel_limited_s") or 0) > 0:
            cc.append(f"La operación estuvo limitada por combustible durante {k['t_fuel_limited_s']:.4g} s: la política no "
                      "puede cumplirse con ese caudal.")
        else:
            cc.append("El caudal alimentado no limitó la política de operación en el horizonte simulado.")
    elif r.bench == "optimizacion":
        sel = r.context["selected"]
        it.append(r.context.get("explanation", ""))
        it.append(f"Punto seleccionado: j = {sel['j_A_cm2']:.4g} A/cm², I = {sel['I_A']:.4g} A, P = {sel['P_W']:.4g} W, "
                  f"η = {100 * sel['eta']:.1f} %, SFC = {sel['SFC_g_kWh']:.4g} g/kWh.")
        act = r.context.get("active_constraints") or []
        cc.append("Restricciones activas: " + (", ".join(act) if act else "ninguna (óptimo interior)") + ".")
    cc.append(hedge)
    if r.validity != "VALIDO":
        cc.append(f"Estado de validez: {r.validity}. Revise las advertencias antes de usar estos resultados.")
    return it, cc


# ===================================================================================================== informe PDF
def report_pdf(r: BenchResult, record: dict, profile: dict | None = None, figs: dict | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    teal = colors.HexColor("#0f8b8d")
    ss = getSampleStyleSheet()
    H1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=colors.HexColor("#1d2433"), fontSize=17, spaceAfter=6)
    H2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=teal, fontSize=12, spaceBefore=10, spaceAfter=4)
    B = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.8, leading=11.5, alignment=TA_LEFT)
    S = ParagraphStyle("s", parent=B, fontSize=7.6, leading=9.6, textColor=colors.HexColor("#4a5568"))

    def esc(x):
        return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def table(rows, widths, header=True):
        t = Table([[Paragraph(esc(c), S if i else ParagraphStyle("th", parent=S, textColor=colors.white)) for c in row]
                   for i, row in enumerate(rows)], colWidths=widths, repeatRows=1 if header else 0)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), teal if header else colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e0")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")])]))
        return t

    figs = figs if figs is not None else figures(r)
    dev = (profile or {}).get("device") or r.context.get("device") or r.context.get("model", {}).get("device") or {}
    story = [Paragraph("PEMFC ModelLab · Motor 2 — Laboratorio Virtual", S),
             Paragraph(f"Informe técnico: {esc(BENCHES[r.bench])}", H1),
             Paragraph(f"<b>{esc(record.get('name', ''))}</b> · experimento {esc(record.get('id', '—'))} · "
                       f"{esc(record.get('created_utc', ''))} · validez <b>{esc(r.validity)}</b>", B)]
    story += [Paragraph("1. Identificación del dispositivo", H2),
              table([["Campo", "Valor"], ["Nombre", dev.get("name", "—")], ["Fabricante / modelo",
                     f"{dev.get('manufacturer') or '—'} / {dev.get('model') or '—'}"],
                     ["N celdas", f"{dev.get('n_cells')} ({dev.get('n_cells_origin')})"],
                     ["Área activa", f"{dev.get('active_area_cm2')} cm² ({dev.get('active_area_origin')})"],
                     ["Perfil calibrado", f"{record.get('profile_id')} · {(profile or {}).get('status', {}).get('code', '')}"]],
                    [4.5 * cm, 12 * cm])]
    obj = {"reproduccion": "Reproducir con el modelo identificado el experimento de calibración y cuantificar el ajuste.",
           "carga": "Estudiar la respuesta cuasiestacionaria del stack ante un perfil de demanda eléctrica variable.",
           "hidrogeno": "Estudiar la operación cuando el caudal de H₂ alimentado es una condición de entrada.",
           "optimizacion": "Encontrar un punto de operación según el criterio: "
                           + OBJECTIVES.get(r.inputs.get("objective", ""), "")}[r.bench]
    story += [Paragraph("2. Objetivo del experimento", H2), Paragraph(esc(obj), B),
              Paragraph("3. Condiciones de entrada", H2)]
    inp = _short_inputs(r.inputs)
    story.append(table([["Entrada", "Valor"]] + [[k, json.dumps(v, ensure_ascii=False)[:400]] for k, v in inp.items()],
                       [4.5 * cm, 12 * cm]))
    story += [Paragraph("4. Modelo matemático utilizado", H2),
              Paragraph(esc(f"{core.MODEL_ID} {core.MODEL_VERSION} (núcleo pemfc_core del Motor 1, sin modificaciones). "
                            "V_celda = E_Nernst − V_act − V_óhm − V_conc (recortada a ≥ 0); I = j·A; P = N·V_celda·I; "
                            "ṅ_H₂ = N·I/(2F); η = P/(ṅ_H₂·PCI). Parámetros del perfil calibrado:"), B)]
    params = (profile or {}).get("parameters") or r.context.get("parameters") or r.context.get("model", {}).get("parameters") or []
    if params:
        story.append(table([["Parámetro", "Símbolo", "Valor", "Unidad", "Origen"]] +
                           [[q.get("name"), q.get("symbol"), f"{q.get('value'):.6g}" if isinstance(q.get("value"), (int, float)) else q.get("value"),
                             q.get("unit"), q.get("origin")] for q in params],
                           [5 * cm, 2.2 * cm, 3 * cm, 2.3 * cm, 4 * cm]))
    story += [Paragraph("5. Hipótesis y limitaciones", H2)] + [Paragraph("• " + esc(h), B) for h in r.hypotheses]
    story += [Paragraph("Limitaciones generales: modelo cuasiestacionario; sin dinámica de gases, térmica ni de "
                        "humidificación; sin degradación; sin auxiliares (BoP) ni electrónica de potencia.", S), PageBreak(),
              Paragraph("6. Resultados gráficos", H2)]
    for name, f in figs.items():
        png = fig_bytes(f, "png")
        img = Image(io.BytesIO(png))
        w = 16.5 * cm
        img.drawWidth, img.drawHeight = w, w * img.imageHeight / img.imageWidth
        story += [KeepTogether([img, Paragraph(f"Figura: {esc(name)}", S), Spacer(1, 6)])]
    story += [Paragraph("7. Indicadores cuantitativos", H2),
              table([["Indicador", "Valor", "Unidad", "Definición"]] +
                    [[k["label"], "—" if k["value"] is None else f"{k['value']:.6g}", k["unit"], k["definition"]] for k in r.kpis],
                    [4.6 * cm, 2.6 * cm, 1.6 * cm, 7.7 * cm])]
    story += [Paragraph("8. Eventos y advertencias", H2)] + [Paragraph("⚠ " + esc(w), B) for w in r.warnings]
    if r.events:
        story.append(table([["Evento", "Inicio [s]", "Fin [s]", "Magnitud", "Consecuencia"]] +
                           [[e["type"], f"{e['t_start_s']:.4g}", f"{e['t_end_s']:.4g}",
                             f"{e['max_magnitude']:.4g} {e['unit']}", e.get("consequence", "")] for e in r.events[:60]],
                           [3.6 * cm, 1.8 * cm, 1.8 * cm, 2.6 * cm, 6.7 * cm]))
    elif not r.warnings:
        story.append(Paragraph("Sin eventos ni advertencias.", B))
    it, cc = interpretation(r)
    story += [Paragraph("9. Interpretación de resultados", H2)] + [Paragraph(esc(x), B) for x in it]
    story += [Paragraph("10. Conclusiones sustentadas por los datos", H2)] + [Paragraph("• " + esc(x), B) for x in cc]
    story += [Paragraph("11. Información de trazabilidad", H2),
              table([["Campo", "Valor"], ["Experimento", record.get("id")], ["Huella SHA-256", record.get("content_sha256")],
                     ["Dispositivo", record.get("device_id")], ["Calibración", record.get("calibration_id")],
                     ["Perfil", record.get("profile_id")], ["Aplicación", f"PEMFC ModelLab {record.get('app_version') or APP_VERSION}"],
                     ["Modelo", f"{core.MODEL_ID} {core.MODEL_VERSION}"], ["Duplicado de", record.get("duplicated_from") or "—"],
                     ["Generado (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]], [4.5 * cm, 12 * cm])]
    buf = io.BytesIO()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#718096"))
        canvas.drawString(2 * cm, 1.2 * cm, f"PEMFC ModelLab {APP_VERSION} · Motor 2 · {record.get('id', '')} · simulación "
                                            "cuasiestacionaria: no es una medición experimental")
        canvas.drawRightString(19 * cm, 1.2 * cm, f"pág. {doc.page}")
        canvas.restoreState()

    SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm,
                      title=f"Informe {BENCHES[r.bench]}", author="PEMFC ModelLab").build(story, onFirstPage=footer,
                                                                                           onLaterPages=footer)
    return buf.getvalue()


# ===================================================================================================== ZIP
def experiment_zip(record: dict, profile: dict | None = None) -> bytes:
    r = BenchResult.from_dict(record["result"])
    figs = figures(r)
    stem = _safe(record.get("name") or record.get("id", "experimento"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEEME.txt", (
            f"PEMFC ModelLab {APP_VERSION} — Motor 2 · {BENCHES[r.bench]}\nExperimento: {record.get('name')} ({record.get('id')})\n"
            f"Perfil: {record.get('profile_id')} · validez: {r.validity}\n\n"
            "experimento.json : registro completo (entradas, hipótesis, indicadores, series, eventos) — permite reconstruir "
            "todos los gráficos.\ndatos.csv / datos.xlsx : series y tablas.\nfiguras/ : PNG y SVG.\ninforme.pdf : informe "
            "técnico.\nperfil.json : perfil calibrado usado (para reproducir la simulación).\n\nResultados de un modelo "
            "cuasiestacionario: no sustituyen mediciones experimentales.\n"))
        z.writestr("experimento.json", json.dumps(record, ensure_ascii=False, indent=1, allow_nan=False, default=_json_default))
        z.writestr("datos.csv", to_csv(r))
        z.writestr("datos.xlsx", to_xlsx(r, record))
        for name, f in figs.items():
            z.writestr(f"figuras/{name}.png", fig_bytes(f, "png"))
            z.writestr(f"figuras/{name}.svg", fig_bytes(f, "svg"))
        z.writestr("informe.pdf", report_pdf(r, record, profile, figs))
        if profile is not None:
            z.writestr("perfil.json", json.dumps(profile, ensure_ascii=False, indent=1))
    for f in figs.values():
        plt.close(f)
    return buf.getvalue()


def _json_default(o):
    if isinstance(o, float) and not math.isfinite(o):
        return None
    raise TypeError(type(o))


def study_zip(records: list[dict], skipped: list[dict], profiles: dict[str, dict]) -> bytes:
    """Estudio completo: un subdirectorio por experimento + resumen integrado."""
    buf = io.BytesIO()
    rows = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rec in records:
            r = BenchResult.from_dict(rec["result"])
            folder = f"{rec['bench']}_{_safe(rec['name'])}"
            z.writestr(f"{folder}.zip", experiment_zip(rec, profiles.get(rec["profile_id"])))
            rows.append({"bancada": BENCHES[r.bench], "experimento": rec["name"], "estado": "ejecutada",
                         "validez": r.validity, "advertencias": len(r.warnings), "eventos": len(r.events),
                         **{k["label"] + (f" [{k['unit']}]" if k["unit"] else ""): k["value"] for k in r.kpis[:6]}})
        for s in skipped:
            rows.append({"bancada": BENCHES.get(s["bench"], s["bench"]), "experimento": "—", "estado": "omitida",
                         "validez": "NO_EJECUTABLE", "motivo": s["reason"]})
        df = pd.DataFrame(rows)
        z.writestr("resumen_estudio.csv", df.to_csv(index=False))
        x = io.BytesIO()
        df.to_excel(x, index=False)
        z.writestr("resumen_estudio.xlsx", x.getvalue())
        z.writestr("LEEME.txt", "Estudio completo del Motor 2: un ZIP por bancada ejecutada (con su informe PDF) y un "
                                "resumen integrado. Las bancadas omitidas indican el motivo; nunca se ejecutan con datos "
                                "inventados.\n")
    return buf.getvalue()
