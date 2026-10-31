# Pruebas de extremo a extremo en navegador real (Playwright)

Verifican el lienzo interactivo del digitalizador contra `streamlit run app.py`. Hacen falta un servidor en marcha
y Chromium para Playwright. No forman parte de `pytest` porque necesitan navegador.

```bash
pip install playwright && python -m playwright install chromium
streamlit run app.py --server.headless true --server.port 8501 &
python tools/e2e/e2e_flujo_oficial.py            # flujo completo + capturas oficiales 00–08
python tools/e2e/e2e_zoom_deshacer_alineacion.py # arrastre, deshacer/rehacer, alineación píxel a píxel con zoom
python tools/e2e/e2e_borrar_pan_roi.py           # borrar (modo y Supr), Ctrl+Z, exclusión por recuadro, pan, ROI
python tools/e2e/e2e_primer_evento.py key        # primer evento tras subir: sin remontaje, zoom y foco conservados
python tools/e2e/e2e_escenarios_extra.py         # imagen corrupta, sin ejes, dos curvas, figura real OTEKON
```

`PML_URL` permite apuntar a otro servidor. Las pruebas usan un gancho de solo diagnóstico, `window.__pmlDigitizer`, que expone en el navegador las coordenadas de pantalla de un punto de imagen, la vista, los puntos y el modo. No da acceso al servidor ni a otros datos.
