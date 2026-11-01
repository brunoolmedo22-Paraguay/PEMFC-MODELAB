"""Proyecto portátil (.pmlproj.zip): copia de seguridad independiente del servidor y del navegador.

Estructura del ZIP:
    manifest.json                       esquema, versión, huella SHA-256 de cada registro
    records/<tipo>/<id>.json            dispositivos, conjuntos de datos, borradores, calibraciones, exportaciones
    blobs/<sha256>                      archivos originales (imágenes, CSV, auditorías) tal cual

Importar NUNCA sobrescribe: registros idénticos se omiten; un dispositivo o borrador con el mismo id
pero contenido distinto se importa como COPIA con id nuevo (y se remapean sus referencias); un
registro inmutable (datos, calibración) alterado se rechaza.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field

from identification.profiles import ProfileError, load_profile
from pemfc_core.schemas import APP_VERSION

from .model import (
    SCHEMA, SCHEMA_VERSION, Calibration, Workspace, WorkspaceError, canonical_sha256, new_id, now_utc,
)
from .serialization import SerializationError, curve_from_profile_dataset, curve_to_dict, jsonable

PROJECT_SUFFIX = ".pmlproj.zip"
MAX_PROJECT_BYTES = 150 * 1024 * 1024


# --------------------------------------------------------------------------- huellas (misma semántica que v0.2.0)
def data_key(curves, device_info) -> str:
    payload = {
        "curves": [(c.curve_id, c.meta.role, c.meta.quality, c.meta.sigma_V, c.normalized_sha256,
                    c.conditions.to_dict()) for c in curves],
        "device": (device_info.n_cells, device_info.active_area_cm2) if device_info else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def config_key(data_key_value: str, config_dict: dict | None) -> str:
    cfg = json.dumps(config_dict, sort_keys=True, default=str) if config_dict else ""
    return hashlib.sha256((data_key_value + cfg).encode()).hexdigest()


# --------------------------------------------------------------------------- migraciones de esquema
def _migrate_records(manifest: dict, records: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """Punto único de migración explícita entre versiones del esquema del espacio de trabajo."""
    ver = manifest.get("schema_version")
    if ver == SCHEMA_VERSION:
        return records, []
    raise WorkspaceError(f"Versión de proyecto {ver!r} no soportada por esta aplicación (espera {SCHEMA_VERSION}). "
                         "No se importa nada para no corromper datos.")


# --------------------------------------------------------------------------- exportación
def export_project(ws: Workspace, device_ids: list[str] | None = None) -> bytes:
    ids = set(device_ids) if device_ids else set(ws.devices)
    recs: dict[str, dict] = {}
    for key, val in ws.all_records().items():
        kind = key.split(":", 1)[0]
        if kind == "device" and key.split(":", 1)[1] not in ids:
            continue
        if kind in ("dataset", "draft", "calibration", "export") and val.get("device_id") not in ids:
            continue
        if kind == "blob":
            continue
        recs[key] = val
    needed = set()
    for key, val in recs.items():
        needed |= set((val.get("originals") or {}).values())
    buf = io.BytesIO()
    manifest = {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "app_version": APP_VERSION,
                "created_utc": now_utc(), "device_ids": sorted(ids),
                "records": {k: canonical_sha256(v) for k, v in recs.items()},
                "blobs": {}}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for key, val in sorted(recs.items()):
            kind, rid = key.split(":", 1)
            z.writestr(f"records/{kind}/{rid}.json", json.dumps(val, ensure_ascii=False, indent=1, sort_keys=True))
        for sha in sorted(needed):
            b = ws.blobs.get(sha)
            if b is None:
                continue
            z.writestr(f"blobs/{sha}", b.data)
            manifest["blobs"][sha] = {"name": b.name, "size": b.size}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True))
    return buf.getvalue()


# --------------------------------------------------------------------------- importación
@dataclass
class ImportReport:
    added: list[str] = field(default_factory=list)
    skipped_identical: list[str] = field(default_factory=list)
    copied: dict[str, str] = field(default_factory=dict)     # id original → id nuevo
    rejected: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected


def read_project(data: bytes) -> tuple[dict, dict[str, dict], dict[str, tuple[str, bytes]]]:
    if len(data) > MAX_PROJECT_BYTES:
        raise WorkspaceError(f"Proyecto demasiado grande ({len(data) / 1e6:.0f} MB).")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise WorkspaceError(f"No es un proyecto válido (ZIP ilegible): {exc}") from exc
    names = set(z.namelist())
    if "manifest.json" not in names:
        raise WorkspaceError("Falta manifest.json: no es un proyecto de PEMFC ModelLab.")
    for n in names:
        if n.startswith("/") or ".." in n.split("/"):
            raise WorkspaceError(f"Ruta insegura en el ZIP: {n!r}.")
    manifest = json.loads(z.read("manifest.json"))
    if manifest.get("schema") != SCHEMA:
        raise WorkspaceError(f"Esquema desconocido: {manifest.get('schema')!r}.")
    records = {}
    for key, digest in manifest.get("records", {}).items():
        kind, rid = key.split(":", 1)
        path = f"records/{kind}/{rid}.json"
        if path not in names:
            raise WorkspaceError(f"Falta el registro {key} declarado en el manifiesto.")
        val = json.loads(z.read(path))
        if canonical_sha256(val) != digest:
            raise WorkspaceError(f"El registro {key} no coincide con su huella (archivo alterado).")
        records[key] = val
    records, _ = _migrate_records(manifest, records)
    blobs = {}
    for sha, info in manifest.get("blobs", {}).items():
        raw = z.read(f"blobs/{sha}")
        if hashlib.sha256(raw).hexdigest() != sha:
            raise WorkspaceError(f"Binario {sha[:12]}… alterado.")
        blobs[sha] = (info.get("name", sha), raw)
    return manifest, records, blobs


def import_project(ws: Workspace, data: bytes) -> ImportReport:
    """Fusiona un proyecto en el espacio de trabajo sin sobrescribir nada."""
    manifest, records, blobs = read_project(data)
    rep = ImportReport()
    for sha, (name, raw) in blobs.items():
        ws.put_blob(name, raw)
    remap: dict[str, str] = {}

    def _apply_remap(val: dict) -> dict:
        val = dict(val)
        for k in ("device_id", "draft_id", "calibration_id"):
            if val.get(k) in remap:
                val[k] = remap[val[k]]
        if "calibration_ids" in val:
            val["calibration_ids"] = [remap.get(x, x) for x in val["calibration_ids"]]
        if val.get("active_calibration_id") in remap:
            val["active_calibration_id"] = remap[val["active_calibration_id"]]
        return val

    order = {"device": 0, "dataset": 1, "draft": 2, "calibration": 3, "export": 4}
    for key in sorted(records, key=lambda k: order.get(k.split(":", 1)[0], 9)):
        kind, rid = key.split(":", 1)
        val = _apply_remap(records[key])
        existing = ws.record_value(key)
        if existing is not None:
            if canonical_sha256(existing) == canonical_sha256(val):
                rep.skipped_identical.append(key)
                continue
            if kind in ("dataset", "calibration", "export"):
                rep.rejected.append(f"{key}: ya existe con contenido distinto (registro inmutable); no se importa.")
                continue
            nid = new_id({"device": "dev", "draft": "drf"}[kind])
            remap[rid] = nid
            val = dict(val, id=nid)
            if kind == "device":
                val["name"] = f"{val['name']} (importado)"
            else:
                val["title"] = f"{val.get('title', '')} (importado)"
            key = f"{kind}:{nid}"
            rep.copied[rid] = nid
        try:
            ws.load_record(key, val)
            ws.dirty.add(key)
            ws.base_rev.pop(key, None)
            rep.added.append(key)
        except (WorkspaceError, TypeError, ValueError, KeyError) as exc:
            rep.rejected.append(f"{key}: {exc}")
    # tras remapear dispositivos, las referencias de registros ya cargados se corrigen
    for key in list(rep.added):
        kind, rid = key.split(":", 1)
        obj = ws._store(kind)[rid]
        for attr in ("device_id", "draft_id"):
            if getattr(obj, attr, None) in remap:
                setattr(obj, attr, remap[getattr(obj, attr)])
    rep.messages.append(f"Proyecto v{manifest.get('app_version')} ({manifest.get('created_utc')}): "
                        f"{len(rep.added)} registro(s) añadidos, {len(rep.skipped_identical)} idénticos omitidos, "
                        f"{len(rep.copied)} copiados con id nuevo, {len(rep.rejected)} rechazados.")
    return rep


# --------------------------------------------------------------------------- migración de perfiles v0.2.0
@dataclass
class MigrationResult:
    device_id: str
    dataset_id: str
    calibration_id: str
    reproduction_ok: bool
    max_reproduction_error_V: float
    messages: list[str]


def import_v020_profile(ws: Workspace, data: bytes, filename: str = "profile.json",
                        device_id: str | None = None) -> MigrationResult:
    """Convierte un perfil exportado por v0.1/v0.2 en dispositivo + datos + calibración (migrada).

    El perfil se conserva INTACTO dentro de la calibración (sigue siendo importable con load_profile).
    Si se indica ``device_id`` se asocia a ese dispositivo; si no, se crea uno nuevo (nunca se fusiona
    por nombre).
    """
    try:
        loaded = load_profile(data)
    except ProfileError as exc:
        raise WorkspaceError(f"Perfil no importable: {exc}") from exc
    prof = loaded.profile
    if device_id is None:
        dev_info = loaded.device
        dev = ws.create_device(dev_info.name or "Dispositivo importado", dev_info.manufacturer, dev_info.model,
                               n_cells=dev_info.n_cells, n_cells_origin=dev_info.n_cells_origin,
                               active_area_cm2=dev_info.active_area_cm2, active_area_origin=dev_info.active_area_origin,
                               datasheet_reference=dev_info.datasheet_reference, notes=dev_info.notes,
                               provenance=f"Migrado desde el perfil {prof['profile_id']} ({filename}).")
        device_id = dev.id
    elif device_id not in ws.devices:
        raise WorkspaceError("Dispositivo de destino inexistente.")
    try:
        curves = [curve_from_profile_dataset(d) for d in prof["datasets"]]
    except SerializationError as exc:
        raise WorkspaceError(str(exc)) from exc
    ds = ws.add_dataset(device_id, f"Datos del perfil {prof['profile_id']}", "perfil_v020",
                        [curve_to_dict(c) for c in curves], {filename: data},
                        notes="Curvas reconstruidas a partir del perfil (sin tabla bruta original).")
    dk = data_key(curves, loaded.device)
    ck = config_key(dk, prof.get("fit", {}).get("config"))
    cal = Calibration(new_id("cal"), device_id, None, json.loads(json.dumps(prof)), dk, ck, origin="migrada_v020",
                      label=f"Perfil {prof['profile_id']} (v0.2.0)", app_version=str(prof.get("engine", {}).get(
                          "app_version", "0.2.0"))).seal()
    ws.calibrations[cal.id] = cal
    ws.dirty.add(f"calibration:{cal.id}")
    msgs = list(loaded.messages)
    msgs.insert(0, f"Reproducción del perfil: error máximo {loaded.max_reproduction_error_V:.2e} V "
                   f"({'OK' if loaded.reproduction_ok else 'FUERA DE TOLERANCIA'}).")
    return MigrationResult(device_id, ds.id, cal.id, loaded.reproduction_ok, loaded.max_reproduction_error_V, msgs)


def workspace_jsonable(ws: Workspace) -> dict:
    return jsonable(ws.all_records())
