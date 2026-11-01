"""Capa de presentación común: componentes propios, CSS global, enrutado y estado de guardado."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from pemfc_core.schemas import APP_VERSION

from . import persistence

STATIC = Path(__file__).resolve().parent / "static"
_KIT = (STATIC / "ui_kit.css").read_text(encoding="utf-8")
VIEWS = ("home", "catalog", "device", "motor2", "digitizer", "about")
NAV_ITEMS = [("home", "Inicio"), ("catalog", "Motor 1"), ("motor2", "Motor 2"), ("digitizer", "Digitalizador"),
             ("about", "Alcance")]


def _asset(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def component(name: str):
    """Componente v2 local (JS + CSS del kit). Registrar en cada ejecución es inocuo."""
    return st.components.v2.component(f"pml_{name}", js=_asset(f"{name}.js"), css=_KIT + _asset(f"{name}.css"))


def payload(key: str, field: str = "action"):
    val = st.session_state.get(key)
    if val is None:
        return None
    try:
        return val.get(field) if hasattr(val, "get") else getattr(val, field, None)
    except Exception:  # noqa: BLE001
        return None


GLOBAL_CSS = """
<style>
/* La cabecera nativa de Streamlit (3,75 rem) es una franja fija y transparente sobre la página. Se reserva su
   altura para que la barra propia quede DEBAJO (solución estructural) y, además, la franja transparente deja de
   capturar toques: solo sus propios botones (menú, despliegue) siguen siendo interactivos. */
.block-container { padding-top: calc(3.75rem + 0.6rem) !important; padding-bottom: 5rem !important; max-width: 1360px; }
h1, h2, h3 { letter-spacing: -0.012em; }
[data-testid="stHeader"] { background: transparent; pointer-events: none; }
[data-testid="stHeader"] [data-testid="stToolbar"], [data-testid="stHeader"] button, [data-testid="stHeader"] a,
[data-testid="stHeader"] [role="button"] { pointer-events: auto; }
.pml-hero h1 { font-size: 1.85rem; margin: .4rem 0 .35rem 0; line-height: 1.15; }
.pml-hero p { max-width: 920px; opacity: .82; font-size: 1.02rem; margin: 0 0 .4rem 0; }
.m1-hero { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 1.5rem;
  padding: 1.15rem 1.4rem; margin: .35rem 0 .9rem 0; border-radius: 16px; overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--primary-color, #0E7C86) 22%, rgba(128,128,128,.25));
  background: linear-gradient(120deg, color-mix(in srgb, var(--primary-color, #0E7C86) 9%, transparent) 0%, transparent 62%); }
.m1-hero::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 4px; background: var(--primary-color, #0E7C86); }
.m1-text { min-width: 0; }
.m1-chip { display: inline-flex; align-items: center; gap: .45rem; font-size: .7rem; font-weight: 750; letter-spacing: .13em;
  color: var(--primary-color, #0E7C86); }
.m1-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 18%, transparent); }
.m1-hero h1 { font-size: clamp(1.45rem, 1.1rem + 1.4vw, 2.05rem); margin: .35rem 0 .3rem 0; line-height: 1.12; letter-spacing: -.02em; }
.m1-hero p { margin: 0; max-width: 760px; opacity: .8; font-size: 1rem; line-height: 1.5; }
.m1-art { flex: none; width: 210px; height: auto; color: var(--primary-color, #0E7C86); opacity: .9; }
@media (max-width: 720px) { .m1-art { display: none; } .m1-hero { padding: 1rem 1.1rem; } }
.pml-eyebrow { text-transform: uppercase; letter-spacing: .12em; font-size: .72rem; font-weight: 700; color: var(--primary-color, #0E7C86); }
.pml-section-title { font-size: 1.12rem; font-weight: 700; margin: .2rem 0 .1rem 0; }
.pml-muted { opacity: .72; font-size: .9rem; }
.pml-devhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: .55rem 1rem; margin: .5rem 0 .25rem 0; }
.pml-devhead h2 { margin: 0; font-size: 1.55rem; }
.pml-kv { font-size: .83rem; padding: .12rem .5rem; border-radius: .45rem; border: 1px solid rgba(128,128,128,.28); opacity: .9; }
.pml-mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: .8rem; }
div[data-testid="stVerticalBlockBorderWrapper"] { transition: box-shadow .2s ease; }
.pml-stagebox { animation: pmlfade .22s ease both; }
@keyframes pmlfade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) { .pml-stagebox { animation: none; } }
</style>
"""


def global_css() -> None:
    st.html(GLOBAL_CSS)


# --------------------------------------------------------------------------- enrutado (sobrevive a recargas)
def route() -> dict:
    ss = st.session_state
    if "route" not in ss:
        qp = st.query_params
        view = qp.get("view", "home")
        step = qp.get("step", "1")
        ss.route = {"view": view if view in VIEWS else "home", "device": qp.get("device"),
                    "draft": qp.get("draft"), "step": int(step) if str(step).isdigit() and 1 <= int(step) <= 6 else 1,
                    "panel": qp.get("panel", "flujo")}
        if ss.route["view"] not in VIEWS:
            ss.route["view"] = "home"
    return ss.route


def go(view: str, **kw) -> None:
    r = route()
    r["view"] = view
    for k in ("device", "draft", "step", "panel"):
        if k in kw:
            r[k] = kw[k]
    if view != "device":
        r.update(device=None, draft=None, step=1, panel="flujo")
    qp = {"view": view}
    if view == "device":
        qp.update({k: str(r[k]) for k in ("device", "draft", "step", "panel") if r.get(k)})
    st.query_params.clear()
    st.query_params.update(qp)


# --------------------------------------------------------------------------- barra superior
def _fmt_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return iso


def save_indicator() -> dict:
    s = persistence.status()
    txt = {
        "cargando": "Cargando espacio de trabajo…",
        "guardado": f"Guardado en este navegador{' · ' + _fmt_time(s.get('last_saved_utc')) if s.get('last_saved_utc') else ''}",
        "pendiente": f"Cambios sin guardar ({s['dirty']})",
        "guardando": "Guardando…",
        "conflicto": "Conflicto de guardado",
        "no_disponible": "Sin persistencia en el navegador",
    }.get(s["state"], s["state"])
    title = ("Persistencia local del navegador (IndexedDB): sobrevive a recargas; se pierde si se borran los datos del "
             "sitio; no se sincroniza entre equipos. Use «Exportar proyecto» para una copia independiente.")
    if s.get("message"):
        title = s["message"]
    return {"state": s["state"], "text": txt, "title": title}


def _on_topbar() -> None:
    a = payload("pml_topbar")
    if a and a.get("type") == "nav":
        go(a["view"])


def topbar() -> None:
    r = route()
    view = "catalog" if r["view"] == "device" else r["view"]
    component("topbar")(key="pml_topbar", data={"version": APP_VERSION, "view": view, "route_view": r["view"], "items": NAV_ITEMS,
                                                "save": save_indicator()}, on_action_change=_on_topbar)
    s = persistence.status()
    if s["state"] in ("conflicto", "no_disponible") and s.get("message"):
        c1, c2 = st.columns([6, 1])
        (c1.error if s["state"] == "conflicto" else c1.warning)(s["message"])
        if s["state"] == "conflicto":
            c2.button("Entendido", key="ack_conflict", on_click=persistence.acknowledge_conflicts)
    if s.get("load_problems"):
        with st.expander(f"⚠ {len(s['load_problems'])} registro(s) del navegador no se pudieron cargar"):
            st.write("\n".join(f"- {p}" for p in s["load_problems"]))
