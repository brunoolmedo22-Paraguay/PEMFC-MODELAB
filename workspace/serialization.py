"""Serialización exacta (JSON) de los objetos existentes del Motor 1, sin modificarlos.

- Floats: JSON conserva ``repr(float)`` → ida y vuelta bit a bit. Se verifica con el
  ``normalized_sha256`` de cada curva al reconstruirla.
- ``FitConfig`` tiene ``to_dict`` en el núcleo; aquí se añade la operación inversa.
"""
from __future__ import annotations

import base64
import math
from dataclasses import asdict, fields

import numpy as np
import pandas as pd

from identification.datasets import PolarizationCurve
from identification.optimizer import FitConfig, ParameterSetting
from pemfc_core import model as core
from pemfc_core.parameters import ModelParameters
from pemfc_core.schemas import CurveMetadata, DeviceInfo


class SerializationError(ValueError):
    pass


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        x = float(obj)
        return x if math.isfinite(x) else None
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return obj


jsonable = _jsonable


# --------------------------------------------------------------------------- dispositivo (núcleo)
def device_info_to_dict(d: DeviceInfo) -> dict:
    return _jsonable(asdict(d))


def device_info_from_dict(d: dict) -> DeviceInfo:
    allowed = {f.name for f in fields(DeviceInfo)}
    return DeviceInfo(**{k: v for k, v in (d or {}).items() if k in allowed})


# --------------------------------------------------------------------------- curvas
def curve_to_dict(c: PolarizationCurve) -> dict:
    raw = c.raw if isinstance(c.raw, pd.DataFrame) else pd.DataFrame()
    return _jsonable({
        "meta": c.meta.to_dict(),
        "conditions": asdict(c.conditions),
        "conditions_input": c.conditions_input,
        "j_A_cm2": [float(x) for x in c.j_A_cm2],
        "v_cell_V": [float(x) for x in c.v_cell_V],
        "raw": {"columns": [str(x) for x in raw.columns], "data": raw.astype(object).where(raw.notna(), None).values.tolist()},
        "source_file": c.source_file, "source_sha256": c.source_sha256,
        "mapping": c.mapping, "transformations": list(c.transformations), "warnings": list(c.warnings),
        "normalized_sha256": c.normalized_sha256,
    })


def curve_from_dict(d: dict) -> PolarizationCurve:
    try:
        meta = CurveMetadata(**d["meta"])
        cond = core.OperatingConditions(**d["conditions"])
        raw = pd.DataFrame(d["raw"]["data"], columns=d["raw"]["columns"]) if d.get("raw") else pd.DataFrame()
        c = PolarizationCurve(meta=meta, conditions=cond, conditions_input=d.get("conditions_input", {}),
                              j_A_cm2=np.asarray(d["j_A_cm2"], float), v_cell_V=np.asarray(d["v_cell_V"], float),
                              raw=raw, source_file=d.get("source_file", ""), source_sha256=d.get("source_sha256", ""),
                              mapping=d.get("mapping", {}), transformations=list(d.get("transformations", [])),
                              warnings=list(d.get("warnings", [])))
    except (KeyError, TypeError, ValueError) as exc:
        raise SerializationError(f"Curva no reconstruible: {exc}") from exc
    if d.get("normalized_sha256") and c.normalized_sha256 != d["normalized_sha256"]:
        raise SerializationError(f"La curva {meta.curve_id!r} no coincide con su huella SHA-256 (datos alterados).")
    return c


def curve_from_profile_dataset(d: dict) -> PolarizationCurve:
    """Reconstruye una curva desde un dataset de perfil v0.2.0 (sin la tabla bruta original)."""
    pts = d["points"]
    meta = CurveMetadata(**d["metadata"]) if "metadata" in d else CurveMetadata(d["curve_id"], role=d.get("role", "calibración"))
    raw = pd.DataFrame({"j_A_cm2": pts["j_A_cm2"], "V_cell_V": pts["V_cell_V"]})
    c = PolarizationCurve(meta=meta, conditions=core.OperatingConditions(**d["conditions"]),
                          conditions_input=d.get("conditions_input", {}),
                          j_A_cm2=np.asarray(pts["j_A_cm2"], float), v_cell_V=np.asarray(pts["V_cell_V"], float),
                          raw=raw, source_file=d.get("source_file", ""), source_sha256=d.get("source_sha256", ""),
                          mapping=dict(d.get("mapping", {})),
                          transformations=list(d.get("transformations", []))
                          + ["Reconstruida desde un perfil v0.2.0: la tabla bruta original no forma parte del perfil."],
                          warnings=list(d.get("warnings", [])))
    if d.get("normalized_sha256") and c.normalized_sha256 != d["normalized_sha256"]:
        raise SerializationError(f"La curva {meta.curve_id!r} del perfil no coincide con su huella SHA-256.")
    return c


# --------------------------------------------------------------------------- configuración
def fit_config_to_dict(cfg: FitConfig) -> dict:
    return _jsonable(cfg.to_dict())


def fit_config_from_dict(d: dict) -> FitConfig:
    try:
        settings = {n: ParameterSetting(**s) for n, s in d["settings"].items()}
        return FitConfig(settings=settings, base_params=ModelParameters.from_dict(d["base_params"]),
                         n_starts=int(d["n_starts"]), seed=int(d["seed"]), max_nfev=int(d["max_nfev"]),
                         tolerance=float(d["tolerance"]), weighting=d["weighting"],
                         data_informed_start=bool(d["data_informed_start"]),
                         rmse_threshold_V=float(d["rmse_threshold_V"]),
                         validation_rmse_threshold_V=float(d["validation_rmse_threshold_V"]),
                         preset=d.get("preset", "personalizado"), notes=list(d.get("notes", [])))
    except (KeyError, TypeError, ValueError) as exc:
        raise SerializationError(f"Configuración de identificación no reconstruible: {exc}") from exc


# --------------------------------------------------------------------------- binarios
def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)
