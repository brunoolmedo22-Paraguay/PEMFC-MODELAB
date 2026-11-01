"""Gestión de dispositivos, persistencia por registros, proyectos portátiles y migración v0.2.0."""
import io
import json
import zipfile

import numpy as np
import pytest

from identification.examples import load_otekon_curves, otekon_device
from identification.optimizer import preset_generic, preset_otekon, run_identification
from identification.profiles import build_profile, load_profile, profile_to_json
from workspace.model import (
    ADM_FITTED, ADM_IN_PROGRESS, ADM_INCOMPLETE, ADM_NEW, ADM_VALIDATED, Workspace, WorkspaceError,
)
from workspace.project_io import (
    config_key, data_key, export_project, import_project, import_v020_profile, read_project,
)
from workspace.serialization import (
    curve_from_dict, curve_to_dict, fit_config_from_dict, fit_config_to_dict,
)


@pytest.fixture(scope="module")
def otekon():
    curves = load_otekon_curves()
    cfg = preset_otekon()
    res = run_identification(curves, cfg)
    prof = build_profile(res, curves, otekon_device())
    return curves, cfg, res, prof


def _ws_with_device():
    ws = Workspace()
    d = ws.create_device("Stack de prueba", "Fabricante X", "M-1")
    return ws, d


# --------------------------------------------------------------------------- dispositivos
def test_device_minimal_creation_and_stable_id():
    ws = Workspace()
    with pytest.raises(WorkspaceError, match="obligatorio"):
        ws.create_device("   ")
    d = ws.create_device("Mi PEMFC")
    assert d.id.startswith("dev-") and d.manufacturer == "" and d.n_cells is None
    old = d.id
    ws.update_device(d.id, name="Mi PEMFC renombrada", n_cells="41", active_area_cm2="232")
    assert d.id == old and d.name == "Mi PEMFC renombrada" and d.n_cells == 41 and d.active_area_cm2 == 232.0
    assert d.rev == 2


def test_device_invalid_update_rolls_back():
    ws, d = _ws_with_device()
    with pytest.raises(WorkspaceError):
        ws.update_device(d.id, active_area_cm2=-3)
    with pytest.raises(WorkspaceError):
        ws.update_device(d.id, n_cells=0, name="otro")
    assert d.active_area_cm2 is None and d.name == "Stack de prueba" and d.rev == 1
    with pytest.raises(WorkspaceError, match="no editable"):
        ws.update_device(d.id, id="hack")


# --------------------------------------------------------------------------- serialización
def test_curve_and_config_roundtrip_is_exact(otekon):
    curves, cfg, res, _ = otekon
    for c in curves:
        back = curve_from_dict(json.loads(json.dumps(curve_to_dict(c))))
        assert back.normalized_sha256 == c.normalized_sha256
        assert back.meta == c.meta and back.conditions == c.conditions and back.mapping == c.mapping
        assert list(back.raw.columns) == list(c.raw.columns)
    d = json.loads(json.dumps(fit_config_to_dict(cfg)))
    back = fit_config_from_dict(d)
    assert back.to_dict() == cfg.to_dict()
    res2 = run_identification([curve_from_dict(curve_to_dict(c)) for c in curves], back)
    assert res2.metrics_global["rmse_V"] == res.metrics_global["rmse_V"]          # reproducible bit a bit
    tampered = curve_to_dict(curves[0])
    tampered["v_cell_V"][3] += 1e-9
    with pytest.raises(ValueError, match="huella"):
        curve_from_dict(tampered)


