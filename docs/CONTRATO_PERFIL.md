# Contrato del perfil PEMFC (`profile.json`, esquema `pemfc-modellab/profile` 1.0.0)

Un perfil es autocontenido: incluye los puntos normalizados de cada curva, por lo que puede recalcularse sin los
archivos originales. Solo puede generarse desde un ajuste con al menos una curva V–I de calibración.

| Campo | Contenido |
|---|---|
| `schema`, `schema_version`, `profile_id`, `created_utc` | Identificación. `profile_id` = hash de parámetros, datos y configuración |
| `status` | `code` (NO_CONVERGIDO, AJUSTE_INSUFICIENTE, AJUSTADO_A_CURVA, VALIDADO_EXPERIMENTALMENTE), `reasons`, `usable_for_simulation`, `predictive_capability` |
| `engine` | `model_id`, `model_version`, ecuaciones, constantes numéricas, unidades, SHA-256 de `pemfc_core/model.py`, versiones de Python/NumPy/SciPy/pandas |
| `device` | Nombre, fabricante, modelo, `n_cells` y `active_area_cm2` con su origen, referencia de datasheet (solo documental) |
| `parameters[]` | `name`, `symbol`, `value`, `unit`, `origin` (MEDIDO/DATASHEET/FIJADO/IDENTIFICADO/ASUMIDO), límites, inicial, prior, `identifiability`, motivos, error estándar |
| `datasets[]` | `curve_id`, `role`, metadatos, condiciones normalizadas y tal como se introdujeron, dominio, SHA-256 original y normalizado, transformaciones, avisos, `points` (j, V_cell) |
| `fit` | Algoritmo, objetivo, configuración completa (semilla, inicios, límites, ponderación), inicios ejecutados, métricas globales, por curva y de stack |
| `diagnostics` | Valores singulares, condición, rango, dirección débil, correlación, clasificación por parámetro |
| `validation` | Estado de validación independiente, curvas, métricas, criterio, notas |
| `domain` | Rangos de j, T y P de calibración (y validados); política de extrapolación |
| `provenance` | Repositorios de origen y commits; `datasheet_used_in_objective = false` |
| `reproduction_check` | V_model guardada en cada punto y tolerancia (10⁻⁹ V) |
| `intended_use` | Alcance (Motor 1) y contrato para consumidores futuros |
| `warnings[]` | Todas las advertencias del ajuste y de los datos |

## Reimportación

`identification.profiles.load_profile` valida el esquema, rechaza modelos distintos, avisa si cambia la versión
o el hash del código del modelo, recalcula V en todos los puntos guardados y compara con `reproduction_check`.
Una alteración de cualquier parámetro se detecta como fallo de reproducción.

## Contrato para un consumidor futuro (Motor 2, no implementado)

Entradas: j [A/cm²] (o I [A] con `device.active_area_cm2`) y condiciones (`temperature_K`,
`cathode_pressure_atm`, opcionales `p_h2_atm`, `oxygen_fraction`). Salida: V_cell [V] y, si `device.n_cells`
existe, V_stack. El consumidor debe: usar solo perfiles con `usable_for_simulation = true`; marcar como
extrapolación cualquier punto fuera de `domain.calibration`; no inferir dinámica, consumo de H₂ ni BOP del perfil.
