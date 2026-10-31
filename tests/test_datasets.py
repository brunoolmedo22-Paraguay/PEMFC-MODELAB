"""Importación y validación estricta (A01, A02, A03, A07)."""
import numpy as np
import pandas as pd
import pytest

from identification import examples as ex
from identification.datasets import (
    ColumnMapping, ConditionInput, DatasetError, build_curve, check_curve_set, curves_from_table, read_table,
)
from pemfc_core.schemas import CurveMetadata, DeviceInfo

DEV = DeviceInfo(name="d", n_cells=20, active_area_cm2=50.0)
COND = ConditionInput(338.15, "K", 1.5, "atm")
GOOD_J = [0.05, 0.1, 0.2, 0.4, 0.6, 0.8]
GOOD_V = [0.92, 0.88, 0.845, 0.80, 0.76, 0.72]


def _curves(text, mapping, inputs=None, device=DEV, **kw):
    table = read_table(text.encode(), kw.pop("sep", "auto"), kw.get("decimal", "."))
    inputs = inputs or {"": (CurveMetadata("c1"), COND)}
    return curves_from_table(table, mapping, inputs, device, **kw)


def _errors(issues):
    return [i.message for i in issues if i.level == "error"]


def test_csv_semicolon_decimal_comma_stack_units():
    text = "I [A];V stack [V]\n" + "\n".join(f"{j*50:.1f};{v*20:.2f}".replace(".", ",") for j, v in zip(GOOD_J, GOOD_V))
    curves, issues = _curves(text, ColumnMapping("I [A]", "A", "V stack [V]", "V", "stack"), decimal=",")
    assert not _errors(issues)
    assert np.allclose(curves[0].j_A_cm2, GOOD_J) and np.allclose(curves[0].v_cell_V, GOOD_V)
    assert any("A_active (50 cm²)" in t for t in curves[0].transformations)


def test_vj_handoff_sample_conversion():
    c = ex.load_handoff_sample()
    raw = pd.read_csv(ex.EXAMPLES / "handoff" / "otekon_voltage_sample.csv")
    assert np.allclose(c.j_A_cm2, raw.current_density_A_cm2) and np.allclose(c.v_cell_V, raw.voltage_V)
    assert c.meta.quality == "ilustrativo"


def test_65kw_stack_conversion():
    c = ex.load_65kw_curve()
    assert np.allclose(c.j_A_cm2, np.array([180, 300, 420, 540]) / 300.0)
    assert np.allclose(c.v_cell_V, np.array([150, 147, 140, 133]) / 210.0)
    assert c.conditions.cathode_pressure_atm == pytest.approx((120 + 101.325) / 101.325)


def test_mA_cm2_and_mV_units():
    text = "i_mA_cm2,v_mV\n" + "\n".join(f"{1000*j},{1000*v}" for j, v in zip(GOOD_J, GOOD_V))
    curves, issues = _curves(text, ColumnMapping("i_mA_cm2", "mA/cm²", "v_mV", "mV", "celda"))
    assert not _errors(issues) and np.allclose(curves[0].v_cell_V, GOOD_V)


@pytest.mark.parametrize("rows, mapping, fragment", [
    ("j,v\n0.1,0.8\n0.2,\n0.3,0.7\n0.4,0.68", ("j", "A/cm²", "v"), "celdas vacías"),
    ("j,v\n0.1,0.8\n0.2,abc\n0.3,0.7\n0.4,0.68", ("j", "A/cm²", "v"), "no numéricos"),
    ("j,v\n-0.1,0.8\n0.2,0.75\n0.3,0.7\n0.4,0.68", ("j", "A/cm²", "v"), "negativa"),
    ("j,v\n0.1,16\n0.2,15\n0.3,14\n0.4,13", ("j", "A/cm²", "v"), "tensión de stack"),
    ("j,v\n100,0.8\n200,0.75\n300,0.7\n400,0.68", ("j", "A/cm²", "v"), "mA/cm²"),
    ("j,v\n0.1,0.8\n0.1,0.8\n0.3,0.7\n0.4,0.68", ("j", "A/cm²", "v"), "duplicados"),
    ("j,v\n0.1,0.8\n0.2,0.75", ("j", "A/cm²", "v"), "al menos 3"),
    ("j,v\n0.1,0.8\n0.2,0.75\n0.3,0.7\n0.4,0.68", ("j", "inexistente", "v"), "no soportada"),
    ("j,v\nx", ("j", "A/cm²", "v"), "no numéricos"),
])
def test_invalid_data_gives_actionable_errors(rows, mapping, fragment):
    curves, issues = _curves(rows, ColumnMapping(*mapping))
    assert curves == []
    assert any(fragment in m for m in _errors(issues)), _errors(issues)


