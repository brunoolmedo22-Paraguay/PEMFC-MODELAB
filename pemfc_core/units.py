"""Conversión explícita de unidades hacia las unidades internas del modelo.

Unidades internas: j [A/cm²], V [V/celda], T [K], P [atm absolutas], A [cm²].
Ninguna función infiere N_cells ni A_active: si hacen falta y no se dan,
se lanza :class:`UnitConversionError` con un mensaje accionable.
"""
from __future__ import annotations

import math

import numpy as np

ATM_IN_KPA = 101.325


class UnitConversionError(ValueError):
    """Error de unidades o de datos geométricos faltantes."""


CURRENT_UNITS: dict[str, tuple[str, float]] = {
    # unidad: (tipo, factor hacia A o A/cm²)
    "A": ("total", 1.0),
    "mA": ("total", 1e-3),
    "A/cm²": ("density", 1.0),
    "mA/cm²": ("density", 1e-3),
    "A/m²": ("density", 1e-4),
}
VOLTAGE_UNITS: dict[str, float] = {"V": 1.0, "mV": 1e-3}
VOLTAGE_BASES = ("celda", "stack")
TEMPERATURE_UNITS = ("K", "°C")
PRESSURE_UNITS: dict[str, float] = {  # factor hacia kPa
    "atm": ATM_IN_KPA,
    "bar": 100.0,
    "kPa": 1.0,
    "Pa": 1e-3,
    "MPa": 1e3,
    "psi": 6.894757293168,
}
PRESSURE_REFERENCES = ("absoluta", "manométrica")
AREA_UNITS: dict[str, float] = {"cm²": 1.0, "m²": 1e4, "mm²": 1e-2}


def _finite_positive(value: float | None, name: str) -> float:
    if value is None:
        raise UnitConversionError(f"Falta {name}.")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitConversionError(f"{name} no es numérico: {value!r}.") from exc
    if not math.isfinite(x) or x <= 0:
        raise UnitConversionError(f"{name} debe ser finito y positivo (recibido {value!r}).")
    return x


def area_to_cm2(value: float, unit: str) -> float:
    if unit not in AREA_UNITS:
        raise UnitConversionError(f"Unidad de área no soportada: {unit!r}. Use {list(AREA_UNITS)}.")
    return _finite_positive(value, "el área activa") * AREA_UNITS[unit]


def current_is_total(unit: str) -> bool:
    if unit not in CURRENT_UNITS:
        raise UnitConversionError(f"Unidad de corriente no soportada: {unit!r}. Use {list(CURRENT_UNITS)}.")
    return CURRENT_UNITS[unit][0] == "total"


def to_current_density(values, unit: str, area_cm2: float | None) -> np.ndarray:
    """Corriente total o densidad en `unit` -> j [A/cm²]."""
    values = np.asarray(values, dtype=float)
    kind, factor = CURRENT_UNITS.get(unit, (None, None))
    if kind is None:
        raise UnitConversionError(f"Unidad de corriente no soportada: {unit!r}. Use {list(CURRENT_UNITS)}.")
    if kind == "density":
        return values * factor
    if area_cm2 is None:
        raise UnitConversionError(
            "La corriente está en unidades totales (A o mA): indique el área activa del "
            "dispositivo para convertirla a densidad de corriente. No se infiere el área.")
    area = _finite_positive(area_cm2, "el área activa")
    return values * factor / area


def to_cell_voltage(values, unit: str, basis: str, n_cells: int | None) -> np.ndarray:
    """Tensión en `unit` por celda o de stack -> V por celda."""
    if unit not in VOLTAGE_UNITS:
        raise UnitConversionError(f"Unidad de tensión no soportada: {unit!r}. Use {list(VOLTAGE_UNITS)}.")
    if basis not in VOLTAGE_BASES:
        raise UnitConversionError(f"Base de tensión no soportada: {basis!r}. Use {VOLTAGE_BASES}.")
    v = np.asarray(values, dtype=float) * VOLTAGE_UNITS[unit]
    if basis == "celda":
        return v
    if n_cells is None:
        raise UnitConversionError(
            "La tensión es de stack: indique el número de celdas para obtener la tensión "
            "por celda. No se infiere N_cells.")
    n = _finite_positive(n_cells, "el número de celdas")
    if abs(n - round(n)) > 1e-9:
        raise UnitConversionError(f"El número de celdas debe ser entero (recibido {n_cells!r}).")
    return v / round(n)


def temperature_to_K(value: float, unit: str) -> float:
    if unit not in TEMPERATURE_UNITS:
        raise UnitConversionError(f"Unidad de temperatura no soportada: {unit!r}. Use {TEMPERATURE_UNITS}.")
    if value is None:
        raise UnitConversionError("Falta la temperatura de la curva.")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitConversionError(f"Temperatura no numérica: {value!r}.") from exc
    if not math.isfinite(x):
        raise UnitConversionError("La temperatura debe ser finita.")
    kelvin = x + 273.15 if unit == "°C" else x
    if kelvin <= 0:
        raise UnitConversionError(f"Temperatura físicamente imposible: {value} {unit}.")
    return kelvin


def pressure_to_atm_abs(value: float, unit: str, reference: str = "absoluta",
                        ambient_kPa: float | None = None) -> float:
    """Presión en `unit` (absoluta o manométrica) -> atm absolutas.

    Para presión manométrica la presión ambiente es obligatoria (no se asume
    101,325 kPa en silencio: el llamador debe pasarla y declararla).
    """
    if unit not in PRESSURE_UNITS:
        raise UnitConversionError(f"Unidad de presión no soportada: {unit!r}. Use {list(PRESSURE_UNITS)}.")
    if reference not in PRESSURE_REFERENCES:
        raise UnitConversionError(f"Referencia de presión no soportada: {reference!r}.")
    if value is None:
        raise UnitConversionError("Falta la presión de la curva.")
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise UnitConversionError(f"Presión no numérica: {value!r}.") from exc
    if not math.isfinite(x):
        raise UnitConversionError("La presión debe ser finita.")
    kpa = x * PRESSURE_UNITS[unit]
    if reference == "manométrica":
        if ambient_kPa is None:
            raise UnitConversionError(
                "Presión manométrica: indique la presión ambiente de referencia (kPa).")
        kpa += _finite_positive(ambient_kPa, "la presión ambiente")
    if kpa <= 0:
        raise UnitConversionError(f"Presión absoluta no positiva: {value} {unit} ({reference}).")
    return kpa / ATM_IN_KPA
