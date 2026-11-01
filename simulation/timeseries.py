"""Perfiles temporales (demanda de potencia o caudal de H₂): lectura, validación, generadores y remuestreo."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .stack import FLOW_UNITS, SimulationError

TIME_UNITS = {"s": 1.0, "min": 60.0, "h": 3600.0}
POWER_UNITS = {"W": 1.0, "kW": 1e3}
INTERP = ("lineal", "escalonado")
MAX_POINTS = 20000


@dataclass
class TimeSeries:
    """Serie validada en unidades SI internas: t [s] estrictamente creciente, valores finitos ≥ 0."""
    t_s: np.ndarray
    values: np.ndarray
    quantity: str                       # "potencia" (W) o "caudal_H2" (mol/s)
    unit_si: str
    source: str
    interpolation: str = "lineal"
    notes: list[str] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return float(self.t_s[-1] - self.t_s[0])

    def to_dict(self) -> dict:
        return {"t_s": self.t_s.tolist(), "values": self.values.tolist(), "quantity": self.quantity,
                "unit_si": self.unit_si, "source": self.source, "interpolation": self.interpolation,
                "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, d: dict) -> "TimeSeries":
        return cls(np.asarray(d["t_s"], float), np.asarray(d["values"], float), d["quantity"], d["unit_si"],
                   d.get("source", ""), d.get("interpolation", "lineal"), list(d.get("notes", [])))

    def resample(self, dt_s: float | None = None) -> tuple[np.ndarray, np.ndarray, float]:
        """Rejilla uniforme de evaluación. Lineal: interpolación; escalonado: retención del último valor."""
        dur = self.duration_s
        if dt_s is None:
            dt_min = float(np.min(np.diff(self.t_s)))
            dt_s = min(dt_min, dur / 2000.0) if self.interpolation == "lineal" else dt_min / 4.0
            dt_s = max(dt_s, dur / MAX_POINTS)
        if dt_s <= 0 or not math.isfinite(dt_s):
            raise SimulationError("Paso de simulación no válido.")
        n = int(math.floor(dur / dt_s + 1e-9)) + 1
        if n > MAX_POINTS + 1:
            raise SimulationError(f"El paso {dt_s:g} s genera {n} instantes (máximo {MAX_POINTS}). Aumente el paso.")
        t = self.t_s[0] + np.arange(n) * dt_s
        if t[-1] < self.t_s[-1] - 1e-9:
            t = np.append(t, self.t_s[-1])
        if self.interpolation == "lineal":
            v = np.interp(t, self.t_s, self.values)
        else:
            idx = np.searchsorted(self.t_s, t, side="right") - 1
            v = self.values[np.clip(idx, 0, len(self.values) - 1)]
        return t, v, float(dt_s)


def validate(t, v, quantity: str, t_unit: str, v_unit: str, source: str, interpolation: str = "lineal") -> TimeSeries:
    """Valida y convierte a SI. Errores → SimulationError con las filas afectadas (nunca se corrige en silencio)."""
    if t_unit not in TIME_UNITS:
        raise SimulationError(f"Unidad de tiempo no admitida: {t_unit!r}.")
    units = POWER_UNITS if quantity == "potencia" else FLOW_UNITS
    if v_unit not in units:
        raise SimulationError(f"Unidad no admitida para {quantity}: {v_unit!r}. Use {list(units)}.")
    if interpolation not in INTERP:
        raise SimulationError(f"Interpolación no admitida: {interpolation!r}.")
    t = pd.to_numeric(pd.Series(list(t)), errors="coerce").to_numpy(float)
    v = pd.to_numeric(pd.Series(list(v)), errors="coerce").to_numpy(float)
    errs = []
    if len(t) != len(v):
        errs.append("Las columnas de tiempo y valor tienen longitudes distintas.")
    if len(t) < 2:
        errs.append("Se necesitan al menos dos instantes.")
    bad = [i + 1 for i in range(min(len(t), len(v))) if not (math.isfinite(t[i]) and math.isfinite(v[i]))]
    if bad:
        errs.append(f"Valores ausentes o no numéricos en las filas {bad[:12]}{'…' if len(bad) > 12 else ''}.")
    if errs:
        raise SimulationError(" ".join(errs))
    neg = [i + 1 for i in range(len(v)) if v[i] < 0]
    if neg:
        raise SimulationError(f"Valores negativos en las filas {neg[:12]}: el Motor 2 no modela carga regenerativa "
                              "ni electrólisis.")
    d = np.diff(t)
    dup = [i + 2 for i in range(len(d)) if d[i] == 0]
    back = [i + 2 for i in range(len(d)) if d[i] < 0]
    if dup:
        raise SimulationError(f"Tiempos duplicados en las filas {dup[:12]}. Elimine o fusione los duplicados.")
    if back:
        raise SimulationError(f"El tiempo no es creciente en las filas {back[:12]}.")
    notes = []
    if len(d) > 2 and np.max(d) > 20 * np.median(d):
        notes.append(f"Intervalos muy irregulares (máx {np.max(d):g} {t_unit}, mediana {np.median(d):g} {t_unit}): "
                     f"revise si faltan datos; se aplica interpolación {interpolation}.")
    ts = TimeSeries((t - 0.0) * TIME_UNITS[t_unit], v * units[v_unit], quantity,
                    "W" if quantity == "potencia" else "mol/s", source, interpolation, notes)
    return ts


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            return pd.read_excel(io.BytesIO(data))
        text = data.decode("utf-8-sig", errors="replace")
        sep = ";" if text.count(";") > text.count(",") else ","
        dec = "," if sep == ";" and any(c.isdigit() for c in text) and "," in text.replace(";", "") else "."
        return pd.read_csv(io.StringIO(text), sep=sep, decimal=dec)
    except Exception as exc:  # noqa: BLE001
        raise SimulationError(f"No se pudo leer {filename}: {exc}") from exc


# ---------------------------------------------------------------------- generadores
def constant(value: float, duration: float) -> tuple[list, list]:
    if duration <= 0:
        raise SimulationError("La duración debe ser positiva.")
    return [0.0, duration], [value, value]


def step(v0: float, v1: float, t_step: float, duration: float) -> tuple[list, list]:
    if not (0 < t_step < duration):
        raise SimulationError("El instante del escalón debe estar dentro de la duración.")
    return [0.0, t_step, t_step + duration * 1e-9, duration], [v0, v0, v1, v1]


def ramp(v0: float, v1: float, t0: float, t1: float, duration: float) -> tuple[list, list]:
    if not (0 <= t0 < t1 <= duration):
        raise SimulationError("Rampa: se requiere 0 ≤ t_inicio < t_fin ≤ duración.")
    t, v = [0.0], [v0]
    if t0 > 0:
        t.append(t0); v.append(v0)
    t.append(t1); v.append(v1)
    if t1 < duration:
        t.append(duration); v.append(v1)
    return t, v


def sequence(levels: list[float], durations: list[float]) -> tuple[list, list]:
    """Secuencia de niveles constantes (escalonada)."""
    if not levels or len(levels) != len(durations) or any(d <= 0 for d in durations):
        raise SimulationError("Secuencia: un nivel por duración, duraciones positivas.")
    t, v, acc = [], [], 0.0
    for lv, du in zip(levels, durations):
        t += [acc, acc + du * (1 - 1e-9)]
        v += [lv, lv]
        acc += du
    t[-1] = acc
    return t, v


def periodic(base: float, amplitude: float, period: float, duration: float, shape: str = "seno",
             points_per_period: int = 48) -> tuple[list, list]:
    if period <= 0 or duration <= 0:
        raise SimulationError("Periodo y duración deben ser positivos.")
    n = max(int(points_per_period * duration / period), 8) + 1
    t = np.linspace(0.0, duration, n)
    ph = (t / period) % 1.0
    if shape == "seno":
        v = base + amplitude * np.sin(2 * np.pi * ph)
    elif shape == "cuadrada":
        v = base + amplitude * np.where(ph < 0.5, 1.0, -1.0)
    elif shape == "triangular":
        v = base + amplitude * (4 * np.abs(ph - 0.5) - 1) * -1
    else:
        raise SimulationError(f"Forma no admitida: {shape}.")
    return t.tolist(), v.tolist()