def test_missing_geometry_and_conditions():
    text = "I,V\n" + "\n".join(f"{j*50},{v*20}" for j, v in zip(GOOD_J, GOOD_V))
    no_geo = DeviceInfo(name="d")
    _, issues = _curves(text, ColumnMapping("I", "A", "V", "V", "celda"), device=no_geo)
    assert any("área activa" in m for m in _errors(issues))
    _, issues = _curves(text, ColumnMapping("I", "A/cm²", "V", "V", "stack"), device=no_geo)
    assert any("número de celdas" in m for m in _errors(issues))
    _, issues = _curves("j,v\n" + "\n".join(f"{j},{v}" for j, v in zip(GOOD_J, GOOD_V)),
                        ColumnMapping("j", "A/cm²", "v"),
                        {"": (CurveMetadata("c"), ConditionInput(None, "K", 1.0))})
    assert any("temperatura" in m.lower() for m in _errors(issues))
    _, issues = _curves("j,v\n" + "\n".join(f"{j},{v}" for j, v in zip(GOOD_J, GOOD_V)),
                        ColumnMapping("j", "A/cm²", "v"),
                        {"": (CurveMetadata("c"), ConditionInput(338.15, "K", 50, "kPa", "manométrica"))})
    assert any("ambiente" in m for m in _errors(issues))
    _, issues = _curves("j,v\n" + "\n".join(f"{j},{v}" for j, v in zip(GOOD_J, GOOD_V)),
                        ColumnMapping("j", "A/cm²", "v"),
                        {"": (CurveMetadata("c"), ConditionInput(80, "K", 1.0))})
    assert any("fuera del rango admitido" in m for m in _errors(issues))


def test_excluded_rows_and_edit_note_recorded_and_sorting():
    text = "j,v\n0.4,0.80\n0.1,0.88\n0.2,0.85\n9,9\n0.6,0.76\n0.8,0.72"
    curves, issues = _curves(text, ColumnMapping("j", "A/cm²", "v"), excluded_rows={4}, edit_note="nota")
    assert not _errors(issues)
    t = curves[0].transformations
    assert "nota" in t and any("Excluidas" in x and "4" in x for x in t) and any("reordenados" in x for x in t)
    assert np.all(np.diff(curves[0].j_A_cm2) > 0)
    assert len(curves[0].raw) == 5


def test_multi_curve_group_column():
    rows = ["curva,j,v"] + [f"A,{j},{v}" for j, v in zip(GOOD_J, GOOD_V)] + [f"B,{j},{v - 0.02}" for j, v in zip(GOOD_J, GOOD_V)]
    inputs = {"A": (CurveMetadata("A"), COND), "B": (CurveMetadata("B"), ConditionInput(318.15, "K", 1.5))}
    curves, issues = _curves("\n".join(rows), ColumnMapping("j", "A/cm²", "v", group_column="curva"), inputs)
    assert not _errors(issues) and [c.curve_id for c in curves] == ["A", "B"]
    _, issues = _curves("\n".join(rows), ColumnMapping("j", "A/cm²", "v", group_column="curva"),
                        {"A": inputs["A"]})
    assert any("Faltan metadatos" in m for m in _errors(issues))


def test_curve_set_rules():
    assert any("datasheet" in i.message for i in check_curve_set([]))
    c, _ = build_curve(GOOD_J, GOOD_V, meta=CurveMetadata("cal"), condition_input=COND, device=DEV)
    v, _ = build_curve(GOOD_J, GOOD_V, meta=CurveMetadata("val", role="validación"), condition_input=COND, device=DEV)
    assert any("no es independiente" in i.message for i in check_curve_set([c, v]))
    assert any("calibración" in i.message for i in check_curve_set([v]))


def test_empty_and_single_column_files():
    with pytest.raises(DatasetError):
        read_table(b"   ")
    with pytest.raises(DatasetError, match="separador"):
        read_table(b"a\n1\n2", ",")
