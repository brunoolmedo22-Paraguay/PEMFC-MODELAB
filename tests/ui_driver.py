"""Auxiliar de pruebas AppTest para el flujo por etapas de v0.3.0.

Crea un dispositivo y un borrador en el espacio de trabajo de la sesión y abre su espacio de trabajo;
``goto`` cambia de etapa como lo haría el indicador de progreso. Los widgets que se ejercitan son los
reales de cada etapa.
"""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def new_app():
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    assert not at.exception, at.exception
    return at


def open_workspace(step: int = 2, name: str = "Stack de prueba", **device_fields):
    at = new_app()
    ws = at.session_state.ws
    d = ws.create_device(name, **device_fields)
    dr = ws.new_draft(d.id)
    at.session_state.route = {"view": "device", "device": d.id, "draft": dr.id, "step": step, "panel": "flujo"}
    at.run()
    assert not at.exception, at.exception
    return at


def goto(at, step: int):
    at.session_state.route = {**at.session_state.route, "step": step}
    at.run()
    assert not at.exception, at.exception
    return at


def button(at, label):
    return next(b for b in at.button if b.label == label)
