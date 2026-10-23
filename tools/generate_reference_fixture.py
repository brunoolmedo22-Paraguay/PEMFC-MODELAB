"""Genera fixtures de equivalencia ejecutando el código ORIGINAL de PEM-FC.

Uso (auditoría; la aplicación no depende de este script):
    python tools/generate_reference_fixture.py /ruta/al/clon/PEM-FC

Escribe en tests/fixtures/:
* head_reference_curves.csv : tensiones del modelo original para parámetros
  de referencia y 6 vectores aleatorios dentro de los límites OTEKON.
* head_reference_params.json : vectores de parámetros usados + commit y hashes.
* otekon_baseline/ : copias de las salidas originales del identificador
  (si el script original fue ejecutado, se usa su salida fresca).
No modifica el clon de origen: importa sus módulos en modo lectura.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

FIT_NAMES = (
    "xi1", "xi2", "xi3", "xi4", "R_mem_ref_ohm_cm2", "R_mem_temperature_exponent",
    "concentration_a_ref_V", "concentration_a_temperature_V_K", "concentration_b_cm2_A",
)
LOWER = np.array([-1.5, 0.0, -3e-4, 0.0, 0.05, -2.0, 0.0, -5e-5, 0.1])
UPPER = np.array([-0.2, 0.005, 0.0, 1e-4, 0.50, 2.0, 0.03, 5e-5, 8.0])
CONDITIONS = ((298.15, 5.0), (373.15, 5.0), (373.15, 1.0), (333.15, 2.5), (353.15, 1.2))
J_GRID = np.concatenate([[0.0, 0.004, 0.01], np.linspace(0.02, 1.4, 70)])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(source: Path) -> None:
    source = source.resolve()
    commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    # Ejecutar sobre una copia temporal para no tocar el clon.
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "PEM-FC"
        shutil.copytree(source, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        sys.path.insert(0, str(work))
        from models.pemfc_model import PEMFCModel  # noqa: E402
        from pemfc_config import DEFAULT_PARAMS  # noqa: E402

        rng = np.random.default_rng(123)
        vectors = {"reference": {n: float(getattr(DEFAULT_PARAMS, n)) for n in FIT_NAMES}}
        for k in range(6):
            vectors[f"random_{k}"] = dict(zip(FIT_NAMES, map(float, rng.uniform(LOWER, UPPER))))

        rows = []
        for label, values in vectors.items():
            model = PEMFCModel(DEFAULT_PARAMS.copy_with(**values))
            for T, P in CONDITIONS:
                v = model.cell_voltage(J_GRID, T, P)
                for j, vv in zip(J_GRID, v):
                    rows.append({"vector": label, "T_K": T, "P_atm": P, "j_A_cm2": j, "V_cell_V": float(vv)})
        FIXTURES.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(FIXTURES / "head_reference_curves.csv", index=False, float_format="%.17g")

        # Línea base del identificador original, ejecutada ahora.
        subprocess.run([sys.executable, "calibration/identify_parameters.py", "--starts", "16"],
                       cwd=work, check=True, capture_output=True)
        base = FIXTURES / "otekon_baseline"
        base.mkdir(exist_ok=True)
        for name in ("optimization_summary.json", "identified_parameters.csv",
                     "optimization_runs.csv", "optimization_residuals.csv"):
            shutil.copy(work / "outputs" / name, base / name)

        meta = {
            "source_repository": "https://github.com/brunoolmedo22-Paraguay/PEM-FC",
            "commit": commit,
            "sha256": {p: sha256(source / p) for p in (
                "models/pemfc_model.py", "pemfc_config/parameters.py",
                "calibration/identify_parameters.py")},
            "vectors": vectors,
            "default_fixed": {"p_h2": DEFAULT_PARAMS.p_h2, "p_h2o": DEFAULT_PARAMS.p_h2o,
                              "oxygen_fraction_air": DEFAULT_PARAMS.oxygen_fraction_air,
                              "E0": DEFAULT_PARAMS.E0, "T_ref": DEFAULT_PARAMS.T_ref,
                              "current_density_floor_A_cm2": DEFAULT_PARAMS.current_density_floor_A_cm2},
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "note": "Generado ejecutando el código original en una copia temporal; "
                    "otekon_baseline/ contiene la salida fresca del identificador original.",
        }
        (FIXTURES / "head_reference_params.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Fixtures escritos en {FIXTURES} (commit {commit[:7]})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python tools/generate_reference_fixture.py /ruta/PEM-FC")
    main(Path(sys.argv[1]))