# --------------------------------------------------------------------------- calibraciones y estados
def test_calibrations_are_immutable_and_never_overwritten(otekon):
    curves, cfg, res, prof = otekon
    ws, d = _ws_with_device()
    assert ws.admin_status(d.id) == ADM_NEW
    dr = ws.new_draft(d.id)
    ws.update_draft(dr.id, stage=2)
    assert ws.admin_status(d.id) in (ADM_NEW, ADM_INCOMPLETE)
    ws.update_draft(dr.id, curves=[curve_to_dict(c) for c in curves], stage=3)
    assert ws.admin_status(d.id) == ADM_IN_PROGRESS
    dk = data_key(curves, d.to_device_info())
    c1 = ws.record_calibration(dr.id, prof, dk, config_key(dk, cfg.to_dict()))
    c2 = ws.record_calibration(dr.id, prof, dk, config_key(dk, cfg.to_dict()))
    assert c1.id != c2.id and dr.calibration_ids == [c1.id, c2.id]
    assert c1.content_sha256 == c2.content_sha256 and c1.profile is not prof     # copia profunda
    prof["status"]["code"] = "MODIFICADO_FUERA"                                     # no afecta a lo registrado
    assert c1.status_code == "AJUSTADO_A_CURVA"
    assert ws.admin_status(d.id) == ADM_FITTED
    ws.set_active_calibration(d.id, c1.id)
    assert d.active_calibration_id == c1.id and c1.status_code == "AJUSTADO_A_CURVA"   # administrativo
    other, _ = Workspace(), None
    with pytest.raises(WorkspaceError):
        ws.set_active_calibration(d.id, "cal-inexistente")
    prof["status"]["code"] = "AJUSTADO_A_CURVA"


def test_unusable_profile_cannot_be_active_and_validated_status(otekon):
    _, _, _, prof = otekon
    ws, d = _ws_with_device()
    dr = ws.new_draft(d.id)
    bad = json.loads(json.dumps(prof))
    bad["status"].update(code="NO_CONVERGIDO", usable_for_simulation=False)
    cb = ws.record_calibration(dr.id, bad, "k", "k")
    with pytest.raises(WorkspaceError, match="no es utilizable"):
        ws.set_active_calibration(d.id, cb.id)
    val = json.loads(json.dumps(prof))
    val["status"]["code"] = "VALIDADO_EXPERIMENTALMENTE"
    ws.record_calibration(dr.id, val, "k", "k")
    assert ws.admin_status(d.id) == ADM_VALIDATED


def test_closed_draft_and_field_guards():
    ws, d = _ws_with_device()
    dr = ws.new_draft(d.id)
    with pytest.raises(WorkspaceError):
        ws.update_draft(dr.id, calibration_ids=["x"])
    dr.status = "cerrado"
    with pytest.raises(WorkspaceError, match="cerrado"):
        ws.update_draft(dr.id, stage=3)


def test_catalog_search_filter_sort():
    ws = Workspace()
    a = ws.create_device("Alpha", "Ballard", "9SSL")
    b = ws.create_device("Beta", "Horizon", "H-1000")
    ws.create_device("Gamma", "Ballard", "FCgen")
    assert [s["name"] for s in ws.list_devices(sort="nombre")] == ["Alpha", "Beta", "Gamma"]
    assert [s["name"] for s in ws.list_devices(query="ballard", sort="nombre")] == ["Alpha", "Gamma"]
    assert [s["name"] for s in ws.list_devices(query="h-1000")] == ["Beta"]
    assert [s["name"] for s in ws.list_devices(manufacturer="Horizon")] == ["Beta"]
    ws.archive_device(a.id)
    assert "Alpha" not in [s["name"] for s in ws.list_devices()]
    assert ws.summary(b.id)["admin_status"] == ADM_NEW


