"""Exporta un detector de Hugging Face (D-FINE, DEIMv2, RF-DETR, RT-DETRv2) al formato ONNX de Traffiqui.

    python tools/detector/exportar.py ustc-community/dfine-nano-coco models/detector-personas --size 640

Genera <salida>.onnx y <salida>.json. El grafo ya trae la normalización de la red y devuelve solo la
clase "persona" (ver app/vision/detector.py). Necesita torch y transformers: es una herramienta de
desarrollo, no se instala en las tiendas.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from transformers import AutoConfig, AutoImageProcessor, AutoModelForObjectDetection


class PersonHead(torch.nn.Module):
    def __init__(self, model, person_idx: int, mean, std, use_softmax: bool):
        super().__init__()
        self.model, self.person_idx, self.use_softmax = model, person_idx, use_softmax
        self.register_buffer("mean", torch.tensor(mean, dtype=torch.float32).view(1, 3, 1, 1) if mean else torch.zeros(1))
        self.register_buffer("std", torch.tensor(std, dtype=torch.float32).view(1, 3, 1, 1) if std else torch.ones(1))
        self.normalize = mean is not None

    def forward(self, images):
        x = (images - self.mean) / self.std if self.normalize else images
        out = self.model(pixel_values=x)
        logits, boxes = out.logits, out.pred_boxes          # [1, Q, C], [1, Q, 4] cx, cy, w, h (0–1)
        if self.use_softmax:
            scores = logits.softmax(-1)[..., self.person_idx]
        else:
            scores = logits.sigmoid()[..., self.person_idx]
        cx, cy, w, h = boxes.unbind(-1)
        xyxy = torch.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dim=-1)
        return xyxy, scores


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("salida")
    ap.add_argument("--size", type=int, default=640)
    ap.add_argument("--nombre", default=None)
    ap.add_argument("--normalizar", action="store_true", help="forzar la normalización ImageNet")
    a = ap.parse_args()

    cfg = AutoConfig.from_pretrained(a.repo)
    labels = {int(k): v for k, v in cfg.id2label.items()}
    person_idx = next(k for k, v in labels.items() if v.lower() == "person")
    proc = AutoImageProcessor.from_pretrained(a.repo)
    norm = getattr(proc, "do_normalize", False) or a.normalizar
    mean = list(proc.image_mean) if norm else None
    std = list(proc.image_std) if norm else None
    model = AutoModelForObjectDetection.from_pretrained(a.repo).eval()
    # D-FINE, DEIM, RT-DETR y RF-DETR clasifican con sigmoide (pérdida focal); DETR clásico, con softmax
    use_softmax = getattr(cfg, "use_focal_loss", True) is False
    head = PersonHead(model, person_idx, mean, std, use_softmax).eval()

    out = Path(a.salida)
    out.parent.mkdir(parents=True, exist_ok=True)
    dummy = torch.rand(1, 3, a.size, a.size)
    with torch.no_grad():
        torch.onnx.export(head, (dummy,), str(out.with_suffix(".onnx")), input_names=["images"],
                          output_names=["boxes", "scores"], opset_version=17, dynamo=False)
    lic = next((t.split(":", 1)[1] for t in getattr(model.config, "tags", []) or [] if t.startswith("license:")), None)
    meta = {"name": a.nombre or a.repo.split("/")[-1], "source": f"https://huggingface.co/{a.repo}",
            "license": lic or "apache-2.0", "input_size": a.size, "person_index": person_idx,
            "normalize": mean is not None}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"{out.with_suffix('.onnx')}  ({out.with_suffix('.onnx').stat().st_size / 1e6:.1f} MB)  persona={person_idx}")


if __name__ == "__main__":
    main()
