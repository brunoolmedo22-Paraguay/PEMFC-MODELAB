# Plan de implementación — Hito 1 (Motor 1: identificación paramétrica)

## Arquitectura

```
PEMFC-ModelLab/
  app.py                       Punto de entrada Streamlit (pestañas)
  pemfc_core/                  Núcleo físico, sin Streamlit
    model.py                   Ecuaciones OTEKON reconstruidas (única implementación)
    parameters.py              Parámetros, metadatos, perfil de referencia OTEKON
    units.py                   Conversión de corriente, tensión, temperatura, presión, área
    schemas.py                 Esquema versionado del perfil y validación
  identification/              Motor de identificación, sin Streamlit
    datasets.py                Lectura CSV, mapeo, validación estricta, normalización
    optimizer.py               Multistart TRF generalizado, priors, presets
    diagnostics.py             Métricas, identificabilidad, estado del ajuste
    profiles.py                Construcción, exportación y reimportación de perfiles
    reporting.py               Figuras PNG, reporte Markdown, ZIP de experimento
    examples.py                Carga de ejemplos documentados
  ui/                          Vistas Streamlit (solo presentación y estado)
  examples/                    OTEKON Fig. 3, 65 kW, CSV ilustrativo del handoff
  tests/                       pytest (núcleo, datos, ajuste, perfiles, UI)
  tools/                       Scripts de auditoría (generación de fixtures)
```

## Decisiones

1. **Un solo núcleo.** Gráficos, optimización, exportación y reimportación llaman `pemfc_core.model`.
2. **Condiciones explícitas por curva:** T [K], presión absoluta de cátodo/aire [atm]; opcionales p_H2 y fracción de O2.
3. **Unidades internas:** j [A/cm²], V por celda [V]. Corriente total y tensión de stack exigen A_active y N_cells; si faltan, error.
4. **Parámetros ajustables (lista blanca):** ξ1–ξ4, R_mem,ref, n_R, a_ref, a_T, b. t_m, D_H, E0 nunca libres (§6 de la auditoría).
5. **Reglas estructurales previas al ajuste:** ξ2, n_R, a_T exigen ≥ 2 temperaturas; ξ4 exige ≥ 2 presiones parciales de O2; puntos > parámetros libres. Si no se cumplen, el ajuste se bloquea salvo que el parámetro tenga prior explícito.
6. **Priors** solo si todas las curvas de calibración declaran σ_V (para que el peso dato/prior tenga sentido).
7. **Preset OTEKON**: mismas especificaciones, semilla 20260720, 16 inicios, σ = 3 mV declarado solo para ese ejemplo.
8. **Inicio informado por datos** (proyección lineal en los parámetros que entran linealmente), opcional; desactivado en el preset OTEKON para conservar los inicios originales.
9. **Estados:** `NO_CONVERGIDO`, `AJUSTE_INSUFICIENTE`, `AJUSTADO_A_CURVA`, `VALIDADO_EXPERIMENTALMENTE`. Este último solo con curvas de rol “validación”, no usadas en el ajuste, con hash distinto y criterio cumplido.
10. **Imagen/digitalización:** no implementada en este hito; deshabilitada y documentada.
11. **Sin persistencia en servidor:** el usuario descarga el perfil/ZIP y lo vuelve a cargar.

## Verificación prevista

* Equivalencia del modelo con el código original (tabla generada por `tools/generate_reference_fixture.py`).
* Reproducción OTEKON: |ΔRMSE| ≤ 1 µV frente a la ejecución original; curvas ≤ 10 µV.
* Sintético con ruido controlado: RMSE ≈ σ, advertencias de no identificabilidad.
* Stack 65 kW: conversión I/A y V/N.
* Datos inválidos: errores accionables, ningún perfil.
* Ida y vuelta del perfil: reproducción ≤ 1e-9 V.
* AppTest de Streamlit: flujo completo sin excepciones.
