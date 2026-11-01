"""Contratos de datos compartidos: dispositivo, curvas, estados y esquema de perfil."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from .parameters import ORIGINS

PROFILE_SCHEMA_ID = "pemfc-modellab/profile"
PROFILE_SCHEMA_VERSION = "1.0.0"
APP_NAME = "PEMFC ModelLab"
APP_VERSION = "0.3.0"

# Estados del perfil (excluyentes, en orden creciente de exigencia).
STATUS_NOT_CONVERGED = "NO_CONVERGIDO"
STATUS_INSUFFICIENT = "AJUSTE_INSUFICIENTE"
STATUS_FITTED = "AJUSTADO_A_CURVA"
STATUS_VALIDATED = "VALIDADO_EXPERIMENTALMENTE"
PROFILE_STATUSES = (STATUS_NOT_CONVERGED, STATUS_INSUFFICIENT, STATUS_FITTED, STATUS_VALIDATED)
USABLE_STATUSES = (STATUS_FITTED, STATUS_VALIDATED)

STATUS_DESCRIPTIONS = {
    STATUS_NOT_CONVERGED: "El optimizador no convergió. El perfil no es utilizable.",
    STATUS_INSUFFICIENT: "Convergió, pero el error supera el criterio declarado. No utilizable para simulación.",
    STATUS_FITTED: "Reproduce las curvas de calibración dentro del criterio declarado. "
                   "No demuestra capacidad predictiva fuera de esos datos.",
    STATUS_VALIDATED: "Además, reproduce curvas experimentales independientes (no usadas en el ajuste) "
                      "en al menos una condición de operación no usada en la calibración, dentro del criterio "
                      "de validación declarado. Solo en las condiciones validadas.",
}

# Validación independiente
VALIDATION_NONE = "SIN_VALIDACION_INDEPENDIENTE"
VALIDATION_PASSED = "VALIDACION_SUPERADA"
VALIDATION_FAILED = "VALIDACION_NO_SUPERADA"
VALIDATION_NOT_EXPERIMENTAL = "VALIDACION_CON_DATOS_NO_EXPERIMENTALES"
VALIDATION_SAME_CONDITION = "VALIDACION_SOLO_MISMA_CONDICION"

ROLE_CALIBRATION = "calibración"
ROLE_VALIDATION = "validación"
CURVE_ROLES = (ROLE_CALIBRATION, ROLE_VALIDATION)

QUALITY_MEASURED = "medido"
QUALITY_DIGITIZED = "digitalizado"
QUALITY_SYNTHETIC = "sintético"
QUALITY_ILLUSTRATIVE = "ilustrativo"
CURVE_QUALITIES = (QUALITY_MEASURED, QUALITY_DIGITIZED, QUALITY_SYNTHETIC, QUALITY_ILLUSTRATIVE)
EXPERIMENTAL_QUALITIES = (QUALITY_MEASURED, QUALITY_DIGITIZED)


@dataclass
class DeviceInfo:
    """Información del dispositivo. El datasheet es solo complementario."""

    name: str = ""
    manufacturer: str = ""
    model: str = ""
    n_cells: int | None = None
    n_cells_origin: str = "MEDIDO"
    active_area_cm2: float | None = None
    active_area_origin: str = "MEDIDO"
    datasheet_reference: str = ""
    notes: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not self.name.strip():
            errors.append("Indique un nombre para el dispositivo.")
        if self.n_cells is not None:
            if int(self.n_cells) != self.n_cells or self.n_cells < 1:
                errors.append("El número de celdas debe ser un entero ≥ 1.")
        if self.active_area_cm2 is not None:
            if not (math.isfinite(self.active_area_cm2) and self.active_area_cm2 > 0):
                errors.append("El área activa debe ser finita y positiva.")
        for name, origin in (("N_cells", self.n_cells_origin), ("A_active", self.active_area_origin)):
            if origin not in ORIGINS:
                errors.append(f"Origen inválido para {name}: {origin!r}.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CurveMetadata:
    curve_id: str
    role: str = ROLE_CALIBRATION
    source: str = ""
    provenance: str = ""
    quality: str = QUALITY_MEASURED
    sigma_V: float | None = None  # incertidumbre por celda declarada por el usuario
    sigma_origin: str = ""
    conditions_origin: str = "MEDIDO"
    notes: str = ""

    def validate(self) -> list[str]:
        errors = []
        if not str(self.curve_id).strip():
            errors.append("Cada curva necesita un identificador.")
        if self.role not in CURVE_ROLES:
            errors.append(f"Rol de curva inválido: {self.role!r}.")
        if self.quality not in CURVE_QUALITIES:
            errors.append(f"Calidad de curva inválida: {self.quality!r}.")
        if self.sigma_V is not None:
            if not (math.isfinite(self.sigma_V) and 0 < self.sigma_V < 0.2):
                errors.append(f"σ_V de la curva {self.curve_id!r} debe estar en (0, 0,2) V/celda.")
        if self.conditions_origin not in ORIGINS:
            errors.append(f"Origen de condiciones inválido: {self.conditions_origin!r}.")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SchemaReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


_REQUIRED_TOP = {
    "schema": str, "schema_version": str, "profile_id": str, "created_utc": str,
    "status": dict, "engine": dict, "device": dict, "parameters": list,
    "datasets": list, "fit": dict, "diagnostics": dict, "validation": dict,
    "domain": dict, "provenance": dict, "reproduction_check": dict, "warnings": list,
}


def validate_profile_dict(profile: Any) -> SchemaReport:
    """Validación estructural del perfil (sin dependencias externas)."""
    rep = SchemaReport()
    if not isinstance(profile, dict):
        rep.errors.append("El perfil debe ser un objeto JSON.")
        return rep
    for key, typ in _REQUIRED_TOP.items():
        if key not in profile:
            rep.errors.append(f"Falta el campo obligatorio {key!r}.")
        elif not isinstance(profile[key], typ):
            rep.errors.append(f"El campo {key!r} debe ser {typ.__name__}.")
    if rep.errors:
        return rep
    if profile["schema"] != PROFILE_SCHEMA_ID:
        rep.errors.append(f"Esquema desconocido: {profile['schema']!r}.")
    major = str(profile["schema_version"]).split(".")[0]
    if major != PROFILE_SCHEMA_VERSION.split(".")[0]:
        rep.errors.append(f"Versión de esquema incompatible: {profile['schema_version']} "
                          f"(soportada {PROFILE_SCHEMA_VERSION}).")
    code = profile["status"].get("code")
    if code not in PROFILE_STATUSES:
        rep.errors.append(f"Estado de perfil inválido: {code!r}.")
    for p in profile["parameters"]:
        if not isinstance(p, dict) or not {"name", "value", "unit", "origin"} <= set(p):
            rep.errors.append("Cada parámetro necesita name, value, unit y origin.")
            break
        if p["origin"] not in ORIGINS:
            rep.errors.append(f"Origen inválido en parámetro {p.get('name')!r}: {p['origin']!r}.")
        if not isinstance(p["value"], (int, float)) or not math.isfinite(float(p["value"])):
            rep.errors.append(f"Valor no finito en parámetro {p.get('name')!r}.")
    cal = [d for d in profile["datasets"] if isinstance(d, dict) and d.get("role") == ROLE_CALIBRATION]
    if not cal:
        rep.errors.append("El perfil no contiene ninguna curva de calibración: "
                          "un perfil sin curva V–I no es admisible.")
    for d in profile["datasets"]:
        pts = d.get("points", {}) if isinstance(d, dict) else {}
        if not pts.get("j_A_cm2") or len(pts.get("j_A_cm2", [])) != len(pts.get("V_cell_V", [])):
            rep.errors.append(f"Puntos ausentes o inconsistentes en la curva {d.get('curve_id')!r}.")
    if code == STATUS_VALIDATED and profile["validation"].get("status") != VALIDATION_PASSED:
        rep.errors.append("Estado VALIDADO_EXPERIMENTALMENTE sin validación independiente superada.")
    return rep
