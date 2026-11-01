# Motor 2 — Laboratorio Virtual (PEMFC ModelLab v0.4.0)

## 1. Principio

El Motor 2 **no introduce ecuaciones electroquímicas**. La tensión de celda es `pemfc_core.model.cell_voltage`, evaluada con los parámetros, la geometría y las condiciones de un **perfil calibrado del Motor 1**. Solo se añaden relaciones de conservación y definiciones operacionales:

| Magnitud | Expresión | Observaciones |
|---|---|---|
| Corriente del stack | I = j · A_activa | A_activa del perfil, con su origen (MEDIDO, DATASHEET o ASUMIDO) |
| Tensión del stack | V_stack = N · V_celda(j) | Celdas en serie: todas conducen la misma I |
| Potencia eléctrica | P = N · V_celda · I | |
| Consumo faradaico de H₂ | ṅ = N · I / (2F) | F = 96 485,33212 C/mol. Teórico: sin purgas, fugas ni H₂ no reaccionado |
| Masa y volumen de H₂ | ṁ = ṅ · 2,01588 g/mol; V = ṅ · 22,414 NL/mol | NL = litro normal (0 °C, 1 atm) |
| Eficiencia (H₂ consumido) | η = P / (ṅ · PC) = V_celda / (PC / 2F) | PCI 241,83 kJ/mol → 1,2532 V; PCS 285,83 kJ/mol → 1,4811 V. Del stack, sin BoP |
| Eficiencia (H₂ alimentado) | η_alim = P / (ṅ_alim · PC) = η · u | Solo en la bancada de hidrógeno |
| Consumo específico | SFC = ṁ / P = M_H₂ / (2F · V_celda) | Minimizar SFC equivale a maximizar η |
| Utilización | u = ṅ_consumido / ṅ_alimentado ≤ u_máx ≤ 1 | |

**El perfil es la única fuente de verdad.** Si faltan N_celdas o A_activa, el Motor 2 no se ejecuta y explica por qué. Si el perfil no es utilizable para simulación, ocurre lo mismo.

## 2. Dominio admisible y extrapolación

- **Densidad de corriente.** Por defecto, el dominio calibrado del perfil (`domain.calibration.j_A_cm2`). Superar el máximo solo es posible con la casilla «Permitir extrapolación», que marca el experimento como `EXTRAPOLADO`.
- **Condiciones de operación.** Se elige una condición calibrada o se introducen otras:
  - dentro del rango calibrado, se avisa de que esas condiciones no se ensayaron (interpolación del modelo);
  - fuera del rango, se marca **EXTRAPOLACIÓN**.
- **Límites documentados (opcionales):** corriente máxima, potencia máxima, tensión mínima de celda, rampas de subida y bajada, y su procedencia. **Vacío significa «no evaluado», no «ilimitado».**
- **Baja carga.** Por debajo del mínimo calibrado (0 < j < j_mín) se evalúa por extrapolación y se registra como evento. P = 0 significa stack sin carga (j = 0): no hay consumo y la eficiencia no se define.

## 3. Bancadas

**01 Reproducción experimental**
- Evalúa el perfil en los mismos puntos normalizados de sus curvas. Las métricas son RMSE, MAE, sesgo (media de V_modelo − V_exp) y error máximo, y deben coincidir **exactamente** con las del Motor 1, lo que se comprueba.
- Muestra V–I y P–I (esta, si hay geometría), los residuos y la tabla experimental frente a calculado.
- El tipo de evaluación depende del rol de las curvas:
  - **«calibración»:** REPRODUCCIÓN DE CALIBRACIÓN, que no demuestra capacidad predictiva;
  - **«validación»:** VALIDACIÓN INDEPENDIENTE.

**02 Seguimiento de carga**
- **Entrada.** Un perfil P(t) obtenido de:
  - generadores: constante, escalón, rampa, secuencia o ciclo seno, cuadrado o triangular;
  - una tabla;
  - un CSV o Excel;
  - una imagen digitalizada.
- **Validación del perfil.** Comprueba duplicados, orden temporal, valores ausentes, valores negativos e intervalos irregulares.
- **Evaluación.** Se hace en una rejilla uniforme con interpolación lineal o escalonada, declarada, y las integrales se calculan por trapecio.
- **Cálculo por instante:** potencia disponible, entregada = mín(demanda, disponible), restringida por rampa si existe; déficit; margen; y la **menor** corriente que entrega esa potencia (rama de mayor eficiencia).
- **Modos.** El **ideal** usa solo la capacidad del modelo. El **restringido** añade los límites documentados.
- **Eventos:** déficit (instante, duración, magnitud, energía no servida y causa: capacidad, rampa o límite), restricción de rampa y baja carga fuera del dominio.
- **Indicadores:** energía demandada, entregada y no atendida; satisfacción por energía y por tiempo; potencias máximas; H₂ total; eficiencia ponderada por energía y temporal; tiempo limitado; número de eventos.

