"""Flujos de la interfaz Streamlit de extremo a extremo (A01, A07, A09, A11, A12) sobre el flujo por etapas v0.3.0.

Los casos científicos de v0.1/v0.2 se conservan; cambia solo la navegación (etapas 01–06 en lugar de pestañas).
"""
from ui_driver import button, goto, new_app, open_workspace

STACK_CSV = "corriente_A;tension_stack_V\n" + "\n".join(
    f"{i};{v}" for i, v in [(2.5, 18.4), (5, 17.6), (10, 16.9), (15, 16.4), (20, 15.95), (25, 15.5),
                            (30, 15.05), (35, 14.55), (40, 13.95), (45, 13.2)])


def _paste(at, csv, sep=";"):
    at.radio(key="src_mode").set_value("Pegar datos CSV").run()
    at.selectbox(key="csv_sep").set_value(sep).run()
    at.text_area(key="csv_text").set_value(csv).run()


def _otekon_configured(at):
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_otekon").click().run()
    goto(at, 3)
    button(at, "Preset OTEKON (9 parámetros, reproducción del artículo)").click().run()


# --------------------------------------------------------------------------- catálogo y dispositivos
def test_home_is_default_and_navigates_to_both_engines():
    at = new_app()
    assert at.session_state.route["view"] == "home" and not at.exception
    html = " ".join(h.proto.body for h in at.get("html"))
    assert "Bienvenido a PEMFC ModelLab" in html and "¿Qué deseas hacer hoy?" in html
    assert [t.label for t in at.tabs] == ["Acerca de ModelLab", "Motor 1", "Motor 2", "Modelo implementado"]
    assert len(at.get("latex")) >= 7                                       # ecuaciones del modelo implementado
    button(at, "Acceder al Motor 2 →").click().run()
    assert at.session_state.route["view"] == "motor2" and not at.exception
    html = " ".join(h.proto.body for h in at.get("html"))
    assert "Motor 2 — Laboratorio Virtual" in html                      # v0.4.0: laboratorio real
    assert any("perfil calibrado utilizable" in i.value for i in at.info)  # sin dispositivos: lo indica, no simula
    button(at, "Ir al Motor 1").click().run()
    assert at.session_state.route["view"] == "catalog" and not at.exception
    at.session_state.route = {**at.session_state.route, "view": "home"}
    at.run()
    button(at, "Acceder al Motor 1 →").click().run()
    assert at.session_state.route["view"] == "catalog" and not at.exception


def test_model_section_matches_code_parameters():
    from pemfc_core.parameters import PARAMETER_INFO
    at = new_app()
    df = next(d for d in at.dataframe if "identificable" in d.value.columns).value
    assert list(df["parámetro"]) == list(PARAMETER_INFO)                   # tabla generada desde el código
    assert set(df.loc[df["identificable"] == "sí", "parámetro"]) == {n for n, i in PARAMETER_INFO.items() if i.fittable}


def test_catalog_welcome_and_empty_state():
    at = new_app()
    at.session_state.route = {**at.session_state.route, "view": "catalog"}
    at.run()
    html = " ".join(h.proto.body for h in at.get("html"))
    assert "Bienvenido al Motor 1" in html and "MOTOR 1 · IDENTIFICACIÓN Y CALIBRACIÓN" in html
    assert "modelos digitales calibrados y reproducibles" in html
    assert at.session_state.route["view"] == "catalog" and at.session_state.ws.devices == {}


def test_create_device_dialog_requires_only_name():
    at = new_app()
    at.session_state.route = {**at.session_state.route, "view": "catalog"}
    at.session_state.show_new_device = True
    at.run()
    assert button(at, "Crear dispositivo").disabled
    at.text_input(key="nd_name").set_value("Stack nuevo").run()
    button(at, "Crear dispositivo").click().run()
    assert not at.exception
    (dev,) = at.session_state.ws.devices.values()
    assert dev.name == "Stack nuevo" and dev.manufacturer == "" and dev.n_cells is None
    r = at.session_state.route
    assert r["view"] == "device" and r["device"] == dev.id and r["step"] == 1


