# Verificación de PEMFC ModelLab v0.3.1

Todas las ejecuciones se hicieron sobre el código final.

| Verificación | Resultado |
|---|---|
| `python -m pytest -q` | **212 aprobadas** |
| OTEKON (`tools/reproduce_otekon.py`) | RMSE 0,001411370003308996 V, **Δ = 0,0** |
| Navegador: inicio, toques en Digitalizador y Alcance, Motor 2, regreso al inicio, «Modelo implementado» (7 ecuaciones renderizadas), encabezado del Motor 1 (`tools/e2e/e2e_v031_inicio_encabezado_gestion.py`) | OK |
| Navegador: exportar dispositivo (`.pmldevice.zip` con manifiesto `app_version 0.3.1`), eliminar con confirmación (botón bloqueado sin nombre), recargar (catálogo vacío), importar y recargar (dispositivo restaurado) | OK, 0 excepciones, 0 errores JS |
| Navegador, tablet táctil 1024×768: **una única** selección de imagen con el servidor recién arrancado deja el lienzo listo en 2–2,5 s, con ambos ejes reconocidos (2 ejecuciones) (`tools/e2e/e2e_v031_tablet_primera_carga.py`) | OK |
| Dependencias | Sin cambios respecto a v0.3.0 |

## Limitaciones

- **Tablet:** se emuló con Chromium y un viewport táctil, no con un iPad real con Safari. La causa corregida (borrador no atómico tras una interrupción, más la espera de la primera carga del modelo OCR) se confirmó por inspección del código y por la prueba, pero falta confirmarlo en el dispositivo físico.
- **Despliegue:** no se ejecutó en Streamlit Community Cloud porque requiere la cuenta del usuario.