# --------------------------------------------------------------------------- persistencia por registros
def test_records_roundtrip_pending_and_tamper_detection(otekon):
    curves, cfg, _, prof = otekon
    ws, d = _ws_with_device()
    dr = ws.new_draft(d.id)
    ws.update_draft(dr.id, curves=[curve_to_dict(c) for c in curves])
    ws.set_draft_originals(dr.id, {"a.csv": b"j,V\n0.1,0.9\n"})
    cal = ws.record_calibration(dr.id, prof, "dk", "ck")
    ops = ws.pending()
    keys = {o["key"] for o in ops}
    assert {f"device:{d.id}", f"draft:{dr.id}", f"calibration:{cal.id}"} <= keys
    assert any(k.startswith("blob:") for k in keys)
    assert next(o for o in ops if o["key"] == f"calibration:{cal.id}")["immutable"]
    ws.mark_saved(keys)
    assert not ws.pending() and ws.base_rev[f"draft:{dr.id}"] == dr.rev
    recs = json.loads(json.dumps(ws.all_records()))
    ws2, problems = Workspace.from_records(recs)
    assert not problems and ws2.all_records() == ws.all_records()
    assert ws2.originals_bytes(ws2.drafts[dr.id].originals) == {"a.csv": b"j,V\n0.1,0.9\n"}
    bad = json.loads(json.dumps(recs))
    bad[f"calibration:{cal.id}"]["profile"]["parameters"][5]["value"] = 999.0
    sha = next(k for k in bad if k.startswith("blob:"))
    bad[sha]["data_b64"] = "QUJD"
    ws3, problems = Workspace.from_records(bad)
    assert any("alterada" in p for p in problems) and any("alterado" in p for p in problems)
    assert cal.id not in ws3.calibrations


# --------------------------------------------------------------------------- proyectos portátiles
def test_project_export_import_merge_without_overwrite(otekon):
    curves, _, _, prof = otekon
    ws, d = _ws_with_device()
    dr = ws.new_draft(d.id)
    ws.update_draft(dr.id, curves=[curve_to_dict(c) for c in curves])
    ws.set_draft_originals(dr.id, {"img.png": b"\x89PNG fake"})
    cal = ws.record_calibration(dr.id, prof, "dk", "ck")
    ws.set_active_calibration(d.id, cal.id)
    blob = export_project(ws)
    # importación en vacío: copia exacta
    fresh = Workspace()
    rep = import_project(fresh, blob)
    assert rep.ok and fresh.all_records() == ws.all_records()
    # segunda importación: todo idéntico, nada duplicado
    rep2 = import_project(fresh, blob)
    assert rep2.ok and not rep2.added and len(rep2.skipped_identical) >= 3
    # el dispositivo cambió en el destino → la importación crea una COPIA, no sobrescribe
    fresh.update_device(d.id, notes="editado localmente")
    rep3 = import_project(fresh, blob)
    assert d.id in rep3.copied
    copy_id = rep3.copied[d.id]
    assert fresh.devices[d.id].notes == "editado localmente"
    assert fresh.devices[copy_id].name.endswith("(importado)")
    copied_drafts = [x for x in fresh.drafts.values() if x.device_id == copy_id]
    assert copied_drafts and fresh.devices[copy_id].active_calibration_id == cal.id


def test_project_tamper_traversal_and_version_checks(otekon):
    ws, d = _ws_with_device()
    blob = export_project(ws)
    zin = zipfile.ZipFile(io.BytesIO(blob))
    files = {n: zin.read(n) for n in zin.namelist()}

    def rezip(mut):
        f = dict(files)
        mut(f)
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            for n, v in f.items():
                z.writestr(n, v)
        return b.getvalue()

    key = next(n for n in files if n.startswith("records/device/"))
    t = rezip(lambda f: f.__setitem__(key, f[key].replace(b"Stack de prueba", b"Stack alterado")))
    with pytest.raises(WorkspaceError, match="alterado"):
        read_project(t)
    t = rezip(lambda f: f.__setitem__("../evil.txt", b"x"))
    with pytest.raises(WorkspaceError, match="insegura"):
        read_project(t)
    man = json.loads(files["manifest.json"])
    man["schema_version"] = "9.9.9"
    t = rezip(lambda f: f.__setitem__("manifest.json", json.dumps(man).encode()))
    with pytest.raises(WorkspaceError, match="no soportada"):
        read_project(t)
    with pytest.raises(WorkspaceError, match="ZIP"):
        read_project(b"no es un zip")


