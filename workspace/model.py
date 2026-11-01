"""Espacio de trabajo del Motor 1 (v0.3.0): objetos persistentes y sus invariantes.

Objetos (claves de almacenamiento entre paréntesis):
- Dispositivo ``Device`` (``device:<id>``): entidad persistente; id estable e independiente del nombre.
- Conjunto de datos ``Dataset`` (``dataset:<id>``): curvas experimentales importadas (CSV, pegado,
  ejemplo, imagen digitalizada o perfil v0.2.0). Inmutable una vez registrado.
- Borrador de identificación ``Draft`` (``draft:<id>``): trabajo en curso (curvas, configuración,
  etapa). Editable; se guarda explícita o automáticamente.
- Calibración ``Calibration`` (``calibration:<id>``): ejecución del optimizador. INMUTABLE: guarda el
  perfil completo generado (formato v0.2.0, reimportable con ``load_profile``).
- Exportación ``ProfileExport`` (``export:<id>``): registro de cada descarga de un perfil.
- Binarios ``blob:<sha256>``: archivos originales (CSV, imágenes, auditorías), deduplicados.

Reglas: nunca se sobrescribe una calibración; una nueva identificación crea una calibración nueva;
el «perfil activo» es una selección ADMINISTRATIVA que no altera el estado científico del perfil.
"""
from __future__ import annotations

import hashlib
import json
import math
import secrets
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone

from pemfc_core.schemas import APP_VERSION, ORIGINS, DeviceInfo

from .serialization import b64decode, b64encode, jsonable

SCHEMA = "pemfc-modellab/workspace"
SCHEMA_VERSION = "1.0.0"

# Estado ADMINISTRATIVO del dispositivo (catálogo). No es calidad científica.
ADM_NEW = "NUEVO"
ADM_INCOMPLETE = "CONFIGURACION_INCOMPLETA"
ADM_IN_PROGRESS = "EN_CALIBRACION"
ADM_FITTED = "PERFIL_AJUSTADO"
ADM_VALIDATED = "PERFIL_CON_VALIDACION"
ADM_TEXT = {
    ADM_NEW: "Nuevo", ADM_INCOMPLETE: "Configuración incompleta", ADM_IN_PROGRESS: "Calibración en progreso",
    ADM_FITTED: "Perfil ajustado", ADM_VALIDATED: "Perfil con validación experimental",
}
VALIDATED_CODE = "VALIDADO_EXPERIMENTALMENTE"


class WorkspaceError(ValueError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5)}"


