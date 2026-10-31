"""Pestaña 1: Importar curva."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from identification import examples as ex
from identification.datasets import (
    ColumnMapping, ConditionInput, DatasetError, ValidationIssue, check_curve_set, curves_from_table,
    read_table, sha256_bytes,
)
from pemfc_core import units
from pemfc_core.parameters import ORIGINS
from pemfc_core.schemas import CURVE_QUALITIES, CURVE_ROLES, CurveMetadata, DeviceInfo

from . import digitizer_view, plots, state

NO_GROUP = "(ninguna: una sola curva)"
DEVICE_ORIGINS = [o for o in ORIGINS if o != "IDENTIFICADO"]


# ---------------------------------------------------------------------------
def _device_to_widgets(d: DeviceInfo) -> None:
    ss = st.session_state
    ss.dev_name, ss.dev_manufacturer, ss.dev_model = d.name, d.manufacturer, d.model
    ss.dev_n_known = d.n_cells is not None
    ss.dev_n = int(d.n_cells or 1)
    ss.dev_n_origin = d.n_cells_origin
    ss.dev_a_known = d.active_area_cm2 is not None
    ss.dev_a = float(d.active_area_cm2 or 1.0)
    ss.dev_a_unit = "cm²"
    ss.dev_a_origin = d.active_area_origin
    ss.dev_datasheet, ss.dev_notes = d.datasheet_reference, d.notes


def _device_from_widgets() -> DeviceInfo:
    ss = st.session_state
    area = None
    if ss.get("dev_a_known"):
        try:
            area = units.area_to_cm2(ss.dev_a, ss.dev_a_unit)
        except units.UnitConversionError:
            area = None
    return DeviceInfo(name=ss.get("dev_name", ""), manufacturer=ss.get("dev_manufacturer", ""),
                      model=ss.get("dev_model", ""),
                      n_cells=int(ss.dev_n) if ss.get("dev_n_known") else None,
                      n_cells_origin=ss.get("dev_n_origin", "MEDIDO"), active_area_cm2=area,
                      active_area_origin=ss.get("dev_a_origin", "MEDIDO"),
                      datasheet_reference=ss.get("dev_datasheet", ""), notes=ss.get("dev_notes", ""))


def _load_example(kind: str) -> None:
    if kind == "otekon":
        dev = ex.otekon_device()
        curves = ex.load_otekon_curves(dev)
        label = "Ejemplo OTEKON Fig. 3 (4 curvas digitalizadas)"
    elif kind == "65kw":
        dev = ex.equivalent_65kw_device()
        curves = [ex.load_65kw_curve(dev)]
        label = "Ejemplo stack 65 kW (Chen et al. 2024)"
    elif kind == "handoff":
        dev = DeviceInfo(name="Muestra ilustrativa del handoff")
        curves = [ex.load_handoff_sample(dev)]
        label = "Muestra ilustrativa del handoff (no experimental)"
    else:
        dev = DeviceInfo(name="Dispositivo sintético", n_cells=1, n_cells_origin="FIJADO",
                         active_area_cm2=100.0, active_area_origin="FIJADO")
        curves = [ex.synthetic_curve(device=dev, curve_id="sintetico_343K_1.5atm"),
                  ex.synthetic_curve(device=dev, temperature_K=323.15, pressure_atm=1.5, seed=11,
                                     j=[0.05, 0.2, 0.4, 0.6, 0.8, 1.0], curve_id="sintetico_323K_validacion",
                                     role="validación")]
        label = "Caso sintético (modelo + ruido 2 mV; NO es validación experimental)"
    originals = {c.source_file: (ex.EXAMPLES / c.meta.provenance.replace("examples/", "")).read_bytes()
                 for c in curves if c.source_file and c.meta.provenance.startswith("examples/")}
    state.set_dataset(curves, dev, originals, label)
    _device_to_widgets(dev)


# ---------------------------------------------------------------------------
def _device_section() -> None:
    st.subheader("Dispositivo")
    st.caption("N_cells y A_active solo son necesarios si los datos están en corriente total o tensión de stack. "
               "No se infieren. La referencia de datasheet es complementaria: no se usa en el ajuste.")
    c1, c2, c3 = st.columns(3)
    c1.text_input("Nombre del dispositivo *", key="dev_name")
    c2.text_input("Fabricante", key="dev_manufacturer")
    c3.text_input("Modelo", key="dev_model")
    c1, c2, c3, c4 = st.columns([1.1, 1, 1, 1])
    c1.checkbox("Número de celdas conocido", key="dev_n_known")
    if st.session_state.get("dev_n_known"):
        c2.number_input("N_cells", min_value=1, max_value=2000, step=1, key="dev_n")
        c3.selectbox("Origen de N_cells", DEVICE_ORIGINS, key="dev_n_origin")
    c1, c2, c3, c4 = st.columns([1.1, 1, 1, 1])
    c1.checkbox("Área activa conocida", key="dev_a_known")
    if st.session_state.get("dev_a_known"):
        c2.number_input("Área activa", min_value=0.0, format="%.6g", key="dev_a")
        c3.selectbox("Unidad de área", list(units.AREA_UNITS), key="dev_a_unit")
        c4.selectbox("Origen del área", DEVICE_ORIGINS, key="dev_a_origin")
    st.text_input("Referencia de datasheet (opcional, solo documental)", key="dev_datasheet")
    st.text_area("Notas del dispositivo", key="dev_notes", height=70)

    form = _device_from_widgets()
    current = st.session_state.device
    if st.session_state.curves and (form.n_cells, form.active_area_cm2) != (current.n_cells, current.active_area_cm2):
        st.error(f"Las curvas actuales se normalizaron con N_cells = {current.n_cells} y A = {current.active_area_cm2} cm². "
                 "La geometría del formulario es distinta: vacíe el conjunto de curvas y vuelva a importarlas, "
                 "o restaure los valores anteriores.")
    else:
        st.session_state.device = form


def _guess(columns, words, default_index):
    for i, c in enumerate(columns):
        if any(w in c.lower() for w in words):
            return i
    return min(default_index, len(columns) - 1)


def _guess_current_unit(col: str) -> str:
    c = col.lower()
    if "ma_cm2" in c or "ma/cm" in c:
        return "mA/cm²"
    if "a_cm2" in c or "a/cm" in c or "density" in c or "densidad" in c:
        return "A/cm²"
    if "ma" in c.split("_"):
        return "mA"
    return "A" if "_a" in c or c.endswith("(a)") or c in ("i", "current", "corriente") else "A/cm²"


def _csv_section(mode: str) -> None:
    c1, c2 = st.columns(2)
    sep = c1.selectbox("Separador de columnas", ["auto", ",", ";", "tab"], key="csv_sep")
    dec = c2.selectbox("Separador decimal", [".", ","], key="csv_dec")
    if mode == "Archivo CSV":
        up = st.file_uploader("Archivo CSV con la curva de polarización", type=["csv", "txt"], key="csv_file")
        if up is None:
            st.info("Seleccione un archivo. Formato: una fila de encabezado y columnas de corriente y tensión; "
                    "opcionalmente una columna que identifique varias curvas. Líneas que empiezan por # se ignoran.")
            return
        data, fname = up.getvalue(), up.name
    else:
        text = st.text_area("Pegue aquí el contenido CSV (con encabezado)", key="csv_text", height=180,
                            placeholder="current_density_A_cm2,voltage_V\n0.1,0.82\n0.2,0.77\n…")
        if not text.strip():
            return
        data, fname = text.encode("utf-8"), st.text_input("Nombre para registrar el origen", "datos_pegados.csv",
                                                           key="csv_text_name")
    try:
        table = read_table(data, sep, dec)
    except DatasetError as exc:
        state.show_issues(exc.issues)
        return
    digest = sha256_bytes(data)
    st.caption(f"{fname} · {len(table)} filas · {len(table.columns)} columnas · SHA-256 {digest[:16]}…")
    cols = list(table.columns)

    st.markdown("**Mapeo de columnas y unidades**")
    c1, c2, c3 = st.columns(3)
    cur_col = c1.selectbox("Columna de corriente", cols, index=_guess(cols, ("current", "corr", "j_", "i_"), 0),
                           key=f"map_cur_{digest}")
    cur_unit = c1.selectbox("Unidad de corriente", list(units.CURRENT_UNITS),
                            index=list(units.CURRENT_UNITS).index(_guess_current_unit(cur_col)), key=f"map_curu_{digest}")
    volt_col = c2.selectbox("Columna de tensión", cols, index=_guess(cols, ("volt", "tens", "v_", "value"), 1),
                            key=f"map_v_{digest}")
    volt_unit = c2.selectbox("Unidad de tensión", list(units.VOLTAGE_UNITS), key=f"map_vu_{digest}")
    basis = c2.selectbox("La tensión es", ["celda", "stack"], index=1 if "stack" in volt_col.lower() else 0,
                         key=f"map_vb_{digest}", format_func=lambda b: "por celda" if b == "celda" else "del stack completo")
    group = c3.selectbox("Columna que identifica la curva", [NO_GROUP] + cols, key=f"map_g_{digest}")
    group = None if group == NO_GROUP else group
    mapping = ColumnMapping(cur_col, cur_unit, volt_col, volt_unit, basis, group)

    st.markdown("**Puntos** — edite valores o desmarque *incluir* para excluir filas (queda registrado).")
    show_cols = [c for c in dict.fromkeys([cur_col, volt_col, group]) if c]
    view = table[show_cols].copy()
    view.insert(0, "incluir", True)
    view.index = range(1, len(view) + 1)
    edited = st.data_editor(view, key=f"points_{digest}_{'_'.join(show_cols)}", width="stretch",
                            num_rows="fixed", disabled=[group] if group else [])
    excluded = {int(i) for i in edited.index[~edited["incluir"].astype(bool)]}
    table_used = table.copy()
    for c in show_cols:
        table_used[c] = edited[c].astype(str).to_numpy()
    n_changed = int((table_used[show_cols].to_numpy() != table[show_cols].to_numpy()).sum())
    edit_note = f"Valores editados por el usuario en {n_changed} celda(s) del archivo original." if n_changed else None

    groups = list(dict.fromkeys(table[group].astype(str))) if group else [""]
    st.markdown("**Condiciones de medición y metadatos** — temperatura y presión son obligatorias.")
    curve_inputs = _single_curve_form(Path(fname).stem) if not group else _multi_curve_editor(groups, digest)
    if curve_inputs is None:
        return

    if st.button("Validar y añadir al conjunto", type="primary", key=f"add_{digest}"):
        device = st.session_state.device
        issues = [ValidationIssue("error", "", e) for e in device.validate()]
        if st.session_state.curves:
            existing = {c.curve_id for c in st.session_state.curves}
            dup = existing & {m.curve_id for m, _ in curve_inputs.values()}
            if dup:
                issues.append(ValidationIssue("error", "", f"Ya existen curvas con id {sorted(dup)}."))
        if not any(i.level == "error" for i in issues):
            curves, cissues = curves_from_table(table_used, mapping, curve_inputs, device, decimal=dec,
                                                source_file=fname, source_sha256=digest,
                                                excluded_rows=excluded, edit_note=edit_note)
            issues += cissues
            if not any(i.level == "error" for i in issues):
                all_curves = st.session_state.curves + curves
                issues += [i for i in check_curve_set(all_curves) if i.level == "error"]
        if not state.show_issues(issues):
            new = st.session_state.curves + curves
            originals = dict(st.session_state.originals)
            originals[fname] = data
            state.set_dataset(new, device, originals,
                              st.session_state.dataset_label or "Datos importados por el usuario")
            st.success(f"Añadidas {len(curves)} curva(s). Revise el conjunto abajo y continúe en "
                       "«Configurar identificación».")


def _optional(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else v


def _single_curve_form(default_id: str):
    ss = st.session_state
    c1, c2, c3 = st.columns(3)
    cid = c1.text_input("Identificador de la curva", value=default_id, key="sc_id")
    role = c2.selectbox("Rol", CURVE_ROLES, key="sc_role",
                        help="‘validación’: no se usa en el ajuste; sirve para validación independiente.")
    quality = c3.selectbox("Calidad", CURVE_QUALITIES, key="sc_quality")
    c1, c2, c3, c4 = st.columns(4)
    T = c1.number_input("Temperatura *", value=None, format="%.6g", key="sc_T")
    T_unit = c2.selectbox("Unidad T", units.TEMPERATURE_UNITS, key="sc_Tu")
    P = c3.number_input("Presión de cátodo *", value=None, format="%.6g", key="sc_P")
    P_unit = c4.selectbox("Unidad P", list(units.PRESSURE_UNITS), key="sc_Pu")
    c1, c2, c3, c4 = st.columns(4)
    P_ref = c1.selectbox("Referencia de presión", units.PRESSURE_REFERENCES, key="sc_Pref")
    amb = c2.number_input("P ambiente [kPa]", value=None, format="%.6g", key="sc_amb",
                          help="Obligatoria si la presión es manométrica.") if P_ref == "manométrica" else None
    ph2 = c3.number_input("p_H2 [atm abs] (opcional)", value=None, format="%.6g", key="sc_ph2",
                          help="Si se deja vacío se usa el valor global del modelo (1 atm, hipótesis OTEKON).")
    yo2 = c4.number_input("Fracción de O2 (opcional)", value=None, min_value=0.0, max_value=1.0, format="%.4g",
                          key="sc_yo2", help="Vacío = aire (0,21).")
    c1, c2, c3 = st.columns(3)
    sig = c1.number_input("σ_V [mV/celda] (opcional)", value=None, min_value=0.0, format="%.4g", key="sc_sig",
                          help="Incertidumbre de tensión declarada. No se asume ningún valor por defecto.")
    corig = c2.selectbox("Origen de las condiciones", DEVICE_ORIGINS, key="sc_corig")
    source = c3.text_input("Fuente", key="sc_src", placeholder="Ensayo, artículo, laboratorio…")
    prov = st.text_input("Procedencia / trazabilidad", key="sc_prov", placeholder="Fecha, banco de ensayo, archivo…")
    if T is None or P is None or (P_ref == "manométrica" and amb is None):
        st.info("Complete temperatura y presión (y la presión ambiente si es manométrica) para poder validar.")
        return None
    meta = CurveMetadata(curve_id=cid.strip(), role=role, source=source, provenance=prov, quality=quality,
                         sigma_V=None if not sig else sig / 1000.0,
                         sigma_origin="Declarada por el usuario" if sig else "", conditions_origin=corig)
    cond = ConditionInput(T, T_unit, P, P_unit, P_ref, _optional(amb), _optional(ph2), _optional(yo2) or None)
    return {"": (meta, cond)}


def _multi_curve_editor(groups: list[str], digest: str):
    base = pd.DataFrame({
        "grupo": groups, "curve_id": groups, "rol": CURVE_ROLES[0], "calidad": CURVE_QUALITIES[0],
        "T": [None] * len(groups), "unidad_T": "K", "P": [None] * len(groups), "unidad_P": "atm",
        "referencia_P": "absoluta", "P_ambiente_kPa": [None] * len(groups), "p_H2_atm_abs": [None] * len(groups),
        "fraccion_O2": [None] * len(groups), "sigma_V_mV": [None] * len(groups), "origen_condiciones": "MEDIDO",
        "fuente": "", "procedencia": ""})
    cfg = {
        "grupo": st.column_config.TextColumn(disabled=True),
        "rol": st.column_config.SelectboxColumn(options=list(CURVE_ROLES), required=True),
        "calidad": st.column_config.SelectboxColumn(options=list(CURVE_QUALITIES), required=True),
        "T": st.column_config.NumberColumn("T *"), "P": st.column_config.NumberColumn("P cátodo *"),
        "unidad_T": st.column_config.SelectboxColumn(options=list(units.TEMPERATURE_UNITS), required=True),
        "unidad_P": st.column_config.SelectboxColumn(options=list(units.PRESSURE_UNITS), required=True),
        "referencia_P": st.column_config.SelectboxColumn(options=list(units.PRESSURE_REFERENCES), required=True),
        "origen_condiciones": st.column_config.SelectboxColumn(options=DEVICE_ORIGINS, required=True),
        "P_ambiente_kPa": st.column_config.NumberColumn(), "p_H2_atm_abs": st.column_config.NumberColumn(),
        "fraccion_O2": st.column_config.NumberColumn(), "sigma_V_mV": st.column_config.NumberColumn("σ_V [mV]"),
    }
    ed = st.data_editor(base, key=f"groups_{digest}", column_config=cfg, hide_index=True, num_rows="fixed",
                        width="stretch")
    missing = ed[ed["T"].isna() | ed["P"].isna()]["grupo"].tolist()
    if missing:
        st.info(f"Complete T y P para las curvas: {missing}.")
        return None
    out = {}
    for _, r in ed.iterrows():
        sig = _optional(r["sigma_V_mV"])
        meta = CurveMetadata(curve_id=str(r["curve_id"]).strip(), role=r["rol"], quality=r["calidad"],
                             source=str(r["fuente"] or ""), provenance=str(r["procedencia"] or ""),
                             sigma_V=None if not sig else float(sig) / 1000.0,
                             sigma_origin="Declarada por el usuario" if sig else "",
                             conditions_origin=r["origen_condiciones"])
        cond = ConditionInput(float(r["T"]), r["unidad_T"], float(r["P"]), r["unidad_P"], r["referencia_P"],
                              _optional(r["P_ambiente_kPa"]), _optional(r["p_H2_atm_abs"]),
                              _optional(r["fraccion_O2"]))
        out[str(r["grupo"])] = (meta, cond)
    return out


def _examples_section() -> None:
    st.caption("Conjuntos documentados para explorar la aplicación. Ninguno constituye validación experimental "
               "de un dispositivo nuevo. Cargar un ejemplo reemplaza el conjunto actual.")
    items = [
        ("otekon", "OTEKON Fig. 3 — 4 curvas digitalizadas",
         "Referencia de reproducción del identificador original (σ = 3 mV declarada solo aquí)."),
        ("65kw", "Stack 65 kW — Chen et al. 2024",
         "4 puntos de stack, 210 celdas, 300 cm². Condiciones = hipótesis ETAPA 3. No es una curva Horizon."),
        ("handoff", "Muestra del handoff",
         "CSV ilustrativo de formato (V–j); condiciones asumidas. No son datos experimentales."),
        ("synthetic", "Sintético con ruido controlado",
         "Generado con el modelo (ruido 2 mV) + curva de validación sintética: prueba del algoritmo."),
    ]
    for kind, title, desc in items:
        c1, c2 = st.columns([1, 2.4])
        c1.button(f"Cargar: {title}", key=f"ex_{kind}", on_click=_load_example, args=(kind,), width="stretch")
        c2.caption(desc)


def _current_set() -> None:
    curves = st.session_state.curves
    st.subheader("Conjunto de curvas actual")
    if not curves:
        st.info("Todavía no hay curvas. Importe un CSV, pegue datos o cargue un ejemplo. "
                "Sin curva V–I no es posible crear un perfil.")
        return
    dev = st.session_state.device
    cfg = st.session_state.fit_config
    dev_p_h2 = cfg.base_params.p_h2 if cfg is not None else 1.0
    st.caption(st.session_state.dataset_label)
    rows = [{"curva": c.curve_id, "rol": c.meta.role, "calidad": c.meta.quality,
             "T [K]": round(c.conditions.temperature_K, 2), "P cátodo [atm abs]": round(c.conditions.cathode_pressure_atm, 4),
             "p_H2 [atm]": (f"{c.conditions.p_h2_atm:.6g}" if c.conditions.p_h2_atm is not None
                           else f"global ({dev_p_h2:g})"), "n": c.n_points,
             "j [A/cm²]": f"{c.j_A_cm2.min():.3g} – {c.j_A_cm2.max():.3g}",
             "V [V/celda]": f"{c.v_cell_V.min():.3g} – {c.v_cell_V.max():.3g}",
             "σ_V [mV]": "no declarada" if c.meta.sigma_V is None else f"{1000 * c.meta.sigma_V:g}",
             "origen": c.source_file}
            for c in curves]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    stack = st.toggle("Mostrar en unidades de stack (I [A], V_stack)", key="prev_stack",
                      disabled=not (dev.n_cells and dev.active_area_cm2))
    st.plotly_chart(plots.data_preview(curves, dev, stack), width="stretch")
    for c in curves:
        with st.expander(f"Detalle de {c.curve_id}: transformaciones, avisos y puntos originales"):
            st.markdown("**Transformaciones:**\n" + ("\n".join(f"- {t}" for t in c.transformations) or "- Ninguna"))
            if c.warnings:
                st.warning("\n".join(f"- {w}" for w in c.warnings))
            st.markdown(f"Fuente: {c.meta.source or '—'} · Procedencia: {c.meta.provenance or '—'} · "
                        f"Origen de condiciones: {c.meta.conditions_origin}")
            if c.meta.notes:
                st.caption(c.meta.notes)
            st.dataframe(c.raw, hide_index=True, width="stretch")
    c1, c2 = st.columns([2, 1])
    remove = c1.multiselect("Quitar curvas", [c.curve_id for c in curves], key="rm_curves")
    if c1.button("Quitar seleccionadas", disabled=not remove):
        keep = [c for c in curves if c.curve_id not in remove]
        state.set_dataset(keep, dev, st.session_state.originals, st.session_state.dataset_label)
        st.rerun()
    if c2.button("Vaciar conjunto"):
        state.set_dataset([], dev, {}, "")
        st.rerun()


def render() -> None:
    _device_section()
    st.divider()
    st.subheader("Datos de polarización")
    mode = st.radio("Origen de los datos", ["Archivo CSV", "Pegar datos CSV", "Ejemplos documentados",
                                            "Imagen de una curva"], horizontal=True, key="src_mode")
    if mode in ("Archivo CSV", "Pegar datos CSV"):
        _csv_section(mode)
    elif mode == "Ejemplos documentados":
        _examples_section()
    else:
        digitizer_view.render_entry()
    st.divider()
    _current_set()