# --------------------------------------------------------------------------- compatibilidad v0.2.0
def test_v020_profile_migration_preserves_profile_and_reproduces(otekon):
    _, _, _, prof = otekon
    data = profile_to_json(prof).encode("utf-8")
    ws = Workspace()
    m = import_v020_profile(ws, data, "otekon_profile.json")
    assert m.reproduction_ok and m.max_reproduction_error_V < 1e-9
    cal = ws.calibrations[m.calibration_id]
    assert cal.origin == "migrada_v020" and cal.profile == json.loads(data)          # intacto
    assert load_profile(json.dumps(cal.profile)).reproduction_ok                     # sigue siendo importable
    ds = ws.datasets[m.dataset_id]
    assert [c["normalized_sha256"] for c in ds.curves] == [d["normalized_sha256"] for d in prof["datasets"]]
    assert ws.originals_bytes(ds.originals)["otekon_profile.json"] == data
    dev = ws.devices[m.device_id]
    assert dev.n_cells == 41 and "Migrado" in dev.provenance
    m2 = import_v020_profile(ws, data, "otekon_profile.json")
    assert m2.device_id != m.device_id                                               # nunca fusiona por nombre
    m3 = import_v020_profile(ws, data, "otekon_profile.json", device_id=m.device_id)
    assert m3.device_id == m.device_id and len(ws.device_calibrations(m.device_id)) == 2
    with pytest.raises(WorkspaceError, match="no importable"):
        import_v020_profile(ws, b'{"schema": "otro"}')


def test_real_v020_profile_file_is_loadable_and_migrates():
    """Perfil exportado por la aplicación v0.2.0 (archivo real de la entrega anterior, con curva digitalizada)."""
    from pathlib import Path
    data = (Path(__file__).resolve().parent / "fixtures" / "compat" / "profile_v020.json").read_bytes()
    prof = json.loads(data)
    assert prof["engine"]["app_version"] == "0.2.0"
    loaded = load_profile(data)
    assert loaded.reproduction_ok and loaded.engine_match
    ws = Workspace()
    m = import_v020_profile(ws, data, "profile_v020.json")
    cal = ws.calibrations[m.calibration_id]
    assert m.reproduction_ok and cal.profile == prof and cal.origin == "migrada_v020"
    assert any(c["meta"]["quality"] == "digitalizado" for c in ws.datasets[m.dataset_id].curves)
    assert ws.admin_status(m.device_id) in ("PERFIL_AJUSTADO", "EN_CALIBRACION")


# --------------------------------------------------------------------------- v0.3.1: gestión de dispositivos
from workspace.project_io import analyze_package, export_device  # noqa: E402


def _device_with_history(otekon, name="Stack A"):
    curves, cfg, _, prof = otekon
    ws = Workspace()
    d = ws.create_device(name, "Fab", "M1", n_cells=41, active_area_cm2=232.0)
    dr = ws.new_draft(d.id)
    ws.update_draft(dr.id, curves=[curve_to_dict(c) for c in curves], fit_config=cfg.to_dict())
    ws.set_draft_originals(dr.id, {"fig.png": b"\x89PNG imagen de prueba"})
    ws.add_dataset(d.id, "Datos OTEKON", "ejemplo", [curve_to_dict(c) for c in curves], {"fig.png": b"\x89PNG imagen de prueba"})
    cal = ws.record_calibration(dr.id, prof, "dk", "ck")
    ws.set_active_calibration(d.id, cal.id)
    ws.record_export(cal.id, "p.json", b"{}")
    return ws, d, cal