def canonical_sha256(obj) -> str:
    return hashlib.sha256(json.dumps(jsonable(obj), sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _num(v, positive=True):
    if v is None or v == "":
        return None
    x = float(v)
    if not math.isfinite(x) or (positive and x <= 0):
        raise WorkspaceError(f"Valor numérico inválido: {v!r} (debe ser finito{' y positivo' if positive else ''}).")
    return x


# --------------------------------------------------------------------------- registros
@dataclass
class Device:
    id: str
    name: str
    manufacturer: str = ""
    model: str = ""
    technology: str = ""                 # p. ej. PEMFC de baja temperatura
    configuration: str = ""              # p. ej. stack refrigerado por aire
    n_cells: int | None = None
    n_cells_origin: str = "MEDIDO"
    active_area_cm2: float | None = None
    active_area_origin: str = "MEDIDO"
    rated_power_W: float | None = None
    nominal_voltage_V: float | None = None
    nominal_current_A: float | None = None
    datasheet_reference: str = ""
    notes: str = ""
    provenance: str = ""
    active_calibration_id: str | None = None   # perfil activo (selección administrativa)
    archived: bool = False
    created_utc: str = field(default_factory=now_utc)
    updated_utc: str = field(default_factory=now_utc)
    rev: int = 1

    EDITABLE = ("name", "manufacturer", "model", "technology", "configuration", "n_cells", "n_cells_origin",
                "active_area_cm2", "active_area_origin", "rated_power_W", "nominal_voltage_V", "nominal_current_A",
                "datasheet_reference", "notes", "provenance")

    def validate(self) -> list[str]:
        errs = []
        if not str(self.name).strip():
            errs.append("El nombre del dispositivo es obligatorio.")
        if self.n_cells is not None and (int(self.n_cells) != self.n_cells or self.n_cells < 1):
            errs.append("El número de celdas debe ser un entero ≥ 1.")
        for k in ("active_area_cm2", "rated_power_W", "nominal_voltage_V", "nominal_current_A"):
            v = getattr(self, k)
            if v is not None and not (math.isfinite(float(v)) and float(v) > 0):
                errs.append(f"{k}: debe ser finito y positivo.")
        for k in ("n_cells_origin", "active_area_origin"):
            if getattr(self, k) not in ORIGINS:
                errs.append(f"{k}: origen inválido {getattr(self, k)!r}.")
        return errs

    def to_device_info(self) -> DeviceInfo:
        return DeviceInfo(name=self.name, manufacturer=self.manufacturer, model=self.model, n_cells=self.n_cells,
                          n_cells_origin=self.n_cells_origin, active_area_cm2=self.active_area_cm2,
                          active_area_origin=self.active_area_origin, datasheet_reference=self.datasheet_reference,
                          notes=self.notes)

    @property
    def missing_for_identification(self) -> list[str]:
        """Propiedades no declaradas. Solo bloquean si las unidades de los datos las requieren."""
        out = []
        if self.n_cells is None:
            out.append("número de celdas")
        if self.active_area_cm2 is None:
            out.append("área activa")
        return out


@dataclass
class Dataset:
    id: str
    device_id: str
    label: str
    source_kind: str                      # csv | pegado | ejemplo | imagen | perfil_v020
    curves: list[dict]                    # serialización exacta (workspace.serialization.curve_to_dict)
    originals: dict[str, str] = field(default_factory=dict)   # nombre → sha256 del blob
    notes: str = ""
    created_utc: str = field(default_factory=now_utc)
    rev: int = 1
    content_sha256: str = ""

    def seal(self) -> "Dataset":
        self.content_sha256 = canonical_sha256({"curves": self.curves, "originals": self.originals})
        return self


@dataclass
class Draft:
    id: str
    device_id: str
    title: str
    stage: int = 1                         # 1..6
    curves: list[dict] = field(default_factory=list)
    originals: dict[str, str] = field(default_factory=dict)
    dataset_label: str = ""
    dataset_ids: list[str] = field(default_factory=list)
    fit_config: dict | None = None
    data_key: str = ""                     # huella de datos+geometría del dispositivo
    config_key: str = ""                   # huella de la configuración
    calibration_ids: list[str] = field(default_factory=list)
    stage_notes: dict = field(default_factory=dict)
    status: str = "abierto"                # abierto | cerrado
    created_utc: str = field(default_factory=now_utc)
    updated_utc: str = field(default_factory=now_utc)
    saved_explicitly_utc: str | None = None
    rev: int = 1


@dataclass
class Calibration:
    id: str
    device_id: str
    draft_id: str | None
    profile: dict
    data_key: str
    config_key: str
    origin: str = "ejecutada"              # ejecutada | migrada_v020 | importada
    label: str = ""
    app_version: str = APP_VERSION
    created_utc: str = field(default_factory=now_utc)
    content_sha256: str = ""

    def seal(self) -> "Calibration":
        self.content_sha256 = canonical_sha256({"profile": self.profile, "data_key": self.data_key,
                                                "config_key": self.config_key, "device_id": self.device_id})
        return self

    # resúmenes derivados del perfil (sin duplicar datos)
    @property
    def profile_id(self) -> str:
        return self.profile.get("profile_id", "")

    @property
    def status_code(self) -> str:
        return self.profile.get("status", {}).get("code", "")

    @property
    def validation_status(self) -> str:
        return self.profile.get("validation", {}).get("status", "")

    @property
    def usable(self) -> bool:
        return bool(self.profile.get("status", {}).get("usable_for_simulation", False))

    @property
    def rmse_V(self) -> float | None:
        return (self.profile.get("fit", {}).get("metrics_calibration") or {}).get("rmse_V")

    @property
    def curve_ids(self) -> list[str]:
        return [d["curve_id"] for d in self.profile.get("datasets", [])]

    @property
    def free_parameters(self) -> list[str]:
        return list(self.profile.get("fit", {}).get("free_parameters", []))

    def parameters(self) -> dict[str, float]:
        return {p["name"]: p["value"] for p in self.profile.get("parameters", [])}


@dataclass
class ProfileExport:
    id: str
    device_id: str
    calibration_id: str
    profile_id: str
    filename: str
    sha256: str
    kind: str = "profile.json"             # profile.json | zip
    created_utc: str = field(default_factory=now_utc)


@dataclass
class Experiment:
    """Ejecución de una bancada del Motor 2 (inmutable, sellada). Referencia la calibración usada."""
    id: str
    device_id: str
    calibration_id: str
    profile_id: str
    bench: str
    name: str
    result: dict
    app_version: str = ""
    model: dict = field(default_factory=dict)
    study_id: str | None = None
    duplicated_from: str | None = None
    created_utc: str = field(default_factory=now_utc)
    content_sha256: str = ""

    def seal(self) -> "Experiment":
        d = asdict(self)
        d.pop("content_sha256", None)
        self.content_sha256 = canonical_sha256(jsonable(d))
        return self


@dataclass
class Blob:
    sha256: str
    name: str
    size: int
    data_b64: str

    @property
    def data(self) -> bytes:
        return b64decode(self.data_b64)


_TYPES = {"device": Device, "dataset": Dataset, "draft": Draft, "calibration": Calibration, "export": ProfileExport,
          "experiment": Experiment}
_IMMUTABLE = {"dataset", "calibration", "export", "blob", "experiment"}


def _from(cls, d: dict):
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in allowed})