**03 Alimentación de hidrógeno**
- **Entrada.** Un caudal ṅ_alim(t) en NL/min, mol/s, g/s, g/min o kg/h, más una **política** que cierra el problema: corriente objetivo, potencia objetivo, utilización objetivo, o máxima potencia factible (que exige u_máx).
- **Cálculo.** I = mín(I_política, I_combustible = u_máx · 2F · ṅ_alim / N, I_admisible). Sin u_máx solo se aplica la cota estequiométrica u ≤ 1, y se avisa.
- **Resultados:** alimentado frente a consumido (instantáneo y acumulado), utilización, H₂ no consumido, P, I, V, energía, η respecto al consumido y al alimentado, y eventos de operación limitada por combustible o por corriente.

**04 Optimización operacional**
- **Búsqueda.** Un barrido de 4001 puntos sobre el dominio admisible con refinamiento local. Las restricciones posibles son: potencia mínima útil, potencia máxima, corriente máxima, tensión mínima y caudal máximo de H₂ con u_máx.
- **Objetivos:**
  - máxima potencia, interior o en el borde del dominio, lo que se declara;
  - máxima eficiencia;
  - mínimo consumo específico, declarado **equivalente** a máxima eficiencia;
  - potencia objetivo, eligiendo la rama de menor corriente;
  - frontera de Pareto potencia–eficiencia, con un punto de referencia que no es un óptimo único.
- **Sin potencia mínima útil**, el óptimo de eficiencia es trivial (la mínima corriente) y se advierte.

## 4. Experimentos, estudio y persistencia

- **Cada ejecución es un experimento inmutable.** Queda sellado con SHA‑256 y contiene: nombre, dispositivo, calibración, perfil, bancada, fecha, entradas (con la configuración exacta), hipótesis, parámetros, resultados, indicadores, advertencias, eventos y validez (`VALIDO`, `VALIDO_CON_ADVERTENCIAS` o `EXTRAPOLADO`). Si se altera, se detecta al cargarlo.
- **Historial.** Permite consultar, **duplicar la configuración** (se crea un experimento nuevo y el original no cambia) y comparar experimentos de la misma bancada.
- **Estudio completo.** Ejecuta las bancadas seleccionadas con su configuración. Las que no tienen datos suficientes **se omiten con su motivo**.
- **Persistencia en el navegador (IndexedDB).** Los experimentos viajan en el paquete `.pmldevice.zip` del dispositivo y se eliminan con él. **En Streamlit Cloud el servidor no conserva datos:** para conservarlos fuera del navegador, exporte los experimentos (ZIP) o el dispositivo.

## 5. Exportación

| Archivo | Contenido |
|---|---|
| `experimento.json` | Registro completo; permite reconstruir los gráficos |
| `datos.csv` | Series temporales o tablas, con 17 cifras significativas |
| `datos.xlsx` | Indicadores con definición, datos, eventos, tablas, hipótesis y advertencias, trazabilidad |
| `figuras/*.png`, `figuras/*.svg` | Gráficos (matplotlib) |
| `informe.pdf` | Informe técnico con 11 apartados: identificación, objetivo, entradas, modelo, hipótesis y limitaciones, gráficos, indicadores, eventos y advertencias, interpretación, conclusiones prudentes y trazabilidad |
| `perfil.json` | Perfil calibrado usado |

Hay además un ZIP conjunto para varios experimentos y otro para el estudio completo, con un resumen integrado en CSV y XLSX.

## 6. Limitaciones

- **Cuasiestacionario:** no hay doble capa, dinámica de gases ni de presión, térmica, ni gestión de agua o hidratación.
- **No modelado:** degradación, auxiliares (compresor, humidificador, refrigeración), electrónica de potencia y balance de planta.
- **Ánodo:** el caudal de H₂ solo limita la corriente por conservación de masa. No se modelan presión, estequiometría, recirculación ni purgas.
- **Eficiencias:** son del stack, referidas al poder calorífico elegido.
- **Capacidad de un dispositivo «perfil ajustado»:** es la del modelo ajustado, no una medición; su capacidad predictiva no está demostrada.
- **Bancadas 05 y 06** (sensibilidad y comparación de escenarios; mapa operacional): solo están previstas, sin ejecución.

## 7. Actualización desde v0.3.1

1. Sustituya los archivos del repositorio por los del ZIP, o despliegue el ZIP completo.
2. Instale `pip install -r requirements.txt`. Única dependencia nueva: **`reportlab==4.4.10`** (pura pip, compatible con Streamlit Cloud).
3. Los datos del navegador (dispositivos, calibraciones, borradores) se conservan: el esquema del espacio de trabajo no cambia y el tipo `experiment` es aditivo. Los paquetes de dispositivos v0.3.x se importan sin cambios.
4. **Contrato modificado:** el resumen de `Workspace.delete_device` incluye ahora la clave `experiments`. El núcleo numérico (`pemfc_core/model.py`, `identification/`) no cambia.