def test_single_device_export_is_self_contained_and_reimportable(otekon):
    ws, d, cal = _device_with_history(otekon)
    other = ws.create_device("Otro dispositivo")
    name, data = export_device(ws, d.id)
    assert name.endswith(".pmldevice.zip") and d.id in name
    fresh = Workspace()
    an = analyze_package(fresh, data)
    assert [x["id"] for x in an.devices] == [d.id] and not an.conflicts       # solo el dispositivo elegido
    assert an.devices[0]["n_calibrations"] == 1 and an.devices[0]["n_datasets"] == 1 and an.devices[0]["n_drafts"] == 1
    rep = import_project(fresh, data)
    assert rep.ok and other.id not in fresh.devices
    assert {k: v for k, v in fresh.all_records().items()} == {k: ws.record_value(k) for k in fresh.all_records()}
    c2 = fresh.calibrations[cal.id]
    assert c2.profile == cal.profile and load_profile(json.dumps(c2.profile)).reproduction_ok
    assert fresh.devices[d.id].active_calibration_id == cal.id
    assert fresh.originals_bytes(fresh.drafts[next(iter(fresh.drafts))].originals) == {"fig.png": b"\x89PNG imagen de prueba"}


def test_import_conflict_strategies_copy_replace_skip(otekon):
    ws, d, cal = _device_with_history(otekon)
    _, data = export_device(ws, d.id)
    an = analyze_package(ws, data)
    assert an.conflicts and an.conflicts[0]["identical"]
    # copia independiente: ids nuevos para el dispositivo y TODOS sus registros
    rep = import_project(ws, data, {d.id: "copia"})
    assert rep.ok and d.id in rep.copied
    nid = rep.copied[d.id]
    assert ws.devices[nid].name.endswith("(copia importada)") and len(ws.devices) == 2
    cals = ws.device_calibrations(nid)
    assert len(cals) == 1 and cals[0].id != cal.id and cals[0].profile == cal.profile
    assert ws.devices[nid].active_calibration_id == cals[0].id
    ws2, problems = Workspace.from_records(json.loads(json.dumps(ws.all_records())))
    assert not problems                                              # las calibraciones copiadas se re-sellaron bien
    # reemplazo (confirmado): la versión local modificada se sustituye por la del paquete
    ws.update_device(d.id, notes="cambio local")
    rep = import_project(ws, data, {d.id: "reemplazar"})
    assert rep.ok and ws.devices[d.id].notes == "" and ws.calibrations[cal.id].content_sha256 == cal.content_sha256
    # omitir: no cambia nada
    before = ws.all_records()
    rep = import_project(ws, data, {d.id: "omitir"})
    assert ws.all_records() == before and not rep.added


def test_delete_device_is_deliberate_complete_and_persisted(otekon):
    ws, d, cal = _device_with_history(otekon)
    keep = ws.create_device("Comparte imagen")
    dr2 = ws.new_draft(keep.id)
    ws.set_draft_originals(dr2.id, {"fig.png": b"\x89PNG imagen de prueba"})   # mismo binario
    ws.mark_saved({o["key"] for o in ws.pending()})
    with pytest.raises(WorkspaceError, match="Confirmación incorrecta"):
        ws.delete_device(d.id, "stack a")
    s = ws.delete_device(d.id, "Stack A")
    assert s == {"device": "Stack A", "datasets": 1, "drafts": 1, "calibrations": 1, "exports": 1, "blobs": 0}
    assert d.id not in ws.devices and not ws.device_calibrations(d.id) and cal.id not in ws.calibrations
    assert len(ws.blobs) == 1                                          # binario compartido conservado
    ops = ws.pending()
    assert {o["key"] for o in ops if o.get("delete")} >= {f"device:{d.id}", f"calibration:{cal.id}"}
    ws.mark_saved([o["key"] for o in ops])
    assert not ws.deleted and not ws.pending()
    ws.delete_device(keep.id, "Comparte imagen")
    assert not ws.blobs and any(k.startswith("blob:") for k in ws.deleted)


def test_zip_bomb_and_oversized_packages_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", "{}")
        z.writestr("records/x.json", b"\0" * (60 * 1024 * 1024))
    with pytest.raises(WorkspaceError, match="bomba"):
        read_project(buf.getvalue())