def test_step1_edits_device_and_keeps_stable_id():
    at = open_workspace(step=1, name="Original")
    dev = next(iter(at.session_state.ws.devices.values()))
    at.text_input(key="d1_name").set_value("Renombrado").run()
    at.number_input(key="d1_n_cells").set_value(20).run()
    at.number_input(key="d1_area").set_value(50.0).run()
    button(at, "Guardar cambios del dispositivo").click().run()
    assert not at.exception and any("actualizado" in s.value for s in at.success)
    d2 = at.session_state.ws.devices[dev.id]
    assert d2.name == "Renombrado" and d2.n_cells == 20 and d2.active_area_cm2 == 50.0
    assert any("datasheet" in t.label for t in at.text_input)


def test_initial_render_and_guards():
    at = open_workspace(step=2)
    texts = " ".join(i.value for i in at.info)
    assert "Sin curva V–I no es posible crear un perfil" in texts
    at.radio(key="src_mode").set_value("Imagen de una curva").run()
    assert not any("no está implementada" in w.value for w in at.warning)
    assert any(b.label == "Abrir digitalizador" for b in at.button)
    goto(at, 4)                                     # bloqueada: redirige a la última etapa accesible
    assert at.session_state.route["step"] <= 3


# --------------------------------------------------------------------------- casos científicos (conservados)
def test_otekon_example_full_flow_records_immutable_calibrations():
    at = open_workspace(step=2, name="Dispositivo OTEKON")
    _otekon_configured(at)
    assert len(at.session_state.curves) == 4
    goto(at, 4)
    at.button(key="run_fit").click().run()
    assert not at.exception
    r = at.session_state.fit_result
    assert r.status == "AJUSTADO_A_CURVA" and abs(r.metrics_global["rmse_V"] - 0.0014113700033) < 1e-6
    ws = at.session_state.ws
    (cal1,) = ws.calibrations.values()
    assert cal1.status_code == "AJUSTADO_A_CURVA" and at.session_state.profile is not None
    (ds,) = ws.datasets.values()                                                  # experimento registrado
    assert len(ds.curves) == 4 and ds.device_id == cal1.device_id
    assert at.session_state.profile["device"]["name"] == "Dispositivo OTEKON"     # identidad del registro
    at.button(key="run_fit").click().run()                                        # nueva ejecución → nueva calibración
    assert len(ws.calibrations) == 2 and ws.calibrations[cal1.id].content_sha256 == cal1.content_sha256
    assert len(ws.datasets) == 1                                                  # mismas curvas: no se duplica
    goto(at, 6)
    at.button(key="prep_zip").click().run()
    assert not at.exception and len(at.session_state.zip_bytes) > 100_000
    assert ws.admin_status(cal1.device_id) == "PERFIL_AJUSTADO"


def test_new_stack_csv_without_code_changes():
    at = open_workspace(step=2, name="Stack X", n_cells=20, active_area_cm2=50.0)
    _paste(at, STACK_CSV)
    at.number_input(key="sc_T").set_value(65.0).run()
    at.selectbox(key="sc_Tu").set_value("°C").run()
    at.number_input(key="sc_P").set_value(50.0).run()
    at.selectbox(key="sc_Pu").set_value("kPa").run()
    at.selectbox(key="sc_Pref").set_value("manométrica").run()
    at.number_input(key="sc_amb").set_value(101.325).run()
    button(at, "Validar y añadir al conjunto").click().run()
    assert not at.exception and not at.error
    c = at.session_state.curves[0]
    assert abs(c.j_A_cm2[0] - 2.5 / 50) < 1e-12 and abs(c.v_cell_V[0] - 18.4 / 20) < 1e-12
    assert abs(c.conditions.temperature_K - 338.15) < 1e-9
    goto(at, 3)
    goto(at, 4)
    at.button(key="run_fit").click().run()
    assert not at.exception
    assert at.session_state.fit_result.status == "AJUSTADO_A_CURVA"
    assert at.session_state.profile["device"]["n_cells"] == 20


