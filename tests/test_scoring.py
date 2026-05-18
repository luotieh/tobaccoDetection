from app.schemas import BrandResult, Detection, OCRText
from app.services.scoring import infer_scene_tags, score_visual


def det(name: str) -> Detection:
    return Detection(class_name=name, label_zh=name, bbox=[0, 0, 100, 100], confidence=0.9)


def test_single_pack_low_or_medium():
    detections = [det("cigarette_pack")]
    scene = infer_scene_tags(detections, [])
    score, level = score_visual(detections, [], [], scene)
    assert score > 0
    assert level in {"none", "low", "medium"}


def test_bulk_trade_high():
    detections = [det("cigarette_carton"), det("cigarette_carton"), det("cigarette_carton")]
    ocr = [OCRText(text="中华 现货 私聊 微信", confidence=0.95)]
    scene = infer_scene_tags(detections, ocr)
    score, level = score_visual(detections, [BrandResult(brand="中华", confidence=0.95)], ocr, scene, frequency_score=0.8)
    assert score >= 0.85
    assert level == "high"


def test_whitelist_reduces_risk():
    detections = [det("cigarette_pack")]
    ocr = [OCRText(text="禁烟宣传 危害", confidence=0.9)]
    scene = infer_scene_tags(detections, ocr)
    score, _ = score_visual(detections, [], ocr, scene)
    assert score < 0.5


def test_no_object_none():
    score, level = score_visual([], [], [], ["unknown_scene"])
    assert score < 0.5
    assert level == "none"
