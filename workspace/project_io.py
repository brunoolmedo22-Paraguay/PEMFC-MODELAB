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
DEVICE_SUFFIX = ".pmldevice.zip"
MAX_PROJECT_BYTES = 150 * 1024 * 1024          # archivo comprimido
MAX_UNCOMPRESSED_BYTES = 600 * 1024 * 1024     # suma descomprimida (protección contra bombas ZIP)
MAX_ENTRIES = 20_000
MAX_RATIO = 200                                # compresión máxima admitida por entrada


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
        if kind in ("dataset", "draft", "calibration", "export", "experiment") and val.get("device_id") not in ids:
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
    infos = z.infolist()
    if len(infos) > MAX_ENTRIES:
        raise WorkspaceError(f"Demasiadas entradas en el ZIP ({len(infos)}).")
    total = 0
    for info in infos:
        total += info.file_size
        if info.file_size > 0 and info.compress_size > 0 and info.file_size / info.compress_size > MAX_RATIO \
                and info.file_size > 1_000_000:
            raise WorkspaceError(f"Compresión anómala en {info.filename!r} (posible bomba ZIP).")
    if total > MAX_UNCOMPRESSED_BYTES:
        raise WorkspaceError(f"El contenido descomprimido ({total / 1e6:.0f} MB) supera el máximo admitido.")
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


@dataclass
class PackageAnalysis:
    """Resumen previo a importar (no modifica nada)."""
    manifest: dict
    devices: list[dict]                       # [{id, name, manufacturer, model, n_calibrations, …, conflict}]
    n_records: int
    n_blobs: int
    warnings: list[str] = field(default_factory=list)

    @property
    def conflicts(self) -> list[dict]:
        return [d for d in self.devices if d["conflict"]]


def analyze_package(ws: Workspace, data: bytes) -> PackageAnalysis:
    """Valida el paquete (integridad, rutas, tamaño, versión) y detecta conflictos de identificador."""
    manifest, records, blobs = read_project(data)
    devs = []
    for key, val in records.items():
        if not key.startswith("device:"):
            continue
        rid = key.split(":", 1)[1]
        count = lambda kind: sum(1 for k, v in records.items() if k.startswith(kind + ":") and v.get("device_id") == rid)  # noqa: E731
        existing = ws.devices.get(rid)
        same = existing is not None and canonical_sha256(ws.record_value(key)) == canonical_sha256(val)
        devs.append({"id": rid, "name": val.get("name", ""), "manufacturer": val.get("manufacturer", ""),
                     "model": val.get("model", ""), "n_calibrations": count("calibration"),
                     "n_drafts": count("draft"), "n_datasets": count("dataset"),
                     "conflict": existing is not None, "identical": same,
                     "existing_name": existing.name if existing else None})
    warns = []
    if manifest.get("app_version") and manifest["app_version"] != APP_VERSION:
        warns.append(f"Paquete creado con PEMFC ModelLab {manifest['app_version']} (esta es {APP_VERSION}); el "
                     "esquema es compatible.")
    return PackageAnalysis(manifest, devs, len(records), len(blobs), warns)


