# Matriz de aceptación

| ID | Prueba | Resultado esperado |
|---|---|---|
| A01 | Cargar CSV V–I de nuevo dispositivo | UI mapea columnas, unidades y condiciones sin tocar código |
| A02 | Cargar CSV V–j | Conversión dimensional correcta |
| A03 | Datos de stack | V_stack/N y I/A coherentes |
| A04 | Ejecutar calibración | Convergencia/fracaso explícitos y métricas calculadas |
| A05 | OTEKON | Comparación con baseline histórica y tolerancias documentadas |
| A06 | Datos sintéticos | Ajuste de curva razonable y advertencia de no-identificabilidad si corresponde |
| A07 | Curva inválida | Error explicativo, no perfil válido |
| A08 | Guardar perfil JSON | Incluye origen, unidades, modelo, datos y parámetros |
| A09 | Reimportar perfil | Reproduce misma curva para misma versión |
| A10 | Exportar ZIP | Contiene datos, resultados, figuras, reporte y perfil |
| A11 | UI Streamlit | Flujo completo sin excepciones |
| A12 | Seguridad científica | Sin ajuste datasheet-only, sin declaraciones de validación no probada |
| A13 | Deploy | Instrucciones de GitHub + Streamlit Cloud comprobables |
