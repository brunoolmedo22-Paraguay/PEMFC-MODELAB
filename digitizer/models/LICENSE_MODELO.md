# Modelo de reconocimiento de texto (OCR) incluido

| Campo | Valor |
|---|---|
| Archivo | `ch_PP-OCRv4_rec_infer.onnx` (10,9 MB) |
| SHA-256 | `48fc40f24f6d2a207a2b1091d3437eb3cc3eb6b676dc3ef9c37384005483683b` (se verifica al cargar) |
| Origen del modelo | PaddleOCR PP-OCRv4, reconocimiento de texto (PaddlePaddle), licencia **Apache-2.0** |
| Conversión a ONNX | Proyecto RapidOCR (licencia Apache-2.0); archivo tomado sin modificar del paquete `rapidocr-onnxruntime==1.4.4` |
| Uso en PEMFC ModelLab | Solo el modelo de reconocimiento, ejecutado localmente con `onnxruntime` (CPU). Las cajas de texto se localizan con componentes conexos propios. Sin descargas ni servicios externos. |

Texto de la licencia Apache-2.0: https://www.apache.org/licenses/LICENSE-2.0
