# Fixtures controlados

Los tres PNG fueron **generados sintéticamente** para comprobar extracción y calibración. `*_truth.csv` contiene los valores de curvas generadas matemáticamente (columnas `curve_id`, `current_density_A_cm2`, `voltage_V`). `*_manifest.json` registra píxeles verdaderos de referencias de X e Y y dimensiones. NO son datos experimentales, ni destinados a identificar parámetros reales.

**Secuencia:** abrir imagen → comprobar overlay automático → fijar/ajustar anclas en las coordenadas del manifiesto → exportar CSV digitalizado en unidades físicas → evaluar su error con `handoff/verificacion/evaluar_extraccion.py`. Dejar por escrito precisión automática, precisión tras edición y porcentaje cubierto.

El evaluador usa interpolación lineal entre los puntos digitalizados y calcula RMSE contra el truth en la intersección de los dominios X. Un RMSE bajo con cobertura estrecha NO significa buena extracción total; revisar ambos valores.
