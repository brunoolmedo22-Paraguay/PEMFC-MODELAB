"""Conjuntos de ejemplo documentados. Ninguno se presenta como validación.

* OTEKON Fig. 3: 4 curvas de tensión digitalizadas (PEM-FC, commit a533432).
  σ = 3 mV es la hipótesis de digitalización del trabajo OTEKON y se declara
  SOLO para este ejemplo.
* 65 kW equivalente: 4 puntos de stack de Chen et al. (2024), 210 celdas,
  300 cm². Temperatura y presiones: hipótesis de la ETAPA 3 de
  EnergyMultimodelv1.5 (valores nominales Horizon), NO del artículo.
* Muestra del handoff: CSV ilustrativo de formato, no son datos experimentales.
* Sintético: generado con el propio modelo y ruido controlado; sirve para
  verificar el algoritmo, nunca como validación experimental.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from pemfc_core import model as core
from pemfc_core.parameters import ModelParameters, OTEKON_REFERENCE_PARAMS
from pemfc_core.schemas import (
    QUALITY_DIGITIZED, QUALITY_ILLUSTRATIVE, QUALITY_MEASURED, QUALITY_SYNTHETIC,
    ROLE_CALIBRATION, CurveMetadata, DeviceInfo,
)

from .datasets import ConditionInput, PolarizationCurve, build_curve, sha256_bytes

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
OTEKON_SOURCE = ("Altıntaş, N.; Ertan, R. OTEKON 2024, Figura 3 — digitalización de PEM-FC "
                 "(github.com/brunoolmedo22-Paraguay/PEM-FC, commit a533432, data/otekon_figure3/)")
OTEKON_CASES = (  # mismo orden que VOLTAGE_CASES del identificador original
    ("tensao_298K", "voltage_298K.csv", 298.15, 5.0),
    ("tensao_373K", "voltage_373K.csv", 373.15, 5.0),
    ("pressao_1atm", "pressure_1atm.csv", 373.15, 1.0),
    ("pressao_5atm", "pressure_5atm.csv", 373.15, 5.0),
)


def otekon_device() -> DeviceInfo:
    return DeviceInfo(name="OTEKON 2024 — referencia reconstruida", manufacturer="(artículo académico)",
                      model="Figura 3", n_cells=41, n_cells_origin="ASUMIDO", active_area_cm2=232.0,
                      active_area_origin="ASUMIDO",
                      notes="N = 41 y A = 232 cm² son inferencias del trabajo PEM-FC, no datos del artículo.")


def load_otekon_curves(device: DeviceInfo | None = None) -> list[PolarizationCurve]:
    device = device or otekon_device()
    curves = []
    for cid, fname, T, P in OTEKON_CASES:
        path = EXAMPLES / "otekon_figure3" / fname
        data = path.read_bytes()
        frame = pd.read_csv(path)
        meta = CurveMetadata(curve_id=cid, role=ROLE_CALIBRATION, source=OTEKON_SOURCE,
                             provenance=f"examples/otekon_figure3/{fname}", quality=QUALITY_DIGITIZED,
                             sigma_V=0.003, sigma_origin="Hipótesis de incertidumbre de digitalización OTEKON "
                             "(no aplicable a otros datasets).", conditions_origin="ASUMIDO",
                             notes="Condiciones según la leyenda de la Figura 3 e inferencia PEM-FC "
                                   "(panel de presión a 373,15 K).")
        curve, issues = build_curve(
            frame["current_density_A_cm2"].to_numpy(), frame["value"].to_numpy(), meta=meta,
            condition_input=ConditionInput(T, "K", P, "atm", "absoluta"), device=device,
            raw=frame, source_file=fname, source_sha256=sha256_bytes(data))
        if curve is None:
            raise RuntimeError(f"Ejemplo OTEKON inválido: {issues}")
        curves.append(curve)
    return curves


def equivalent_65kw_device() -> DeviceInfo:
    return DeviceInfo(name="Stack equivalente 65 kW (Chen et al. 2024)", manufacturer="(no Horizon)",
                      model="Stack experimental de alta potencia", n_cells=210, n_cells_origin="MEDIDO",
                      active_area_cm2=300.0, active_area_origin="MEDIDO",
                      datasheet_reference="Chen, H. et al. CIESC Journal 75(2), 637-646, 2024. "
                                          "DOI 10.11949/0438-1157.20230745 (Tablas 1 y 2).",
                      notes="NO es una curva Horizon. Condiciones de operación no informadas en la fuente.")


def load_65kw_raw() -> tuple[bytes, pd.DataFrame]:
    path = EXAMPLES / "equivalent_65kw" / "curve_raw.csv"
    return path.read_bytes(), pd.read_csv(path)


def load_65kw_curve(device: DeviceInfo | None = None) -> PolarizationCurve:
    device = device or equivalent_65kw_device()
    data, frame = load_65kw_raw()
    meta = CurveMetadata(
        curve_id="chen2024_65kW", role=ROLE_CALIBRATION,
        source="Chen et al. (2024), CIESC Journal 75(2), Tabla 2 — vía EnergyMultimodelv1.5 commit 761f032",
        provenance="examples/equivalent_65kw/curve_raw.csv", quality=QUALITY_MEASURED, conditions_origin="ASUMIDO",
        notes="T = 353,15 K y presiones 120/140 kPag son hipótesis de la ETAPA 3 (valores nominales Horizon).")
    cond = ConditionInput(353.15, "K", 120.0, "kPa", "manométrica", ambient_kPa=101.325,
                          p_h2_atm_abs=(140.0 + 101.325) / 101.325)
    curve, issues = build_curve(frame["current_A"].to_numpy(), frame["stack_voltage_V"].to_numpy(), meta=meta,
                                condition_input=cond, device=device, current_unit="A", voltage_unit="V",
                                voltage_basis="stack", raw=frame, source_file="curve_raw.csv",
                                source_sha256=sha256_bytes(data))
    if curve is None:
        raise RuntimeError(f"Ejemplo 65 kW inválido: {issues}")
    return curve


def load_handoff_sample(device: DeviceInfo | None = None) -> PolarizationCurve:
    path = EXAMPLES / "handoff" / "otekon_voltage_sample.csv"
    data = path.read_bytes()
    frame = pd.read_csv(path)
    device = device or DeviceInfo(name="Muestra ilustrativa del handoff")
    meta = CurveMetadata(curve_id="muestra_handoff", source="Paquete handoff Hito 1 (examples/)",
                         provenance="examples/handoff/otekon_voltage_sample.csv", quality=QUALITY_ILLUSTRATIVE,
                         conditions_origin="ASUMIDO", notes="Datos ilustrativos de formato, NO experimentales.")
    curve, issues = build_curve(frame["current_density_A_cm2"].to_numpy(), frame["voltage_V"].to_numpy(),
                                meta=meta, condition_input=ConditionInput(353.15, "K", 1.0, "atm"),
                                device=device, raw=frame, source_file=path.name, source_sha256=sha256_bytes(data))
    if curve is None:
        raise RuntimeError(f"Muestra inválida: {issues}")
    return curve


def synthetic_curve(
    params: ModelParameters = OTEKON_REFERENCE_PARAMS,
    temperature_K: float = 343.15,
    pressure_atm: float = 1.5,
    j: np.ndarray | None = None,
    noise_sigma_V: float = 0.002,
    seed: int = 7,
    curve_id: str = "sintetico",
    device: DeviceInfo | None = None,
    declare_sigma: bool = False,
    role: str = ROLE_CALIBRATION,
) -> PolarizationCurve:
    """Curva generada por el propio modelo + ruido gaussiano (semilla fija)."""
    j = np.linspace(0.02, 1.2, 30) if j is None else np.asarray(j, float)
    cond = core.OperatingConditions(temperature_K, pressure_atm)
    v_true = core.cell_voltage(j, params, cond)
    v = v_true + np.random.default_rng(seed).normal(0.0, noise_sigma_V, j.size)
    meta = CurveMetadata(curve_id=curve_id, role=role, source="Generado por PEMFC ModelLab (caso sintético)",
                         provenance=f"model={core.MODEL_ID} v{core.MODEL_VERSION}; ruido N(0,{noise_sigma_V} V); seed={seed}",
                         quality=QUALITY_SYNTHETIC, sigma_V=noise_sigma_V if declare_sigma else None,
                         sigma_origin="Ruido impuesto en la generación" if declare_sigma else "",
                         conditions_origin="FIJADO", notes="Caso sintético: no es validación experimental.")
    curve, issues = build_curve(j, v, meta=meta, condition_input=ConditionInput(temperature_K, "K", pressure_atm),
                                device=device or DeviceInfo(name="Dispositivo sintético"))
    if curve is None:
        raise RuntimeError(f"Sintético inválido: {issues}")
    return curve
