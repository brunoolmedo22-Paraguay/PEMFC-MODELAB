#!/usr/bin/env python3
"""Evaluación reproducible del digitalizador (sin interfaz).

1. Fixtures SINTÉTICOS del handoff: error de DIGITALIZACIÓN contra *_truth.csv con el
   evaluador oficial sin modificar (tools/handoff/evaluar_extraccion.py), en dos modos:
   A) automático: trazo y POSICIONES de anclas automáticas; VALORES escritos como los
      leería una persona en los rótulos de los ticks;
   B) automático + anclas corregidas: posiciones de anclas del manifiesto (aísla el error
      de extracción del trazo del error de colocación de las anclas).
2. Figura REAL publicada OTEKON Fig. 3: desacuerdo frente a la digitalización previa e
   independiente de examples/otekon_figure3/*.csv (no es un «error frente a la verdad»), y
   ajuste del Motor 1 (preset OTEKON) con las 4 curvas digitalizadas por esta herramienta:
   ese RMSE es del AJUSTE electroquímico, no de la digitalización.

Uso: python tools/evaluate_digitizer.py [--out docs/resultados_digitalizador]
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from digitizer.confirm import build_digitized_curve  # noqa: E402
from digitizer.detection import DetectionParams  # noqa: E402
from digitizer.draft import DigitizationDraft  # noqa: E402
from digitizer.imageio import load_image  # noqa: E402
from identification.datasets import ConditionInput  # noqa: E402
from pemfc_core.schemas import CurveMetadata, DeviceInfo  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "digitizer"
EVAL = ROOT / "tools" / "handoff" / "evaluar_extraccion.py"
OTEKON_IMG = ROOT / "examples" / "digitizer" / "otekon_figure3_source.png"
OTEKON_CSV = ROOT / "examples" / "otekon_figure3"


def official_eval(ref: Path, got: Path, curve: str | None) -> dict:
    cmd = [sys.executable, str(EVAL), "--referencia", str(ref), "--extraido", str(got)]
    if curve:
        cmd += ["--curva", curve]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    line = next(l for l in out.splitlines() if l.startswith("RMSE"))
    parts = dict(p.split(":") for p in line.replace(" [V]", "").split(";"))
    return {"rmse_V": float(parts["RMSE"]), "mae_V": float(parts[" MAE"]),
            "x_coverage": float(parts[" X coverage"].strip().rstrip("%")) / 100, "stdout": out.strip()}


def write_eval_csv(path: Path, curve: str, x, y) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["curve_id", "current_density_A_cm2", "voltage_V"])
        for a, b in zip(x, y):
            w.writerow([curve, repr(float(a)), repr(float(b))])


def set_values_from_ticks(d: DigitizationDraft, x_vals: tuple[float, float], y_vals: tuple[float, float]) -> None:
    """Escribe los valores que una persona lee en los rótulos de los ticks donde quedaron las anclas."""
    d.set_anchor_value("X1", x_vals[0]); d.set_anchor_value("X2", x_vals[1])
    d.set_anchor_value("Y1", y_vals[0]); d.set_anchor_value("Y2", y_vals[1])


def fixtures(out: Path) -> list[dict]:
    rows = []
    for man_path in sorted(FX.glob("*_manifest.json")):
        man = json.loads(man_path.read_text())
        name = man["image_file"]
        a = man["reference_anchors_px"]
        img = load_image((FX / name).read_bytes(), name)
        for tr in man["traces"]:
            d = DigitizationDraft.from_image(img)
            auto_sel = d.selected_candidate
            cand = next(c for c in d.detection.candidates if c.color_hex == tr["color"])
            needed_choice = cand.id != auto_sel
            d.select_candidate(cand.id)
            tx, ty = d.detection.ticks["X"], d.detection.ticks["Y"]
            # valores leídos en los rótulos: X cada 0,3 desde 0; Y cada 0,1 desde 0,4 (abajo)
            set_values_from_ticks(d, (0.0, round(0.3 * (len(tx.positions) - 1), 6)),
                                  (0.4, round(0.4 + 0.1 * (len(ty.positions) - 1), 6)))
            anchors_auto = {n: (d.anchors[n].px if n[0] == "X" else d.anchors[n].py) for n in ("X1", "X2", "Y1", "Y2")}
            ref = {"X1": a["x1"]["px"], "X2": a["x2"]["px"], "Y1": a["y1"]["py"], "Y2": a["y2"]["py"]}
            res = {}
            for mode in ("A_automatico", "B_anclas_corregidas"):
                if mode.startswith("B"):
                    for n, pos in ref.items():
                        d.set_anchor_position(n, pos)
                    set_values_from_ticks(d, (a["x1"]["value"], a["x2"]["value"]), (a["y1"]["value"], a["y2"]["value"]))
                x, y, _ = d.physical()
                p = out / f"{Path(name).stem}__{tr['id'].replace(' ', '_')}__{mode}.csv"
                write_eval_csv(p, tr["id"], x, y)
                res[mode] = official_eval(FX / man["reference_csv"], p, tr["id"])
            rows.append({"fixture": name, "curve": tr["id"], "color": tr["color"], "candidate": cand.id,
                         "user_choice_needed": needed_choice, "confidence": round(cand.confidence, 3),
                         "n_points": len(d.points), "anchor_dev_px": {n: round(anchors_auto[n] - ref[n], 3) for n in ref},
                         "results": res, "warnings": d.quality_warnings()})
    return rows


def otekon(out: Path) -> dict:
    img = load_image(OTEKON_IMG.read_bytes(), OTEKON_IMG.name)
    spec = [  # panel, color, curve_id, csv previo, T [K], P [atm], valores de anclas (X1,X2),(Y1,Y2)
        (0, "azul", "tensao_298K", "voltage_298K.csv", 298.15, 5.0, (0.0, 1.2), (0.5, 1.1)),
        (0, "rojo", "tensao_373K", "voltage_373K.csv", 373.15, 5.0, (0.0, 1.2), (0.5, 1.1)),
        (3, "azul", "pressao_1atm", "pressure_1atm.csv", 373.15, 1.0, (0.0, 1.0), (0.5, 1.1)),
        (3, "rojo", "pressao_5atm", "pressure_5atm.csv", 373.15, 5.0, (0.0, 1.0), (0.5, 1.1)),
    ]
    dev = DeviceInfo(name="OTEKON Fig. 3 (re-digitalizada con PEMFC ModelLab v0.2.0)")
    curves, comps, originals = [], [], {}
    for panel, color, cid, prev, T, P, xv, yv in spec:
        d = DigitizationDraft.from_image(img, DetectionParams(panel_index=panel))
        cand = next(c for c in d.detection.candidates if c.color_name == color and c.confidence >= 0.5)
        d.select_candidate(cand.id)
        set_values_from_ticks(d, xv, yv)
        x, y, _ = d.physical()
        mine = out / f"otekon__{cid}__digitalizado.csv"
        write_eval_csv(mine, cid, x, y)
        with open(OTEKON_CSV / prev, encoding="utf-8") as f:
            pr = list(csv.DictReader(f))
        prev_csv = out / f"otekon__{cid}__previo.csv"
        write_eval_csv(prev_csv, cid, [float(r["current_density_A_cm2"]) for r in pr], [float(r["value"]) for r in pr])
        cmp_ = official_eval(prev_csv, mine, cid)
        meta = CurveMetadata(cid, quality="digitalizado", source="Altıntaş & Ertan, OTEKON 2024, Fig. 3",
                             sigma_V=0.003, sigma_origin="Hipótesis OTEKON (igual que el ejemplo de la app)")
        r = build_digitized_curve(d, meta, ConditionInput(T, "K", P, "atm"), dev, curves, originals)
        assert r.ok, [str(i) for i in r.issues]
        curves.append(r.curve)
        originals.update(r.artifacts)
        comps.append({"curve": cid, "panel": panel + 1, "color": color, "candidate": cand.id,
                      "anchors_px": {n: round(d.anchors[n].position, 2) for n in ("X1", "X2", "Y1", "Y2")},
                      "anchor_sources": {n: d.anchors[n].source for n in ("X1", "X2", "Y1", "Y2")},
                      "n_points": len(x), "j_range": [float(x.min()), float(x.max())],
                      "disagreement_vs_previous_digitization": cmp_,
                      "resolution": d.resolution()})
    from identification.optimizer import preset_otekon, run_identification
    fit = run_identification(curves, preset_otekon())
    return {"image_sha256": img.sha256, "comparisons": comps,
            "fit_motor1_preset_otekon": {"status": fit.status, "rmse_V": fit.metrics_global["rmse_V"],
                                         "baseline_rmse_V_previous_digitization": 0.001411370003308996,
                                         "note": "RMSE del AJUSTE del modelo a los datos digitalizados; NO es error "
                                                 "de digitalización ni validación experimental."}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "resultados_digitalizador"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    fx = fixtures(out)
    ot = otekon(out)
    summary = {"fixtures": fx, "otekon_figure3": ot}
    (out / "resumen.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    print("== Fixtures sintéticos (error de DIGITALIZACIÓN frente a truth) ==")
    for r in fx:
        A, B = r["results"]["A_automatico"], r["results"]["B_anclas_corregidas"]
        print(f"{r['fixture']:<28}{r['curve']:<9} A: RMSE {1000 * A['rmse_V']:.3f} mV, cob {A['x_coverage']:.1%} | "
              f"B: RMSE {1000 * B['rmse_V']:.3f} mV, cob {B['x_coverage']:.1%} | anclas Δpx {r['anchor_dev_px']} | "
              f"elección manual de candidato: {'sí' if r['user_choice_needed'] else 'no'}")
    print("== OTEKON Fig. 3 (real): desacuerdo frente a digitalización previa ==")
    for c in ot["comparisons"]:
        m = c["disagreement_vs_previous_digitization"]
        print(f"{c['curve']:<14} panel {c['panel']} {c['color']:<5} RMSE {1000 * m['rmse_V']:.2f} mV, "
              f"MAE {1000 * m['mae_V']:.2f} mV, cobertura {m['x_coverage']:.1%}")
    f = ot["fit_motor1_preset_otekon"]
    print(f"Motor 1 (preset OTEKON) con las 4 curvas re-digitalizadas: {f['status']}, RMSE de AJUSTE "
          f"{1000 * f['rmse_V']:.3f} mV/celda (baseline con digitalización previa {1000 * f['baseline_rmse_V_previous_digitization']:.3f}).")


if __name__ == "__main__":
    main()
