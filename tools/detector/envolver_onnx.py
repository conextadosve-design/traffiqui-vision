"""Adapta un ONNX ya exportado (salidas logits + pred_boxes, estilo DETR) al formato de Traffiqui.

    python tools/detector/envolver_onnx.py model.onnx models/rfdetr-n --size 384 --persona 1 [--normalizar]

Añade al grafo la normalización de entrada (opcional), la sigmoide de la clase persona y el paso de
cx, cy, w, h a x1, y1, x2, y2. Útil cuando el modelo de Hugging Face no se puede exportar desde PyTorch.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada")
    ap.add_argument("salida")
    ap.add_argument("--size", type=int, required=True)
    ap.add_argument("--persona", type=int, required=True)
    ap.add_argument("--normalizar", action="store_true")
    ap.add_argument("--nombre", default=None)
    ap.add_argument("--fuente", default="")
    a = ap.parse_args()

    m = onnx.load(a.entrada)
    g = m.graph
    old_in = g.input[0].name
    outs = {o.name for o in g.output}
    assert {"logits", "pred_boxes"} <= outs, f"Se esperaban logits y pred_boxes, hay {outs}"

    # entrada nueva: images [1, 3, S, S] en 0–1
    g.input.remove(g.input[0])
    g.input.insert(0, helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, a.size, a.size]))
    pre = []
    if a.normalizar:
        g.initializer.extend([numpy_helper.from_array(np.array(MEAN, np.float32).reshape(1, 3, 1, 1), "tq_mean"),
                              numpy_helper.from_array(np.array(STD, np.float32).reshape(1, 3, 1, 1), "tq_std")])
        pre = [helper.make_node("Sub", ["images", "tq_mean"], ["tq_centered"]),
               helper.make_node("Div", ["tq_centered", "tq_std"], [old_in])]
    else:
        pre = [helper.make_node("Identity", ["images"], [old_in])]
    for i, n in enumerate(pre):
        g.node.insert(i, n)

    # salidas: scores = sigmoid(logits[..., persona]); boxes = cxcywh -> xyxy
    g.initializer.append(numpy_helper.from_array(np.array([a.persona], np.int64), "tq_person"))
    # [cx, cy, w, h] @ M = [cx - w/2, cy - h/2, cx + w/2, cy + h/2]
    g.initializer.append(numpy_helper.from_array(np.array([[1, 0, 1, 0], [0, 1, 0, 1], [-0.5, 0, 0.5, 0],
                                                           [0, -0.5, 0, 0.5]], np.float32), "tq_m"))
    g.node.extend([
        helper.make_node("Gather", ["logits", "tq_person"], ["tq_plogit"], axis=2),
        helper.make_node("Sigmoid", ["tq_plogit"], ["tq_pscore"]),
        helper.make_node("Squeeze", ["tq_pscore", "tq_sq_axis"], ["scores"]),
        helper.make_node("MatMul", ["pred_boxes", "tq_m"], ["boxes"]),
    ])
    g.initializer.append(numpy_helper.from_array(np.array([2], np.int64), "tq_sq_axis"))
    while len(g.output):
        g.output.pop()
    g.output.extend([helper.make_tensor_value_info("boxes", TensorProto.FLOAT, None),
                     helper.make_tensor_value_info("scores", TensorProto.FLOAT, None)])
    out = Path(a.salida)
    out.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(m, str(out.with_suffix(".onnx")))
    meta = {"name": a.nombre or out.stem, "source": a.fuente, "license": "apache-2.0", "input_size": a.size,
            "person_index": a.persona, "normalize": a.normalizar}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(out.with_suffix(".onnx"))


if __name__ == "__main__":
    main()
