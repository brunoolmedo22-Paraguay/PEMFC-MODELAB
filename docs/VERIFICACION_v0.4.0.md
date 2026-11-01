# Verificación de PEMFC ModelLab v0.4.0 (Motor 2 — Laboratorio Virtual)

Estados posibles:
- **OK:** ejecutado y superado.
- **PARCIAL:** superado con la salvedad indicada.
- **NO VERIFICADO:** no ejecutado.

Todas las cifras proceden de ejecuciones reales sobre el código final.

## Pruebas automatizadas: `python -m pytest -q` → **228 aprobadas**

| Archivo | Pruebas | Contenido |
|---|---:|---|
| `test_simulation.py` (nuevo) | 11 | Casos de referencia numéricos con el perfil real OTEKON exportado por v0.2.0 (41 celdas, 232 cm²) |
| `test_motor2_app.py` (nuevo) | 5 | Interfaz del Motor 2 con AppTest: inicio, 4 bancadas, persistencia, u_máx obligatorio, historial, duplicación, estudio completo |
| Resto (v0.1–v0.3.1) | 212 | Sin regresiones. Se adaptaron dos expectativas: el resumen de borrado incluye `experiments` y la página principal ya no muestra el Motor 2 provisional |

**Integridad del núcleo:**
- `pemfc_core/model.py` conserva el SHA‑256 `00b0643a…`.
- `identification/` no cambia respecto a v0.3.1.
- `tools/reproduce_otekon.py` da **Δ RMSE = 0,0 V**.

## Verificaciones numéricas (`tests/test_simulation.py`)

| Verificación | Resultado |
|---|---|
| Reproducción frente al Motor 1 | RMSE y sesgo por curva **idénticos al bit**; RMSE global = `metrics_calibration.rmse_V` |
| Faraday | ṅ(100 A) = 41·100/(2F) con error relativo ≤ 1e‑15 |
| Unidades | I = j·A; P = N·V·I; η = V/1,2532 V (PCI); SFC = M/(2F·V); NL/min ↔ mol/s; g/s ↔ mol/s |
| Capacidad | P_máx coincide con un barrido de 200 001 puntos (rel. 1e‑9); máximo interior; límite de corriente aplicado |
| Inversión P→j | P(j(3000 W)) = 3000 W (rel. 1e‑12), en la rama de menor corriente |
| Seguimiento de carga | E_dem = 930 kJ; entregada + déficit = demandada (1e‑6 W); E_entregada + E_no atendida = E_demandada (rel. 1e‑12); un evento de déficit en t = 120 s con magnitud 9000 − P_disp; H₂ = ∫N·I/(2F)dt; P = 0 implica I = 0; sin rampa documentada no hay eventos de rampa (indicador nulo) y se emite una advertencia |
| Rampa documentada | dP/dt ≤ 100 W/s; eventos de rampa y déficit por rampa; el modo ideal no tiene rampa |
| Hidrógeno | consumido ≤ u_máx·alimentado; con alimentación insuficiente, consumido = 0,8·alimentado; política de utilización exacta; η_alim = η_cons·u; utilización > 1 rechazada; máxima potencia sin u_máx rechazada |
| Optimización | máx P = capacidad; máx η sin P mínima → advertencia de trivialidad; con P mínima → P = 1000 W exacta y restricción activa; mín SFC ≡ máx η; potencia objetivo exacta en la rama inferior; objetivo imposible rechazado; frontera de Pareto con P creciente y η decreciente |
| Datos nunca inventados | sin N_celdas → error; varias condiciones sin T y P → error; condiciones no ensayadas → aviso; fuera de rango → EXTRAPOLACIÓN; perfiles con duplicados, orden, ausentes o negativos → error con filas |
| Persistencia | experimento sellado; recarga exacta; alteración detectada; viaja en `.pmldevice.zip`; se borra con el dispositivo |
| Exportaciones | 4 bancadas: ZIP con JSON, CSV, XLSX, PNG, SVG, PDF y perfil; el CSV coincide con las series; el estudio conjunto incluye las omisiones |

## Navegador real (Chromium, Playwright)

Scripts en `tools/e2e/` y resultados en `docs/resultados_v0.4.0/`.

| Prueba | Resultado |
|---|---|
| `e2e_v040_motor2_laboratorio.py` (1440×1000) | OK: migración del perfil real; laboratorio en **sesión nueva** con datos desde IndexedDB; seguimiento de carga ejecutado con indicadores y gráficos; ZIP descargado (428 KB: datos, figuras PNG y SVG, informe, perfil); PDF válido (134 KB); reproducción «consistente con el Motor 1»; 0 excepciones y 0 errores de JS |
| Historial tras recarga | OK por captura (`04_historial.png`): ambos experimentos recuperados. La tabla se dibuja en canvas, por eso la comprobación de texto del script no la ve |
| `e2e_v040_motor2_tablet.py` (1024×768, táctil) | OK: abrir y ejecutar la bancada 04 con toques; la barra muestra **v0.4.0** |
| `e2e_v031_inicio_encabezado_gestion.py` (regresión) | OK: inicio, toques en Digitalizador y Alcance, Motor 2, regreso, 7 ecuaciones, encabezado del Motor 1; exportar, eliminar, recargar e importar un dispositivo |
| `e2e_v031_tablet_primera_carga.py` (regresión) | OK: dos selecciones únicas de imagen dejan el lienzo listo en 3–3,5 s con ambos ejes reconocidos |
| Revisión visual | Detectados y corregidos: ejes de magnitudes no negativas centrados en valores negativos cuando la serie es constante, y la leyenda sobre el título del primer panel |

## No verificado o parcial

- **NO VERIFICADO en navegador:** la entrada de perfiles mediante imagen digitalizada (modo `series`) y los archivos CSV/Excel de perfil. Están cubiertos solo por código compartido y validado: `timeseries.validate` y el digitalizador.
- **PARCIAL:** la tablet se emuló con Chromium y no se probó en Safari de iPad.
- **NO VERIFICADO:** el despliegue en Streamlit Community Cloud, que requiere la cuenta del usuario. Todas las dependencias son de pip.
- **Rendimiento:** el modelo y el remuestreo admiten hasta 20 000 instantes por experimento; en la prueba de 60 s con 2000 instantes la bancada tarda 0,1 s. Experimentos muy largos generan registros grandes (varios MB) en el navegador.

## Instalación limpia

- **Instalación:** copia sin cachés y entorno nuevo (`uv venv -p 3.12`), solo con `requirements.txt` y `requirements-dev.txt`. Se instala correctamente: streamlit 1.66.1, **reportlab 4.4.10**, onnxruntime 1.24.4, openpyxl 3.1.5 y scipy 1.17.1.
- **Pruebas en ese entorno:** **228 aprobadas**; `reproduce_otekon.py` da Δ = 0,0 V.