def test_invalid_csv_shows_error_and_creates_nothing():
    at = open_workspace(step=2, n_cells=20, active_area_cm2=50.0)
    _paste(at, "corriente_A;tension_stack_V\n2.5;18.4\n5;abc\n10;16.9\n15;\n20;15.9", ";")
    at.number_input(key="sc_T").set_value(338.15).run()
    at.number_input(key="sc_P").set_value(1.5).run()
    button(at, "Validar y añadir al conjunto").click().run()
    assert not at.exception
    err = " ".join(e.value for e in at.error)
    assert "no numéricos" in err and "vacías" in err
    assert at.session_state.curves == [] and at.session_state.profile is None


def test_missing_conditions_block_validation():
    at = open_workspace(step=2, n_cells=20, active_area_cm2=50.0)
    _paste(at, STACK_CSV)
    assert not [b for b in at.button if b.label == "Validar y añadir al conjunto"]
    assert any("Complete temperatura y presión" in i.value for i in at.info)


def test_stack_data_without_geometry_rejected():
    at = open_workspace(step=2, name="Sin geometría")
    _paste(at, STACK_CSV)
    at.number_input(key="sc_T").set_value(338.15).run()
    at.number_input(key="sc_P").set_value(1.5).run()
    button(at, "Validar y añadir al conjunto").click().run()
    assert any("área activa" in e.value for e in at.error)
    assert at.session_state.curves == []


def test_synthetic_example_validation_status_and_profile_reload():
    at = open_workspace(step=2)
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_synthetic").click().run()
    goto(at, 3)
    goto(at, 4)
    at.button(key="run_fit").click().run()
    r = at.session_state.fit_result
    assert r.status == "AJUSTADO_A_CURVA"
    assert r.validation["status"] == "VALIDACION_CON_DATOS_NO_EXPERIMENTALES"
    from identification.profiles import profile_to_json
    goto(at, 6)
    at.text_area(key="profile_text").set_value(profile_to_json(at.session_state.profile)).run()
    assert not at.exception
    assert any("Reproducción de la curva guardada" in s.value and "OK" in s.value for s in at.success)


def test_stale_result_marks_attention_and_keeps_history():
    at = open_workspace(step=2)
    at.radio(key="src_mode").set_value("Ejemplos documentados").run()
    at.button(key="ex_handoff").click().run()
    goto(at, 3)
    goto(at, 4)
    at.button(key="run_fit").click().run()
    assert at.session_state.fit_result is not None
    goto(at, 3)
    at.number_input(key="cfg_starts").set_value(20).run()
    goto(at, 6)                               # la calibración ya no es vigente → etapa 06 bloqueada
    assert at.session_state.route["step"] <= 4
    ws = at.session_state.ws
    st4 = at.session_state.dv_states[3]
    assert st4["state"] == "atencion" and "desactualizado" in st4["reason"]
    assert len(ws.calibrations) == 1                       # el resultado anterior NO se borra


def test_navigation_back_and_forth_keeps_work_and_draft_autosaves():
    at = open_workspace(step=2)
    _otekon_configured(at)
    for s in (1, 2, 3):
        goto(at, s)
    assert len(at.session_state.curves) == 4 and at.session_state.fit_config is not None
    ws = at.session_state.ws
    dr = ws.drafts[at.session_state.route["draft"]]
    assert len(dr.curves) == 4 and dr.fit_config is not None                  # volcado al borrador
    assert f"draft:{dr.id}" in ws.dirty                                       # pendiente de persistir (sin navegador)
    button(at, "Guardar borrador").click().run()
    assert ws.drafts[dr.id].saved_explicitly_utc is not None


def test_reopening_draft_in_new_session_restores_curves_and_config():
    at = open_workspace(step=2)
    _otekon_configured(at)
    ws = at.session_state.ws
    route = dict(at.session_state.route)
    hashes = [c.normalized_sha256 for c in at.session_state.curves]
    from workspace.model import Workspace
    at2 = new_app()
    ws2, problems = Workspace.from_records(ws.all_records())
    assert not problems
    at2.session_state.ws = ws2
    at2.session_state.route = route
    at2.run()
    assert not at2.exception
    assert [c.normalized_sha256 for c in at2.session_state.curves] == hashes
    assert at2.session_state.fit_config is not None and at2.session_state.fit_config.n_starts == 16


