import json
from pathlib import Path

import numpy as np

from app.config import ROOT_DIR, settings
from app.schemas import Detection


MODEL_REGISTRY = {
    "basant-yolo26s": settings.resolve(Path("models/best.pt")),
    "enos-yolo11m": settings.resolve(Path("models/enos-smoking-detection-best.pt")),
}


class TobaccoDetector:
    def __init__(self, weights: Path | None = None, model_id: str | None = None):
        self.class_mapping = json.loads((ROOT_DIR / "app" / "data" / "class_mapping.json").read_text(encoding="utf-8"))
        self.model_id = model_id or settings.yolo_model_id
        self.weights = settings.resolve(weights or MODEL_REGISTRY.get(self.model_id, settings.yolo_weights))
        self.model = None
        self.mock = settings.use_mock_model or not self.weights.exists()
        if not self.mock:
            try:
                from ultralytics import YOLO

                self.model = YOLO(str(self.weights))
            except Exception as exc:
                self.mock = True
                self.load_error = str(exc)
        else:
            self.load_error = None

    def info(self) -> dict:
        return {
            "type": "yolo",
            "weights": str(self.weights),
            "mock": self.mock,
            "model_id": self.model_id,
            "classes": list(self.class_mapping.keys()),
        }

    def normalize_class(self, raw_name: str) -> str:
        name = raw_name.lower().replace(" ", "_")
        aliases = {
            "cigarette": "cigarette",
            "smoke": "cigarette",
            "smoking": "smoking_person",
            "person_smoking": "smoking_person",
            "pack": "cigarette_pack",
            "cigarette_pack": "cigarette_pack",
            "carton": "cigarette_carton",
            "cigarette_carton": "cigarette_carton",
        }
        return aliases.get(name, "cigarette" if "cigarette" in name else "unknown")

    def predict_image(self, image: np.ndarray, conf: float | None = None, timestamp: str | None = None) -> list[Detection]:
        if self.mock or self.model is None:
            h, w = image.shape[:2]
            return [
                Detection(
                    class_name="cigarette_pack",
                    label_zh=self.class_mapping["cigarette_pack"],
                    bbox=[round(w * 0.3, 2), round(h * 0.3, 2), round(w * 0.7, 2), round(h * 0.7, 2)],
                    confidence=0.76,
                    timestamp=timestamp,
                )
            ]
        results = self.model.predict(
            source=image,
            conf=conf if conf is not None else settings.yolo_conf,
            iou=settings.yolo_iou,
            imgsz=settings.yolo_img_size,
            verbose=False,
        )
        names = getattr(results[0], "names", {}) or getattr(self.model, "names", {}) or {}
        detections: list[Detection] = []
        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            return detections
        for box in boxes:
            cls_id = int(box.cls[0].item())
            raw_name = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)
            class_name = self.normalize_class(raw_name)
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            detections.append(
                Detection(
                    class_name=class_name,
                    label_zh=self.class_mapping.get(class_name, self.class_mapping["unknown"]),
                    bbox=[round(v, 2) for v in xyxy],
                    confidence=round(float(box.conf[0].item()), 4),
                    timestamp=timestamp,
                )
            )
        return detections
