import json
from pathlib import Path

import numpy as np

from app.config import ROOT_DIR, settings
from app.schemas import Detection


MODEL_REGISTRY = {
    "basant-yolo26s": settings.resolve(Path("models/best.pt")),
    "enos-yolo11m": settings.resolve(Path("models/enos-smoking-detection-best.pt")),
    # 本地训练的烟草(烟盒/条盒)检测模型，imgsz/iou 等推理参数从同目录 args.yaml 读取
    "tobacco-yolo11s": settings.resolve(Path("weights/best.pt")),
}


def load_train_args(weights: Path) -> dict:
    """读取权重同目录下的 args.yaml（YOLO 训练参数），提取推理相关项 imgsz/iou/conf。

    让本地训练模型按训练时的尺寸推理（如本模型 imgsz=1280），而非服务全局默认值。
    缺文件或解析失败时返回空字典，回退到 settings 默认。
    """
    args_file = weights.parent / "args.yaml"
    if not args_file.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(args_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    params: dict = {}
    if data.get("imgsz"):
        try:
            params["imgsz"] = int(data["imgsz"])
        except (TypeError, ValueError):
            pass
    if data.get("iou") is not None:
        try:
            params["iou"] = float(data["iou"])
        except (TypeError, ValueError):
            pass
    if data.get("conf") is not None:
        try:
            params["conf"] = float(data["conf"])
        except (TypeError, ValueError):
            pass
    return params


class TobaccoDetector:
    def __init__(self, weights: Path | None = None, model_id: str | None = None):
        self.class_mapping = json.loads((ROOT_DIR / "app" / "data" / "class_mapping.json").read_text(encoding="utf-8"))
        self.model_id = model_id or settings.yolo_model_id
        if self.model_id not in MODEL_REGISTRY and weights is None:
            self.model_id = settings.yolo_model_id if settings.yolo_model_id in MODEL_REGISTRY else "basant-yolo26s"
        self.weights = settings.resolve(weights or MODEL_REGISTRY.get(self.model_id, settings.yolo_weights))
        # 按权重同目录 args.yaml 调整推理参数（imgsz/iou/conf），无则回退服务默认
        self.infer_params = load_train_args(self.weights)
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
            "model_exists": self.weights.exists(),
            "model_size_mb": round(self.weights.stat().st_size / 1024 / 1024, 2) if self.weights.exists() else 0,
            "imgsz": self.infer_params.get("imgsz", settings.yolo_img_size),
            "iou": self.infer_params.get("iou", settings.yolo_iou),
            "available_models": [
                {
                    "id": mid,
                    "weights": str(path),
                    "model_exists": path.exists(),
                    "model_size_mb": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
                }
                for mid, path in MODEL_REGISTRY.items()
            ],
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
            # 本地 tobacco-yolo11s 单类别：烟盒/条盒合并类
            "cig_pack_or_carton": "cigarette_pack",
        }
        return aliases.get(name, "cigarette" if "cigarette" in name else "unknown")

    def _mock_detections(self, image: np.ndarray, timestamp: str | None) -> list[Detection]:
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

    def _result_to_detections(self, result, timestamp: str | None) -> list[Detection]:
        names = getattr(result, "names", {}) or getattr(self.model, "names", {}) or {}
        detections: list[Detection] = []
        boxes = getattr(result, "boxes", None)
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

    def predict_batch(
        self,
        images: list[np.ndarray],
        conf: float | None = None,
        timestamps: list[str | None] | None = None,
    ) -> list[list[Detection]]:
        if not images:
            return []
        timestamps = timestamps if timestamps is not None else [None] * len(images)
        if self.mock or self.model is None:
            return [self._mock_detections(img, ts) for img, ts in zip(images, timestamps)]
        if conf is None:
            conf = self.infer_params.get("conf") or settings.yolo_conf
        results = self.model.predict(
            source=list(images),
            conf=conf,
            iou=self.infer_params.get("iou", settings.yolo_iou),
            imgsz=self.infer_params.get("imgsz", settings.yolo_img_size),
            verbose=False,
        )
        return [self._result_to_detections(r, ts) for r, ts in zip(results, timestamps)]

    def predict_image(self, image: np.ndarray, conf: float | None = None, timestamp: str | None = None) -> list[Detection]:
        return self.predict_batch([image], conf=conf, timestamps=[timestamp])[0]