def import_project(ws: Workspace, data: bytes, strategy: dict[str, str] | None = None) -> ImportReport:
    """Importa un paquete. ``strategy``: id de dispositivo en conflicto → «copia» | «reemplazar» | «omitir».

    Por defecto (sin estrategia) nunca se sobrescribe: lo distinto entra como copia. «reemplazar» elimina
    primero el dispositivo existente y todo lo asociado (debe haberlo confirmado el usuario).
    """
    manifest, records, blobs = read_project(data)
    strategy = dict(strategy or {})
    skip_devices = {did for did, s in strategy.items() if s == "omitir"}
    if skip_devices:
        records = {k: v for k, v in records.items()
                   if not ((k.startswith("device:") and k.split(":", 1)[1] in skip_devices)
                           or v.get("device_id") in skip_devices)}
    for did, s in strategy.items():
        if s == "reemplazar" and did in ws.devices:
            ws.delete_device(did, ws.devices[did].name)
    rep = ImportReport()
    for sha, (name, raw) in blobs.items():
        ws.put_blob(name, raw)

    # Copias independientes forzadas: id nuevo para el dispositivo y para TODOS sus registros.
    remap: dict[str, str] = {}
    prefix = {"device": "dev", "dataset": "set", "draft": "drf", "calibration": "cal", "export": "out",
              "experiment": "exp"}
    for did in [d for d, s in strategy.items() if s == "copia"]:
        for key, val in records.items():
            kind, rid = key.split(":", 1)
            if (kind == "device" and rid == did) or val.get("device_id") == did:
                remap[rid] = new_id(prefix[kind])

    def _apply_remap(val: dict) -> dict:
        val = json.loads(json.dumps(val))
        if val.get("id") in remap:
            val["id"] = remap[val["id"]]
        for k in ("device_id", "draft_id", "calibration_id", "active_calibration_id"):
            if val.get(k) in remap:
                val[k] = remap[val[k]]
        for k in ("calibration_ids", "dataset_ids"):
            if k in val:
                val[k] = [remap.get(x, x) for x in val[k]]
        return val

    order = {"device": 0, "dataset": 1, "draft": 2, "calibration": 3, "export": 4}
    for key in sorted(records, key=lambda k: order.get(k.split(":", 1)[0], 9)):
        kind, rid = key.split(":", 1)
        forced = rid in remap
        val = _apply_remap(records[key])
        if forced:
            key = f"{kind}:{val['id']}"
            if kind == "device":
                val["name"] = f"{val['name']} (copia importada)"
                rep.copied[rid] = val["id"]
            if kind == "calibration":
                val["content_sha256"] = ""                       # se vuelve a sellar con el id remapeado
                from .model import Calibration as _Cal, _from as _mk
                val["content_sha256"] = _mk(_Cal, val).seal().content_sha256
        existing = ws.record_value(key)
        if existing is not None:
            if canonical_sha256(existing) == canonical_sha256(val):
                rep.skipped_identical.append(key)
                continue
            if kind in ("dataset", "calibration", "export", "experiment"):
                rep.rejected.append(f"{key}: ya existe con contenido distinto (registro inmutable); no se importa.")
                continue
            nid = new_id(prefix[kind])                             # conflicto no resuelto explícitamente → copia
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
    for key in list(rep.added):                                 # referencias a copias creadas por conflicto
        kind, rid = key.split(":", 1)
        obj = ws._store(kind)[rid]
        for attr in ("device_id", "draft_id"):
            if getattr(obj, attr, None) in remap:
                setattr(obj, attr, remap[getattr(obj, attr)])
                if kind == "experiment":
                    obj.seal()                                   # referencia remapeada: nueva huella coherente
    replaced = [d for d, s in strategy.items() if s == "reemplazar"]
    rep.messages.append(f"Paquete v{manifest.get('app_version')} ({manifest.get('created_utc')}): "
                        f"{len(rep.added)} registro(s) añadidos, {len(rep.skipped_identical)} idénticos omitidos, "
                        f"{len(rep.copied)} dispositivo(s)/borrador(es) como copia, {len(replaced)} reemplazado(s), "
                        f"{len(rep.rejected)} rechazados.")
    return rep


def export_device(ws: Workspace, device_id: str) -> tuple[str, bytes]:
    """Paquete autosuficiente de UN dispositivo (registros, curvas, calibraciones, perfiles y originales)."""
    if device_id not in ws.devices:
        raise WorkspaceError("Dispositivo inexistente.")
    missing = [s for s in ws.device_blob_refs(device_id) if s not in ws.blobs]
    if missing:
        raise WorkspaceError(f"Faltan {len(missing)} archivo(s) original(es) en memoria; ábralos antes de exportar "
                             "(se recuperan del navegador al abrir el dispositivo).")
    data = export_project(ws, [device_id])
    import re as _re
    safe = _re.sub(r"[^\w.-]+", "_", ws.devices[device_id].name).strip("_")[:60] or "dispositivo"
    return f"{safe}__{device_id}{DEVICE_SUFFIX}", data


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
