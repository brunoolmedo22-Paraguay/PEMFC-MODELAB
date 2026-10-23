"""Importación, validación estricta y normalización de curvas de polarización.

Reglas: no se convierten faltantes a cero, no se descartan filas en silencio,
no se infieren N_cells ni A_active. Cada transformación queda registrada.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from pemfc_core import units
from pemfc_core.model import OperatingConditions
from pemfc_core.schemas import CurveMetadata, DeviceInfo

# Dominio de temperatura en el que la estructura del modelo fue identificada (OTEKON).
REFERENCE_T_RANGE_K = (298.15, 373.15)
REFERENCE_P_RANGE_ATM = (1.0, 5.0)
HARD_T_RANGE_K = (233.15, 473.15)
HARD_P_RANGE_ATM = (0.2, 20.0)
MAX_CELL_VOLTAGE_V = 1.3
MAX_CURRENT_DENSITY_A_CM2 = 5.0
MIN_POINTS = 3
RECOMMENDED_POINTS = 6
CURRENT_FLOOR_A_CM2 = 0.010


@dataclass
class ValidationIssue:
    level: str  # "error" | "aviso"
    curve_id: str
    message: str

    def __str__(self) -> str:
        prefix = f"[{self.curve_id}] " if self.curve_id else ""
        return f"{prefix}{self.message}"


class DatasetError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues if i.level == "error"))


@dataclass
class ColumnMapping:
    current_column: str
    current_unit: str
    voltage_column: str
    voltage_unit: str = "V"
    voltage_basis: str = "celda"
    group_column: str | None = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ConditionInput:
    """Condiciones tal como las introduce el usuario (unidades originales)."""

    temperature: float | None
    temperature_unit: str = "K"
    pressure: float | None = None
    pressure_unit: str = "atm"
    pressure_reference: str = "absoluta"
    ambient_kPa: float | None = None
    p_h2_atm_abs: float | None = None
    oxygen_fraction: float | None = None

    def to_conditions(self) -> OperatingConditions:
        T = units.temperature_to_K(self.temperature, self.temperature_unit)
        P = units.pressure_to_atm_abs(self.pressure, self.pressure_unit,
                                      self.pressure_reference, self.ambient_kPa)
        return OperatingConditions(T, P, self.p_h2_atm_abs, self.oxygen_fraction)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class PolarizationCurve:
    meta: CurveMetadata
    conditions: OperatingConditions
    conditions_input: dict
    j_A_cm2: np.ndarray
    v_cell_V: np.ndarray
    raw: pd.DataFrame
    source_file: str = ""
    source_sha256: str = ""
    mapping: dict = field(default_factory=dict)
    transformations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def curve_id(self) -> str:
        return self.meta.curve_id

    @property
    def n_points(self) -> int:
        return int(self.j_A_cm2.size)

    @property
    def normalized_sha256(self) -> str:
        payload = json.dumps({"j": [repr(float(x)) for x in self.j_A_cm2],
                              "v": [repr(float(x)) for x in self.v_cell_V]})
        return hashlib.sha256(payload.encode()).hexdigest()

    def normalized_frame(self, device: DeviceInfo | None = None) -> pd.DataFrame:
        df = pd.DataFrame({"curve_id": self.curve_id, "j_A_cm2": self.j_A_cm2, "V_cell_V": self.v_cell_V})
        if device is not None and device.active_area_cm2:
            df["I_A"] = self.j_A_cm2 * device.active_area_cm2
        if device is not None and device.n_cells:
            df["V_stack_V"] = self.v_cell_V * device.n_cells
        return df


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_table(data: bytes, separator: str = "auto", decimal: str = ".",
               encoding: str = "utf-8") -> pd.DataFrame:
    """Lee un CSV como texto (sin coerción). Líneas que empiezan por # se ignoran."""
    if not data or not data.strip():
        raise DatasetError([ValidationIssue("error", "", "El archivo está vacío.")])
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as exc:
        raise DatasetError([ValidationIssue("error", "", f"No se pudo decodificar como {encoding}: {exc}.")]) from exc
    sep = None if separator == "auto" else {"tab": "\t"}.get(separator, separator)
    if sep is None and decimal == ",":
        # Con coma decimal el separador más habitual es ';'.
        first = next((ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")), "")
        sep = ";" if ";" in first else ("\t" if "\t" in first else None)
    try:
        df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str,
                         keep_default_na=False, comment="#", skip_blank_lines=True)
    except Exception as exc:  # pandas lanza tipos diversos
        raise DatasetError([ValidationIssue("error", "", f"No se pudo leer el CSV: {exc}.")]) from exc
    df.columns = [str(c).strip() for c in df.columns]
    if df.shape[1] < 2:
        raise DatasetError([ValidationIssue(
            "error", "", "Se detectó una sola columna. Revise el separador (coma, punto y coma, tabulador) "
                         "y el separador decimal.")])
    if len(set(df.columns)) != len(df.columns):
        raise DatasetError([ValidationIssue("error", "", "Hay nombres de columna duplicados.")])
    return df.apply(lambda s: s.map(lambda v: v.strip() if isinstance(v, str) else ""))


def parse_numeric(series: pd.Series, decimal: str, column: str, curve_id: str,
                  row_labels) -> tuple[np.ndarray, list[ValidationIssue]]:
    """Convierte texto a float sin rellenar faltantes. Devuelve issues con filas."""
    values = np.full(len(series), np.nan)
    empty, bad = [], []
    for k, (raw, row) in enumerate(zip(series.tolist(), row_labels)):
        s = raw.strip() if isinstance(raw, str) else ""
        if s == "" or s.lower() in {"nan", "na", "null", "none"}:
            empty.append(row)
            continue
        if decimal == ",":
            if "." in s and "," in s:
                bad.append(row)
                continue
            s = s.replace(",", ".")
        try:
            values[k] = float(s)
        except ValueError:
            bad.append(row)
    issues = []
    if empty:
        issues.append(ValidationIssue("error", curve_id, f"Columna {column!r}: celdas vacías en filas {_rows(empty)}. "
                                      "No se rellenan con cero: complete o excluya esas filas."))
    if bad:
        issues.append(ValidationIssue("error", curve_id, f"Columna {column!r}: valores no numéricos en filas {_rows(bad)}. "
                                      "Revise el separador decimal."))
    nonfinite = [r for r, v in zip(row_labels, values) if np.isinf(v)]
    if nonfinite:
        issues.append(ValidationIssue("error", curve_id, f"Columna {column!r}: valores infinitos en filas {_rows(nonfinite)}."))
    return values, issues


def _rows(rows: list) -> str:
    shown = ", ".join(str(r) for r in rows[:12])
    return shown + (f" (+{len(rows) - 12} más)" if len(rows) > 12 else "")


def check_curve_values(j: np.ndarray, v: np.ndarray, curve_id: str) -> list[ValidationIssue]:
    """Validación física/dimensional de una curva ya normalizada (A/cm², V/celda)."""
    issues: list[ValidationIssue] = []
    E = lambda m: issues.append(ValidationIssue("error", curve_id, m))  # noqa: E731
    W = lambda m: issues.append(ValidationIssue("aviso", curve_id, m))  # noqa: E731
    n = j.size
    if n < MIN_POINTS:
        E(f"Solo {n} punto(s); se necesitan al menos {MIN_POINTS} para calibrar.")
        return issues
    if not (np.isfinite(j).all() and np.isfinite(v).all()):
        E("Hay valores no finitos tras la conversión de unidades.")
        return issues
    if (j < 0).any():
        E(f"{int((j < 0).sum())} punto(s) con corriente negativa. Una curva de polarización de pila "
          "en descarga tiene j ≥ 0; revise el signo o la convención del ensayo.")
    if (v <= 0).any():
        E(f"{int((v <= 0).sum())} punto(s) con tensión ≤ 0 V.")
    if (v > MAX_CELL_VOLTAGE_V).any():
        E(f"Tensión por celda máxima {v.max():.3g} V > {MAX_CELL_VOLTAGE_V} V: probablemente es tensión de stack "
          "(indique base 'stack' y N_cells) o la unidad es mV.")
    if (j > MAX_CURRENT_DENSITY_A_CM2).any():
        E(f"Densidad de corriente máxima {j.max():.4g} A/cm² > {MAX_CURRENT_DENSITY_A_CM2}: revise la unidad "
          "(¿mA/cm²?) o el área activa.")
    if np.ptp(j) == 0:
        E("Todos los puntos tienen la misma corriente.")
    pairs = pd.DataFrame({"j": j, "v": v})
    dup_exact = int(pairs.duplicated().sum())
    if dup_exact:
        E(f"{dup_exact} punto(s) duplicados exactamente (misma corriente y tensión). Elimínelos o confirme que "
          "son mediciones repetidas distintas.")
    same_j = int(pairs.duplicated(subset="j").sum()) - dup_exact
    if same_j > 0:
        W(f"{same_j} punto(s) repiten corriente con tensión distinta (mediciones repetidas o histéresis).")
    if any(i.level == "error" for i in issues):
        return issues
    if n < RECOMMENDED_POINTS:
        W(f"Curva con pocos puntos ({n}). Los parámetros obtenidos serán poco robustos.")
    below = int((j < CURRENT_FLOOR_A_CM2).sum())
    if below:
        W(f"{below} punto(s) con j < {CURRENT_FLOOR_A_CM2} A/cm²: el término de activación se evalúa en el piso "
          "numérico del modelo original, que no representa la región de muy baja corriente.")
    order = np.argsort(j, kind="stable")
    rising = int((np.diff(v[order]) > 0).sum())
    if rising:
        W(f"La tensión aumenta con la corriente en {rising} tramo(s): posible ruido, histéresis o error de datos.")
    if j.max() < 0.1:
        W("Rango de corriente estrecho (j máx < 0,1 A/cm²): las pérdidas óhmicas y de concentración "
          "no estarán representadas en los datos.")
    if v.max() > 1.23:
        W("Tensión por celda > 1,23 V: por encima del potencial reversible típico; revise los datos.")
    return issues


def check_conditions(cond: OperatingConditions, curve_id: str) -> list[ValidationIssue]:
    issues = []
    T, P = cond.temperature_K, cond.cathode_pressure_atm
    if not (HARD_T_RANGE_K[0] <= T <= HARD_T_RANGE_K[1]):
        issues.append(ValidationIssue("error", curve_id, f"Temperatura {T:.2f} K fuera del rango admitido "
                                      f"{HARD_T_RANGE_K[0]}–{HARD_T_RANGE_K[1]} K. ¿Unidad °C/K correcta?"))
    elif not (REFERENCE_T_RANGE_K[0] <= T <= REFERENCE_T_RANGE_K[1]):
        issues.append(ValidationIssue("aviso", curve_id, f"Temperatura {T:.2f} K fuera del rango en que la estructura "
                                      f"del modelo fue identificada ({REFERENCE_T_RANGE_K[0]}–{REFERENCE_T_RANGE_K[1]} K)."))
    if not (HARD_P_RANGE_ATM[0] <= P <= HARD_P_RANGE_ATM[1]):
        issues.append(ValidationIssue("error", curve_id, f"Presión absoluta {P:.3g} atm fuera del rango admitido "
                                      f"{HARD_P_RANGE_ATM[0]}–{HARD_P_RANGE_ATM[1]} atm. ¿Unidad o referencia (abs/man.)?"))
    elif not (REFERENCE_P_RANGE_ATM[0] <= P <= REFERENCE_P_RANGE_ATM[1]):
        issues.append(ValidationIssue("aviso", curve_id, f"Presión {P:.3g} atm fuera del rango de referencia "
                                      f"{REFERENCE_P_RANGE_ATM[0]}–{REFERENCE_P_RANGE_ATM[1]} atm."))
    return issues


def build_curve(
    j_values,
    v_values,
    *,
    meta: CurveMetadata,
    condition_input: ConditionInput,
    device: DeviceInfo,
    current_unit: str = "A/cm²",
    voltage_unit: str = "V",
    voltage_basis: str = "celda",
    raw: pd.DataFrame | None = None,
    source_file: str = "",
    source_sha256: str = "",
    mapping: dict | None = None,
    transformations: list[str] | None = None,
) -> tuple[PolarizationCurve | None, list[ValidationIssue]]:
    """Normaliza y valida una curva. Devuelve (None, issues) si hay errores."""
    cid = meta.curve_id
    issues = [ValidationIssue("error", cid, m) for m in meta.validate()]
    j_raw = np.asarray(j_values, dtype=float)
    v_raw = np.asarray(v_values, dtype=float)
    if j_raw.shape != v_raw.shape:
        issues.append(ValidationIssue("error", cid, "Corriente y tensión tienen longitudes distintas."))
        return None, issues
    try:
        cond = condition_input.to_conditions()
    except (units.UnitConversionError, ValueError) as exc:
        issues.append(ValidationIssue("error", cid, f"Condiciones: {exc}"))
        cond = None
    try:
        j = units.to_current_density(j_raw, current_unit, device.active_area_cm2)
        v = units.to_cell_voltage(v_raw, voltage_unit, voltage_basis, device.n_cells)
    except units.UnitConversionError as exc:
        issues.append(ValidationIssue("error", cid, str(exc)))
        return None, issues
    if cond is not None:
        issues += check_conditions(cond, cid)
    issues += check_curve_values(j, v, cid)
    if any(i.level == "error" for i in issues):
        return None, issues

    log = list(transformations or [])
    if units.current_is_total(current_unit):
        log.append(f"j [A/cm²] = I [{current_unit}] × {units.CURRENT_UNITS[current_unit][1]:g} / "
                   f"A_active ({device.active_area_cm2:g} cm²)")
    elif current_unit != "A/cm²":
        log.append(f"j [A/cm²] = valor [{current_unit}] × {units.CURRENT_UNITS[current_unit][1]:g}")
    if voltage_basis == "stack":
        log.append(f"V_cell [V] = V_stack [{voltage_unit}] × {units.VOLTAGE_UNITS[voltage_unit]:g} / N_cells ({device.n_cells})")
    elif voltage_unit != "V":
        log.append(f"V_cell [V] = valor [{voltage_unit}] × {units.VOLTAGE_UNITS[voltage_unit]:g}")
    ci = condition_input
    if ci.temperature_unit == "°C":
        log.append(f"T = {ci.temperature} °C + 273,15 = {cond.temperature_K:.2f} K")
    if ci.pressure_unit != "atm" or ci.pressure_reference != "absoluta":
        extra = f" + ambiente {ci.ambient_kPa} kPa" if ci.pressure_reference == "manométrica" else ""
        log.append(f"P = {ci.pressure} {ci.pressure_unit} ({ci.pressure_reference}){extra} = "
                   f"{cond.cathode_pressure_atm:.6g} atm abs")
    order = np.argsort(j, kind="stable")
    if not np.array_equal(order, np.arange(j.size)):
        log.append("Puntos reordenados por corriente creciente (orden original conservado en datos brutos).")
    j, v = j[order], v[order]
    raw_frame = raw.copy() if raw is not None else pd.DataFrame({"corriente_original": j_raw, "tension_original": v_raw})
    warnings = [i.message for i in issues if i.level == "aviso"]
    curve = PolarizationCurve(
        meta=meta, conditions=cond, conditions_input=condition_input.to_dict(),
        j_A_cm2=j, v_cell_V=v, raw=raw_frame.reset_index(drop=True),
        source_file=source_file, source_sha256=source_sha256,
        mapping=mapping or {"current_unit": current_unit, "voltage_unit": voltage_unit, "voltage_basis": voltage_basis},
        transformations=log, warnings=warnings,
    )
    return curve, issues


def curves_from_table(
    table: pd.DataFrame,
    mapping: ColumnMapping,
    curve_inputs: dict[str, tuple[CurveMetadata, ConditionInput]],
    device: DeviceInfo,
    *,
    decimal: str = ".",
    source_file: str = "",
    source_sha256: str = "",
    excluded_rows: set[int] | None = None,
    edit_note: str | None = None,
) -> tuple[list[PolarizationCurve], list[ValidationIssue]]:
    """Construye curvas a partir de una tabla de texto y un mapeo de columnas.

    `curve_inputs` asocia cada valor de la columna de agrupación (o "" si no hay
    agrupación) con sus metadatos y condiciones. Las filas se identifican por su
    número de fila de datos (1 = primera fila tras el encabezado).
    """
    issues: list[ValidationIssue] = []
    for col in (mapping.current_column, mapping.voltage_column, mapping.group_column):
        if col is not None and col not in table.columns:
            issues.append(ValidationIssue("error", "", f"La columna {col!r} no existe en el archivo."))
    if mapping.current_column == mapping.voltage_column:
        issues.append(ValidationIssue("error", "", "Corriente y tensión no pueden usar la misma columna."))
    if issues:
        return [], issues
    excluded_rows = excluded_rows or set()
    data = table.copy()
    data.insert(0, "_fila", np.arange(1, len(data) + 1))
    if mapping.group_column:
        groups = {str(k): g for k, g in data.groupby(mapping.group_column, sort=False)}
        if "" in groups:
            issues.append(ValidationIssue("error", "", f"Filas sin identificador de curva en {mapping.group_column!r}: "
                                          f"{_rows(groups[''] ['_fila'].tolist())}."))
            return [], issues
    else:
        groups = {"": data}
    missing = [g for g in groups if g not in curve_inputs]
    if missing:
        issues.append(ValidationIssue("error", "", f"Faltan metadatos/condiciones para las curvas: {missing}."))
        return [], issues
    curves = []
    for gkey, g in groups.items():
        meta, cinput = curve_inputs[gkey]
        cid = meta.curve_id
        log = []
        if edit_note:
            log.append(edit_note)
        kept = g[~g["_fila"].isin(excluded_rows)]
        if len(kept) < len(g):
            log.append(f"Excluidas por el usuario {len(g) - len(kept)} fila(s): {_rows(sorted(set(g['_fila']) & excluded_rows))}.")
        rows = kept["_fila"].tolist()
        jv, i1 = parse_numeric(kept[mapping.current_column], decimal, mapping.current_column, cid, rows)
        vv, i2 = parse_numeric(kept[mapping.voltage_column], decimal, mapping.voltage_column, cid, rows)
        if i1 or i2:
            issues += i1 + i2
            continue
        raw = pd.DataFrame({"fila": rows, mapping.current_column: kept[mapping.current_column].tolist(),
                            mapping.voltage_column: kept[mapping.voltage_column].tolist()})
        curve, cissues = build_curve(
            jv, vv, meta=meta, condition_input=cinput, device=device,
            current_unit=mapping.current_unit, voltage_unit=mapping.voltage_unit,
            voltage_basis=mapping.voltage_basis, raw=raw, source_file=source_file,
            source_sha256=source_sha256, mapping=mapping.to_dict(), transformations=log)
        issues += cissues
        if curve is not None:
            curves.append(curve)
    ids = [c.curve_id for c in curves]
    if len(set(ids)) != len(ids):
        issues.append(ValidationIssue("error", "", "Hay identificadores de curva repetidos."))
        return [], issues
    return curves, issues


def check_curve_set(curves: list[PolarizationCurve]) -> list[ValidationIssue]:
    """Validaciones del conjunto: calibración presente, ids únicos, validación independiente."""
    issues = []
    if not curves:
        issues.append(ValidationIssue("error", "", "No hay curvas válidas. Se necesita al menos una curva V–I medida "
                                      "o digitalizada; un datasheet sin curva no permite calibrar."))
        return issues
    ids = [c.curve_id for c in curves]
    if len(set(ids)) != len(ids):
        issues.append(ValidationIssue("error", "", "Identificadores de curva repetidos entre archivos."))
    cal = [c for c in curves if c.meta.role == "calibración"]
    val = [c for c in curves if c.meta.role == "validación"]
    if not cal:
        issues.append(ValidationIssue("error", "", "Ninguna curva tiene rol de calibración."))
    cal_hashes = {c.normalized_sha256 for c in cal}
    for c in val:
        if c.normalized_sha256 in cal_hashes:
            issues.append(ValidationIssue("error", c.curve_id, "La curva de validación es idéntica a una curva de "
                                          "calibración: no es independiente."))
    return issues
