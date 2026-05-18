import json

from app.config import ROOT_DIR, settings
from app.schemas import BrandResult, Detection, OCRText


TOBACCO_CLASSES = {"cigarette_pack", "cigarette_carton", "cigarette", "smoking_person"}


def load_risk_keywords() -> dict:
    return json.loads((ROOT_DIR / "app" / "data" / "risk_keywords.json").read_text(encoding="utf-8"))


def infer_scene_tags(detections: list[Detection], ocr_texts: list[OCRText]) -> list[str]:
    class_names = [item.class_name for item in detections]
    text = " ".join(item.text for item in ocr_texts)
    keywords = load_risk_keywords()
    tags: list[str] = []
    pack_count = sum(1 for name in class_names if name in {"cigarette_pack", "cigarette_carton"})
    has_tobacco = any(name in TOBACCO_CLASSES for name in class_names)
    if pack_count >= 3:
        tags.append("bulk_display")
    if "parcel" in class_names and has_tobacco:
        tags.append("delivery_scene")
    if "price_tag" in class_names or any(word in text for word in keywords["price"]):
        tags.append("price_display")
    if "smoking_person" in class_names or "cigarette" in class_names:
        tags.append("smoking_scene")
    if any(word in text for word in keywords["whitelist"]):
        tags.append("anti_smoking_scene")
    return tags or ["unknown_scene"]


def score_visual(
    detections: list[Detection],
    brand_results: list[BrandResult],
    ocr_texts: list[OCRText],
    scene_tags: list[str],
    frequency_score: float = 0.30,
) -> tuple[float, str]:
    names = {item.class_name for item in detections}
    if "cigarette_carton" in names:
        object_score = 0.95
    elif "cigarette_pack" in names:
        object_score = 0.85
    elif "cigarette" in names:
        object_score = 0.60
    elif "smoking_person" in names:
        object_score = 0.50
    else:
        object_score = 0.00

    brand_score = max((item.confidence for item in brand_results), default=0.0)
    pack_count = sum(1 for item in detections if item.class_name in {"cigarette_pack", "cigarette_carton"})
    if pack_count >= 2:
        scene_score = 0.85
    elif "delivery_scene" in scene_tags:
        scene_score = 0.80
    elif "price_display" in scene_tags:
        scene_score = 0.85
    elif pack_count == 1:
        scene_score = 0.40
    elif "smoking_scene" in scene_tags:
        scene_score = 0.20
    else:
        scene_score = 0.00

    keywords = load_risk_keywords()
    text = " ".join(item.text for item in ocr_texts)
    whitelist_hit = any(word in text for word in keywords["whitelist"])
    if any(word in text for word in keywords["contact"]):
        ocr_risk_score = 0.85
    elif any(word in text for word in keywords["trade"]):
        ocr_risk_score = 0.80
    elif any(word in text for word in keywords["price"]):
        ocr_risk_score = 0.65
    else:
        ocr_risk_score = 0.00

    score = (
        0.35 * object_score
        + 0.20 * brand_score
        + 0.15 * scene_score
        + 0.15 * ocr_risk_score
        + 0.10 * frequency_score
    )
    if whitelist_hit:
        score -= 0.20
    score = round(max(0.0, min(score, 1.0)), 4)
    if score >= settings.risk_high:
        return score, "high"
    if score >= settings.risk_medium:
        return score, "medium"
    if score >= settings.risk_low:
        return score, "low"
    return score, "none"
