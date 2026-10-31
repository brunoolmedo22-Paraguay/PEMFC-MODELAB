"""Reproduce la identificación OTEKON con el motor generalizado y la compara con la
ejecución original (tests/fixtures/otekon_baseline/, generada con PEM-FC@a533432).

Uso: python tools/reproduce_otekon.py [--out carpeta]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from identification.examples import load_otekon_curves, otekon_device  # noqa: E402
from identification.optimizer import preset_otekon, run_identification  # noqa: E402
from identification.profiles import build_profile  # noqa: E402
from identification.reporting import experiment_zip  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None, help="Carpeta donde guardar el ZIP del experimento.")
    args = ap.parse_args()
    curves = load_otekon_curves()
    r = run_identification(curves, preset_otekon())
    base_dir = ROOT / "tests" / "fixtures" / "otekon_baseline"
    base = json.loads((base_dir / "optimization_summary.json").read_text())
    ident = pd.read_csv(base_dir / "identified_parameters.csv").set_index("parameter")
    print(f"Estado: {r.status}  ({r.elapsed_s:.2f} s, {len(r.runs)} inicios)")
    print(f"RMSE nuevo     : {r.metrics_global['rmse_V']:.16g} V")
    print(f"RMSE original  : {base['voltage_rmse_V']:.16g} V")
    print(f"Diferencia     : {r.metrics_global['rmse_V'] - base['voltage_rmse_V']:.3e} V")
    print(f"Condición J    : {r.identifiability['condition_number']:.6g} (original {base['jacobian_condition_number_scaled']:.6g})")
    for n, v in zip(r.free_names, r.x_best):
        ref = ident.loc[n, "identified_value"]
        print(f"  {n:34s} {v: .12g}  (orig {ref: .12g}, Δrel {abs(v - ref) / abs(ref):.1e})")
    if args.out:
        dev = otekon_device()
        prof = build_profile(r, curves, dev)
        originals = {c.source_file: (ROOT / c.meta.provenance).read_bytes() for c in curves}
        args.out.mkdir(parents=True, exist_ok=True)
        path = args.out / f"pemfc_modellab_{prof['profile_id']}.zip"
        path.write_bytes(experiment_zip(prof, r, curves, dev, originals))
        print(f"ZIP: {path}")


if __name__ == "__main__":
    main()