def test_history_panel_active_profile_and_fork():
    at = open_workspace(step=2)
    _otekon_configured(at)
    goto(at, 4)
    at.button(key="run_fit").click().run()
    at.session_state.route = {**at.session_state.route, "panel": "historial"}
    at.run()
    assert not at.exception
    button(at, "Establecer como perfil activo").click().run()
    ws = at.session_state.ws
    dev = ws.devices[at.session_state.route["device"]]
    cal = ws.calibrations[dev.active_calibration_id]
    assert cal.status_code == "AJUSTADO_A_CURVA"                # selección administrativa, no validación
    before = cal.content_sha256
    button(at, "Nueva identificación a partir de esta").click().run()
    assert not at.exception
    assert len(ws.drafts) == 2 and at.session_state.route["step"] == 3
    assert len(at.session_state.curves) == 4 and ws.calibrations[cal.id].content_sha256 == before


# --------------------------------------------------------------------------- v0.3.1: gestión de dispositivos (UI)
def _catalog_with_calibrated_device():
    at = open_workspace(step=2, name="Stack gestionado")
    _otekon_configured(at)
    goto(at, 4)
    at.button(key="run_fit").click().run()
    at.session_state.route = {"view": "catalog", "device": None, "draft": None, "step": 1, "panel": "flujo"}
    at.session_state.show_manage = True
    at.run()
    assert not at.exception
    return at


def test_manage_export_then_delete_with_exact_name_updates_catalog():
    at = _catalog_with_calibrated_device()
    ws = at.session_state.ws
    (did,) = ws.devices
    at.button(key=f"mg_exp_{did}").click().run()
    name, data = at.session_state.mg_export[did]
    assert name.endswith(".pmldevice.zip") and len(data) > 10_000
    at.button(key=f"mg_del_{did}").click().run()
    go = at.button(key=f"mg_go_{did}")
    assert go.disabled                                                      # sin nombre: no se puede borrar
    at.text_input(key="mg_delete_name").set_value("stack gestionado").run()
    assert at.button(key=f"mg_go_{did}").disabled                           # nombre inexacto
    at.text_input(key="mg_delete_name").set_value("Stack gestionado").run()
    at.button(key=f"mg_go_{did}").click().run()
    assert not at.exception and ws.devices == {} and not ws.calibrations and not ws.drafts
    assert any(o.get("delete") for o in ws.pending())                        # el borrado se propagará al navegador
    assert any("eliminado" in s.value for s in at.success)


def test_manage_import_exported_package_new_copy_and_replace():
    at = _catalog_with_calibrated_device()
    ws = at.session_state.ws
    (did,) = ws.devices
    at.button(key=f"mg_exp_{did}").click().run()
    _, data = at.session_state.mg_export[did]
    up = next(u for u in at.get("file_uploader") if u.id.endswith("mg_up_0") or "mg_up_" in u.id)
    up.set_value(("pkg.pmldevice.zip", data, "application/zip")).run()
    assert not at.exception
    assert at.radio(key=f"mg_strat_{did}").value == "copia"                 # conflicto detectado, opción por defecto
    at.button(key="mg_do_import").click().run()
    assert len(ws.devices) == 2 and any(d.name.endswith("(copia importada)") for d in ws.devices.values())
    # reemplazo: exige confirmación explícita
    up = next(u for u in at.get("file_uploader") if "mg_up_" in u.id)
    up.set_value(("pkg.pmldevice.zip", data, "application/zip")).run()
    at.radio(key=f"mg_strat_{did}").set_value("reemplazar").run()
    assert at.button(key="mg_do_import").disabled
    at.checkbox(key=f"mg_conf_{did}").check().run()
    at.button(key="mg_do_import").click().run()
    assert not at.exception and len(ws.devices) == 2 and did in ws.devices