# --------------------------------------------------------------------------- espacio de trabajo
class Workspace:
    """Colección en memoria + registro de cambios pendientes de persistir."""

    def __init__(self):
        self.devices: dict[str, Device] = {}
        self.datasets: dict[str, Dataset] = {}
        self.drafts: dict[str, Draft] = {}
        self.calibrations: dict[str, Calibration] = {}
        self.exports: dict[str, ProfileExport] = {}
        self.experiments: dict[str, Experiment] = {}
        self.blobs: dict[str, Blob] = {}
        self.dirty: set[str] = set()
        self.deleted: set[str] = set()          # claves a borrar también en el almacenamiento persistente
        self.base_rev: dict[str, int] = {}     # revisión con la que se cargó cada registro mutable

    # ---------------------------------------------------------------- utilidades
    def _store(self, kind: str):
        return {"device": self.devices, "dataset": self.datasets, "draft": self.drafts,
                "calibration": self.calibrations, "export": self.exports, "experiment": self.experiments}[kind]

    def _touch(self, kind: str, obj) -> None:
        if hasattr(obj, "updated_utc"):
            obj.updated_utc = now_utc()
        if hasattr(obj, "rev") and kind not in _IMMUTABLE:
            obj.rev = int(obj.rev) + 1
        self.dirty.add(f"{kind}:{obj.id}")

    def put_blob(self, name: str, data: bytes) -> str:
        sha = hashlib.sha256(data).hexdigest()
        self.deleted.discard(f"blob:{sha}")
        if sha not in self.blobs:
            self.blobs[sha] = Blob(sha, name, len(data), b64encode(data))
            self.dirty.add(f"blob:{sha}")
        return sha

    def blob_bytes(self, sha: str) -> bytes | None:
        b = self.blobs.get(sha)
        return b.data if b else None

    def originals_bytes(self, refs: dict[str, str]) -> dict[str, bytes]:
        out = {}
        for name, sha in refs.items():
            data = self.blob_bytes(sha)
            if data is not None:
                out[name] = data
        return out

    # ---------------------------------------------------------------- dispositivos
    def create_device(self, name: str, manufacturer: str = "", model: str = "", **extra) -> Device:
        d = Device(id=new_id("dev"), name=str(name).strip(), manufacturer=str(manufacturer).strip(),
                   model=str(model).strip())
        for k, v in extra.items():
            if k in Device.EDITABLE:
                setattr(d, k, v)
        errs = d.validate()
        if errs:
            raise WorkspaceError(" ".join(errs))
        self.devices[d.id] = d
        self.dirty.add(f"device:{d.id}")
        return d

    def update_device(self, device_id: str, **changes) -> Device:
        d = self.devices[device_id]
        old = asdict(d)
        for k, v in changes.items():
            if k not in Device.EDITABLE:
                raise WorkspaceError(f"Campo no editable: {k}.")
            if k == "n_cells" and v not in (None, ""):
                v = int(v)
            elif k in ("active_area_cm2", "rated_power_W", "nominal_voltage_V", "nominal_current_A"):
                v = _num(v)
            elif isinstance(v, str):
                v = v.strip()
            setattr(d, k, None if v == "" and k in ("n_cells",) else v)
        errs = d.validate()
        if errs:
            for k, v in old.items():
                setattr(d, k, v)
            raise WorkspaceError(" ".join(errs))
        if asdict(d) != old:
            self._touch("device", d)
        return d

    def set_active_calibration(self, device_id: str, calibration_id: str | None) -> None:
        """Selección ADMINISTRATIVA del perfil de referencia. No cambia su estado científico."""
        d = self.devices[device_id]
        if calibration_id is not None:
            c = self.calibrations.get(calibration_id)
            if c is None or c.device_id != device_id:
                raise WorkspaceError("La calibración no pertenece a este dispositivo.")
            if not c.usable:
                raise WorkspaceError(f"El perfil {c.profile_id} tiene estado {c.status_code}: no es utilizable "
                                     "para simulación y no puede ser el perfil activo.")
        if d.active_calibration_id != calibration_id:
            d.active_calibration_id = calibration_id
            self._touch("device", d)

    def archive_device(self, device_id: str, archived: bool = True) -> None:
        d = self.devices[device_id]
        if d.archived != archived:
            d.archived = archived
            self._touch("device", d)

    # ---------------------------------------------------------------- datos y borradores
    def add_dataset(self, device_id: str, label: str, source_kind: str, curves: list[dict],
                    originals: dict[str, bytes] | None = None, notes: str = "") -> Dataset:
        if device_id not in self.devices:
            raise WorkspaceError("Dispositivo inexistente.")
        refs = {name: self.put_blob(name, data) for name, data in (originals or {}).items()}
        ds = Dataset(new_id("set"), device_id, label, source_kind, list(curves), refs, notes).seal()
        self.datasets[ds.id] = ds
        self.dirty.add(f"dataset:{ds.id}")
        return ds

    def new_draft(self, device_id: str, title: str = "") -> Draft:
        if device_id not in self.devices:
            raise WorkspaceError("Dispositivo inexistente.")
        n = sum(1 for d in self.drafts.values() if d.device_id == device_id) + 1
        dr = Draft(new_id("drf"), device_id, title or f"Identificación {n}")
        self.drafts[dr.id] = dr
        self.dirty.add(f"draft:{dr.id}")
        return dr

    def update_draft(self, draft_id: str, explicit: bool = False, **changes) -> Draft:
        dr = self.drafts[draft_id]
        if dr.status == "cerrado":
            raise WorkspaceError("El borrador está cerrado; cree una identificación nueva.")
        allowed = {"title", "stage", "curves", "dataset_label", "dataset_ids", "fit_config", "data_key", "config_key",
                   "stage_notes"}
        changed = False
        for k, v in changes.items():
            if k not in allowed:
                raise WorkspaceError(f"Campo de borrador no editable: {k}.")
            if getattr(dr, k) != v:
                setattr(dr, k, v)
                changed = True
        if "originals" in changes:
            raise WorkspaceError("Use set_draft_originals.")
        if explicit:
            dr.saved_explicitly_utc = now_utc()
            changed = True
        if changed:
            self._touch("draft", dr)
        return dr

    def set_draft_originals(self, draft_id: str, originals: dict[str, bytes]) -> None:
        dr = self.drafts[draft_id]
        refs = {name: self.put_blob(name, data) for name, data in originals.items()}
        if refs != dr.originals:
            dr.originals = refs
            self._touch("draft", dr)

    # ---------------------------------------------------------------- calibraciones
    def record_calibration(self, draft_id: str, profile: dict, data_key: str, config_key: str,
                           label: str = "") -> Calibration:
        """Registra una ejecución como objeto NUEVO e inmutable (nunca sobrescribe otra)."""
        dr = self.drafts[draft_id]
        n = sum(1 for c in self.calibrations.values() if c.device_id == dr.device_id) + 1
        cal = Calibration(new_id("cal"), dr.device_id, dr.id, json.loads(json.dumps(profile)), data_key, config_key,
                          label=label or f"Calibración {n}").seal()
        self.calibrations[cal.id] = cal
        self.dirty.add(f"calibration:{cal.id}")
        dr.calibration_ids = list(dr.calibration_ids) + [cal.id]
        self._touch("draft", dr)
        return cal

    def record_export(self, calibration_id: str, filename: str, data: bytes, kind: str = "profile.json") -> ProfileExport:
        c = self.calibrations[calibration_id]
        ex = ProfileExport(new_id("out"), c.device_id, c.id, c.profile_id, filename,
                           hashlib.sha256(data).hexdigest(), kind)
        self.exports[ex.id] = ex
        self.dirty.add(f"export:{ex.id}")
        return ex

    def device_keys(self, device_id: str) -> list[str]:
        """Todas las claves de registros que pertenecen al dispositivo (sin binarios)."""
        keys = [f"device:{device_id}"]
        for kind in ("dataset", "draft", "calibration", "export", "experiment"):
            keys += [f"{kind}:{rid}" for rid, obj in self._store(kind).items() if obj.device_id == device_id]
        return keys

    def device_blob_refs(self, device_id: str) -> set[str]:
        refs = set()
        for kind in ("dataset", "draft"):
            for obj in self._store(kind).values():
                if obj.device_id == device_id:
                    refs |= set(obj.originals.values())
        return refs

    def delete_device(self, device_id: str, confirm_name: str) -> dict:
        """Elimina DELIBERADAMENTE un dispositivo y todo lo asociado. Exige repetir su nombre exacto.

        Se borran sus conjuntos de datos, borradores, calibraciones, registros de exportación y los
        binarios que ningún otro dispositivo use. Devuelve un resumen de lo eliminado.
        """
        d = self.devices.get(device_id)
        if d is None:
            raise WorkspaceError("Dispositivo inexistente.")
        if str(confirm_name).strip() != d.name.strip():
            raise WorkspaceError("Confirmación incorrecta: escriba exactamente el nombre del dispositivo.")
        keys = self.device_keys(device_id)
        own = self.device_blob_refs(device_id)
        others = set()
        for kind in ("dataset", "draft"):
            for obj in self._store(kind).values():
                if obj.device_id != device_id:
                    others |= set(obj.originals.values())
        summary = {"device": d.name, "datasets": 0, "drafts": 0, "calibrations": 0, "exports": 0, "experiments": 0,
                   "blobs": 0}
        for key in keys:
            kind, rid = key.split(":", 1)
            self._store(kind).pop(rid, None)
            if kind != "device":
                summary[kind + "s"] += 1
            self.dirty.discard(key)
            self.base_rev.pop(key, None)
            self.deleted.add(key)
        for sha in own - others:
            if self.blobs.pop(sha, None) is not None:
                summary["blobs"] += 1
                self.dirty.discard(f"blob:{sha}")
                self.deleted.add(f"blob:{sha}")
        return summary

    # ---------------------------------------------------------------- Motor 2: experimentos
    def add_experiment(self, device_id: str, calibration_id: str, bench: str, name: str, result: dict,
                       model: dict | None = None, study_id: str | None = None,
                       duplicated_from: str | None = None) -> Experiment:
        from pemfc_core.schemas import APP_VERSION
        if device_id not in self.devices:
            raise WorkspaceError("Dispositivo inexistente.")
        cal = self.calibrations.get(calibration_id)
        if cal is None or cal.device_id != device_id:
            raise WorkspaceError("La calibración no pertenece al dispositivo.")
        name = str(name).strip() or f"{bench} {now_utc()}"
        ex = Experiment(new_id("exp"), device_id, calibration_id, cal.profile_id, bench, name, jsonable(result),
                        APP_VERSION, model or {}, study_id, duplicated_from).seal()
        self.experiments[ex.id] = ex
        self.dirty.add(f"experiment:{ex.id}")
        return ex

    def device_experiments(self, device_id: str) -> list[Experiment]:
        return sorted((e for e in self.experiments.values() if e.device_id == device_id),
                      key=lambda e: e.created_utc, reverse=True)

    # ---------------------------------------------------------------- consultas
    def device_calibrations(self, device_id: str) -> list[Calibration]:
        return sorted((c for c in self.calibrations.values() if c.device_id == device_id),
                      key=lambda c: c.created_utc, reverse=True)

    def device_drafts(self, device_id: str) -> list[Draft]:
        return sorted((d for d in self.drafts.values() if d.device_id == device_id),
                      key=lambda d: d.updated_utc, reverse=True)

    def device_datasets(self, device_id: str) -> list[Dataset]:
        return sorted((d for d in self.datasets.values() if d.device_id == device_id),
                      key=lambda d: d.created_utc, reverse=True)

    def device_exports(self, device_id: str) -> list[ProfileExport]:
        return sorted((e for e in self.exports.values() if e.device_id == device_id),
                      key=lambda e: e.created_utc, reverse=True)

    def admin_status(self, device_id: str) -> str:
        cals = self.device_calibrations(device_id)
        if any(c.status_code == VALIDATED_CODE for c in cals):
            return ADM_VALIDATED
        if any(c.usable for c in cals):
            return ADM_FITTED
        if any(d.curves or d.calibration_ids for d in self.device_drafts(device_id)) or cals:
            return ADM_IN_PROGRESS
        if self.devices[device_id].missing_for_identification:
            return ADM_INCOMPLETE if (self.device_drafts(device_id) or self.device_datasets(device_id)) else ADM_NEW
        return ADM_NEW

    def summary(self, device_id: str) -> dict:
        d = self.devices[device_id]
        cals = self.device_calibrations(device_id)
        active = self.calibrations.get(d.active_calibration_id) if d.active_calibration_id else None
        stamps = [d.updated_utc] + [x.updated_utc for x in self.device_drafts(device_id)] + [c.created_utc for c in cals]
        return {
            "id": d.id, "name": d.name, "manufacturer": d.manufacturer, "model": d.model,
            "n_cells": d.n_cells, "active_area_cm2": d.active_area_cm2, "archived": d.archived,
            "admin_status": self.admin_status(device_id),
            "admin_text": ADM_TEXT[self.admin_status(device_id)],
            "n_calibrations": len(cals), "n_drafts": len(self.device_drafts(device_id)),
            "n_datasets": len(self.device_datasets(device_id)),
            "active_profile": None if active is None else {"calibration_id": active.id, "profile_id": active.profile_id,
                                                           "status_code": active.status_code,
                                                           "validation": active.validation_status},
            "last_modified_utc": max(stamps),
        }

    def list_devices(self, query: str = "", status: str | None = None, manufacturer: str | None = None,
                     sort: str = "recientes", include_archived: bool = False) -> list[dict]:
        q = query.strip().lower()
        rows = []
        for d in self.devices.values():
            if d.archived and not include_archived:
                continue
            s = self.summary(d.id)
            hay = " ".join([d.name, d.manufacturer, d.model, d.id]).lower()
            if q and q not in hay:
                continue
            if status and s["admin_status"] != status:
                continue
            if manufacturer and d.manufacturer != manufacturer:
                continue
            rows.append(s)
        key = {"recientes": lambda s: s["last_modified_utc"], "nombre": lambda s: s["name"].lower(),
               "fabricante": lambda s: (s["manufacturer"].lower(), s["name"].lower()),
               "estado": lambda s: (s["admin_status"], s["name"].lower())}.get(sort, lambda s: s["last_modified_utc"])
        return sorted(rows, key=key, reverse=(sort == "recientes"))

    # ---------------------------------------------------------------- persistencia por registros
    def record_value(self, key: str) -> dict | None:
        kind, _, rid = key.partition(":")
        if kind == "blob":
            b = self.blobs.get(rid)
            return None if b is None else asdict(b)
        obj = self._store(kind).get(rid)
        return None if obj is None else jsonable(asdict(obj))

    def pending(self) -> list[dict]:
        """Operaciones pendientes (escrituras y borrados) para el puente de almacenamiento."""
        ops = [{"key": k, "delete": True} for k in sorted(self.deleted)]
        for key in sorted(self.dirty):
            val = self.record_value(key)
            if val is None:
                continue
            kind = key.split(":", 1)[0]
            ops.append({"key": key, "rev": int(val.get("rev", 1)) if kind not in _IMMUTABLE else 0,
                        "base_rev": self.base_rev.get(key, 0), "immutable": kind in _IMMUTABLE,
                        "value": json.dumps(val, ensure_ascii=False)})
        return ops

    def mark_saved(self, keys) -> None:
        for k in keys:
            self.deleted.discard(k)
            self.dirty.discard(k)
            v = self.record_value(k)
            if v is not None and "rev" in v:
                self.base_rev[k] = int(v["rev"])

    def load_record(self, key: str, value: dict) -> None:
        kind, _, rid = key.partition(":")
        if kind == "blob":
            b = _from(Blob, value)
            if hashlib.sha256(b.data).hexdigest() != rid:
                raise WorkspaceError(f"Binario {rid[:12]}… alterado (SHA-256 distinto).")
            self.blobs[rid] = b
            return
        cls = _TYPES.get(kind)
        if cls is None:
            return
        self.deleted.discard(key)
        obj = _from(cls, value)
        if kind == "calibration":
            expect = obj.content_sha256
            if expect and Calibration(**{f.name: getattr(obj, f.name) for f in fields(Calibration)}).seal().content_sha256 != expect:
                raise WorkspaceError(f"Calibración {rid} alterada (huella de contenido distinta).")
        if kind == "experiment":
            expect = obj.content_sha256
            if not expect or _from(Experiment, asdict(obj)).seal().content_sha256 != expect:
                raise WorkspaceError(f"Experimento {rid} alterado (huella de contenido distinta).")
        if kind == "dataset" and obj.content_sha256:
            if canonical_sha256({"curves": obj.curves, "originals": obj.originals}) != obj.content_sha256:
                raise WorkspaceError(f"Conjunto de datos {rid} alterado (huella de contenido distinta).")
        self._store(kind)[rid] = obj
        if hasattr(obj, "rev"):
            self.base_rev[key] = int(obj.rev)

    @classmethod
    def from_records(cls, records: dict[str, dict]) -> tuple["Workspace", list[str]]:
        ws, problems = cls(), []
        for key in sorted(records, key=lambda k: (not k.startswith("blob:"), k)):
            try:
                ws.load_record(key, records[key])
            except (WorkspaceError, TypeError, ValueError, KeyError) as exc:
                problems.append(f"{key}: {exc}")
        return ws, problems

    def all_records(self) -> dict[str, dict]:
        out = {}
        for kind in ("device", "dataset", "draft", "calibration", "export", "experiment"):
            for rid in self._store(kind):
                out[f"{kind}:{rid}"] = self.record_value(f"{kind}:{rid}")
        for sha in self.blobs:
            out[f"blob:{sha}"] = self.record_value(f"blob:{sha}")
        return out
