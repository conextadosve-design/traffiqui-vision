# Modelos de detección de personas

| Archivo | Red | Entrada | Precisión personas* | Uso |
|---|---|---|---|---|
| `detector-personas.onnx` | D-FINE-S | 512 px | AP 0,540 | Por defecto ("preciso") |
| `detector-personas-rapido.onnx` | D-FINE-N | 512 px | AP 0,445 | PCs con muchas cámaras ("rápido") |

\* COCO val2017, 500 imágenes, solo la clase persona (`tools/detector/evaluar.py`). Como referencia, YOLO11n
(el detector anterior, AGPL-3.0) daba AP 0,457 a 480 px.

**Licencia: Apache-2.0.** Pesos originales de [ustc-community/dfine-small-coco](https://huggingface.co/ustc-community/dfine-small-coco)
y [ustc-community/dfine-nano-coco](https://huggingface.co/ustc-community/dfine-nano-coco) — D-FINE: *Redefine Regression
Task of DETRs as Fine-grained Distribution Refinement* (Peng et al., 2024). Exportados con
`python tools/detector/exportar.py <repo> models/<nombre> --size 512`; el grafo devuelve solo la clase persona.
