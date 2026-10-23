"""Parámetros del modelo semiempírico PEMFC y sus metadatos de trazabilidad.

Los valores de referencia proceden de ``PEM-FC/pemfc_config/parameters.py``
(commit a533432, identificación OTEKON reproducida). Solo se incluyen los
parámetros que intervienen en la curva de polarización estacionaria; la
dinámica (tau_H, C_dl) y la eficiencia inferida (U_f) quedan fuera del Hito 1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from typing import Any

# Orígenes permitidos para un parámetro dentro de un perfil.
ORIGIN_MEASURED = "MEDIDO"
ORIGIN_DATASHEET = "DATASHEET"
ORIGIN_FIXED = "FIJADO"
ORIGIN_IDENTIFIED = "IDENTIFICADO"
ORIGIN_ASSUMED = "ASUMIDO"
ORIGINS = (ORIGIN_MEASURED, ORIGIN_DATASHEET, ORIGIN_FIXED, ORIGIN_IDENTIFIED, ORIGIN_ASSUMED)


@dataclass(frozen=True)
class ModelParameters:
    """Vista plana de los parámetros consumidos por :mod:`pemfc_core.model`."""

    # Constantes y referencia termodinámica
    E0: float = 1.229
    R: float = 8.314
    F: float = 96485.0
    T_ref: float = 298.15

    # Membrana (solo trazabilidad: se cancelan en R_mem(T), ver AUDITORIA §6.1)
    t_m: float = 0.005
    D_H: float = 0.85e-6

    # Gases (valores globales; una curva puede sobrescribir p_h2 y y_O2)
    p_h2: float = 1.0
    p_h2o: float = 0.50
    oxygen_fraction_air: float = 0.21

    # Activación efectiva (estructura Eq. 4)
    xi1: float = -0.674591776167
    xi2: float = 0.00177858729827
    xi3: float = -7.38573038384e-05
    xi4: float = 1.19623548544e-05

    # Cadena óhmica (Eq. 9-12)
    R_mem_ref_ohm_cm2: float = 0.225432192680
    R_mem_temperature_exponent: float = -0.776511316144

    # Concentración (Eq. 13 reconstruida)
    concentration_a_ref_V: float = 0.00658205964880
    concentration_a_temperature_V_K: float = 1.50924914732e-05
    concentration_b_cm2_A: float = 2.92419192535

    # Regularización numérica del logaritmo en j -> 0
    current_density_floor_A_cm2: float = 0.010

    def copy_with(self, **kwargs: Any) -> "ModelParameters":
        unknown = set(kwargs) - PARAMETER_NAMES
        if unknown:
            raise KeyError(f"Parámetros desconocidos: {', '.join(sorted(unknown))}")
        return replace(self, **{k: float(v) for k, v in kwargs.items()})

    def to_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ModelParameters":
        unknown = set(values) - PARAMETER_NAMES
        if unknown:
            raise KeyError(f"Parámetros desconocidos: {', '.join(sorted(unknown))}")
        return cls(**{k: float(v) for k, v in values.items()})


PARAMETER_NAMES = frozenset(f.name for f in fields(ModelParameters))

# Valores de referencia OTEKON (identificación reproducida de PEM-FC).
OTEKON_REFERENCE_PARAMS = ModelParameters()


@dataclass(frozen=True)
class ParameterInfo:
    name: str
    symbol: str
    unit: str
    category: str
    description: str
    fittable: bool
    reference_origin: str
    # Límites y escala del identificador OTEKON original (None si no aplica).
    otekon_lower: float | None = None
    otekon_upper: float | None = None
    otekon_scale: float | None = None
    otekon_initial: float | None = None
    # Límites amplios para dispositivos nuevos (decisión de ModelLab, documentada).
    generic_lower: float | None = None
    generic_upper: float | None = None
    # Requisito estructural de identificabilidad.
    requires: str | None = None


# Dominio de densidad de corriente de los datos con que se identificaron los valores de referencia OTEKON.
OTEKON_REFERENCE_J_MAX_A_CM2 = 1.0


PARAMETER_INFO: dict[str, ParameterInfo] = {
    "E0": ParameterInfo("E0", "E0", "V", "Termodinámica", "Potencial reversible estándar", False, "ARTIGO (Tabla 1)"),
    "R": ParameterInfo("R", "R", "J/(mol·K)", "Constante", "Constante de los gases", False, "CONSTANTE FÍSICA"),
    "F": ParameterInfo("F", "F", "C/mol", "Constante", "Constante de Faraday", False, "CONSTANTE FÍSICA"),
    "T_ref": ParameterInfo("T_ref", "T_ref", "K", "Termodinámica", "Temperatura de referencia", False, "ARTIGO (Eq. 3)"),
    "t_m": ParameterInfo("t_m", "t_m", "cm", "Membrana", "Espesor de membrana (no afecta a V–I en esta parametrización)", False, "ARTIGO (Tabla 1)"),
    "D_H": ParameterInfo("D_H", "D_H+", "cm²/s", "Membrana", "Difusividad protónica (no afecta a V–I en esta parametrización)", False, "ARTIGO (Tabla 1)"),
    "p_h2": ParameterInfo("p_h2", "p_H2", "atm", "Gases", "Presión parcial de H2 en el ánodo", False, "INFERIDO (OTEKON)"),
    "p_h2o": ParameterInfo("p_h2o", "p_H2O", "atm", "Gases", "Presión parcial de vapor de agua", False, "HIPÓTESIS (OTEKON)"),
    "oxygen_fraction_air": ParameterInfo("oxygen_fraction_air", "y_O2", "-", "Gases", "Fracción molar de O2 en el oxidante", False, "CONSTANTE FÍSICA (aire seco)"),
    "xi1": ParameterInfo("xi1", "ξ1", "V", "Activación", "Intercepto de activación", True, "IDENTIFICADO (OTEKON)",
                         -1.5, -0.2, 0.5, -0.9514, -2.0, 0.0),
    "xi2": ParameterInfo("xi2", "ξ2", "V/K", "Activación", "Dependencia térmica del intercepto", True, "IDENTIFICADO (OTEKON)",
                         0.0, 0.005, 0.002, 0.00312, -0.005, 0.01, requires="temperaturas"),
    "xi3": ParameterInfo("xi3", "ξ3", "V/K", "Activación", "Pendiente logarítmica (Tafel) por K", True, "IDENTIFICADO (OTEKON)",
                         -3e-4, 0.0, 1e-4, -0.000187, -1e-3, 0.0),
    "xi4": ParameterInfo("xi4", "ξ4", "V/K", "Activación", "Sensibilidad a la concentración de O2", True, "IDENTIFICADO (OTEKON)",
                         0.0, 1e-4, 5e-5, 7.4e-5, 0.0, 3e-4, requires="presiones"),
    "R_mem_ref_ohm_cm2": ParameterInfo("R_mem_ref_ohm_cm2", "R_mem,ref", "Ω·cm²", "Óhmica", "Resistencia de área específica a T_ref", True, "IDENTIFICADO (OTEKON)",
                                       0.05, 0.50, 0.20, 0.20, 0.005, 2.0),
    "R_mem_temperature_exponent": ParameterInfo("R_mem_temperature_exponent", "n_R", "-", "Óhmica", "Exponente térmico de R_mem", True, "IDENTIFICADO (OTEKON)",
                                                -2.0, 2.0, 1.0, 0.0, -5.0, 5.0, requires="temperaturas"),
    "concentration_a_ref_V": ParameterInfo("concentration_a_ref_V", "a_ref", "V", "Concentración", "Amplitud de concentración a T_ref", True, "IDENTIFICADO (OTEKON)",
                                           0.0, 0.03, 0.01, 7.982e-5, 0.0, 0.2),
    "concentration_a_temperature_V_K": ParameterInfo("concentration_a_temperature_V_K", "a_T", "V/K", "Concentración", "Dependencia térmica de a", True, "IDENTIFICADO (OTEKON)",
                                                     -5e-5, 5e-5, 2e-5, -1.2e-6, -1e-3, 1e-3, requires="temperaturas"),
    "concentration_b_cm2_A": ParameterInfo("concentration_b_cm2_A", "b", "cm²/A", "Concentración", "Crecimiento exponencial de concentración", True, "IDENTIFICADO (OTEKON)",
                                           0.1, 8.0, 3.0, 8.0, 0.01, 30.0),
    "current_density_floor_A_cm2": ParameterInfo("current_density_floor_A_cm2", "j_floor", "A/cm²", "Numérico", "Piso de j en el logaritmo de activación", False, "HIPÓTESIS NUMÉRICA"),
}

# Orden canónico de los parámetros ajustables (idéntico a PARAMETER_SPECS de OTEKON).
FITTABLE_PARAMETERS: tuple[str, ...] = tuple(n for n, i in PARAMETER_INFO.items() if i.fittable)

# Parámetros que se reportan en perfiles pero nunca se ajustan.
FIXED_ONLY_PARAMETERS: tuple[str, ...] = tuple(n for n, i in PARAMETER_INFO.items() if not i.fittable)

assert set(PARAMETER_INFO) == set(PARAMETER_NAMES), "Metadatos y parámetros desincronizados"
