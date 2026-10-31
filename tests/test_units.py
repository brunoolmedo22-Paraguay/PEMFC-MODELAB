import numpy as np
import pytest

from pemfc_core import units as u


def test_current_conversions():
    assert np.allclose(u.to_current_density([300.0], "A", 300.0), [1.0])
    assert np.allclose(u.to_current_density([500.0], "mA/cm²", None), [0.5])
    assert np.allclose(u.to_current_density([5000.0], "A/m²", None), [0.5])
    assert np.allclose(u.to_current_density([1500.0], "mA", 3.0), [0.5])


def test_total_current_requires_area():
    with pytest.raises(u.UnitConversionError, match="área activa"):
        u.to_current_density([10.0], "A", None)


def test_stack_voltage_requires_integer_cell_count():
    assert np.allclose(u.to_cell_voltage([147.0], "V", "stack", 210), [0.7])
    assert np.allclose(u.to_cell_voltage([700.0], "mV", "celda", None), [0.7])
    with pytest.raises(u.UnitConversionError, match="número de celdas"):
        u.to_cell_voltage([147.0], "V", "stack", None)
    with pytest.raises(u.UnitConversionError):
        u.to_cell_voltage([147.0], "V", "stack", 2.5)


def test_temperature_and_pressure():
    assert u.temperature_to_K(80, "°C") == pytest.approx(353.15)
    assert u.pressure_to_atm_abs(101.325, "kPa") == pytest.approx(1.0)
    assert u.pressure_to_atm_abs(1.01325, "bar") == pytest.approx(1.0)
    assert u.pressure_to_atm_abs(14.6959488, "psi") == pytest.approx(1.0, rel=1e-6)
    assert u.pressure_to_atm_abs(120, "kPa", "manométrica", 101.325) == pytest.approx(221.325 / 101.325)
    with pytest.raises(u.UnitConversionError, match="ambiente"):
        u.pressure_to_atm_abs(120, "kPa", "manométrica", None)
    with pytest.raises(u.UnitConversionError):
        u.temperature_to_K(-300, "°C")


def test_area_units():
    assert u.area_to_cm2(0.03, "m²") == pytest.approx(300.0)
    assert u.area_to_cm2(30000, "mm²") == pytest.approx(300.0)
