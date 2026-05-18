from pathlib import Path

import cv2

from app.config import settings
from app.schemas import Detection, EvidenceFrame, OCRText
from app.utils.file_utils import ensure_dir


def describe_evidence(detections: list[Detection], ocr_texts: list[OCRText], scene_tags: list[str]) -> str:
    names = {item.class_name for item in detections}
    text = " ".join(item.text for item in ocr_texts)
    has_trade = any(word in text for word in ["现货", "到货", "私聊", "私信", "可发", "包邮"])
    if {"cigarette_pack", "cigarette_carton"} & names and has_trade:
        return "画面中出现烟盒，并伴随交易引导文字"
    if "cigarette_carton" in names or "bulk_display" in scene_tags:
        return "画面中出现多条烟草包装，疑似批量展示"
    if {"cigarette", "smoking_person"} & names:
        return "画面中出现香烟或吸烟场景"
    if "anti_smoking_scene" in scene_tags:
        return "画面中存在烟草相关内容，但疑似新闻/控烟宣传语境"
    return "画面中出现疑似烟草相关目标"


def draw_detections(image, detections: list[Detection]):
    output = image.copy()
    for det in detections:
        x1, y1, x2, y2 = [int(v) for v in det.bbox]
        cv2.rectangle(output, (x1, y1), (x2, y2), (0, 80, 255), 2)
        cv2.putText(output, f"{det.class_name} {det.confidence:.2f}", (x1, max(20, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 80, 255), 2)
    return output


def save_evidence_image(
    image,
    content_id: str,
    detections: list[Detection],
    ocr_texts: list[OCRText],
    scene_tags: list[str],
    filename: str = "evidence_001.jpg",
    timestamp: str | None = None,
) -> EvidenceFrame:
    evidence_dir = ensure_dir(settings.resolve(settings.evidence_dir) / content_id)
    path = evidence_dir / filename
    cv2.imwrite(str(path), draw_detections(image, detections))
    return EvidenceFrame(
        timestamp=timestamp,
        image_path=str(path.relative_to(settings.resolve(Path(".")))),
        description=describe_evidence(detections, ocr_texts, scene_tags),
    )
