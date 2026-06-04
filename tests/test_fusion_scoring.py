import importlib.util
from pathlib import Path


def load_management_app():
    spec = importlib.util.spec_from_file_location("management_app_fusion", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def setup_management(tmp_path):
    management = load_management_app()
    management.DB_PATH = tmp_path / "demo.db"
    management.init_db()
    return management


def test_strong_text_signal_is_not_diluted_by_missing_modalities(tmp_path):
    management = setup_management(tmp_path)

    result = management.analyze_fusion({
        "content_id": "demo",
        "text_risk_score": 0.86,
        "image_risk_score": 0,
        "audio_risk_score": 0,
        "text_available": True,
        "image_available": False,
        "audio_available": False,
        "account_risk_score": 0.1,
    })

    assert result["risk_level"] == "高风险"
    assert result["risk_score"] == 0.86
    assert result["weighted_score"] < 0.4
    assert result["hit_modalities"] == ["文本"]
    assert result["missing_modalities"] == ["图像", "语音"]
    assert "文本交易引流" in result["violation_type"]


def test_medium_single_modality_signal_survives_low_confidence_noise(tmp_path):
    management = setup_management(tmp_path)

    result = management.analyze_fusion({
        "content_id": "demo",
        "text_risk_score": 0.71,
        "image_risk_score": 0.08,
        "audio_risk_score": 0.11,
        "text_available": True,
        "image_available": True,
        "audio_available": True,
        "account_risk_score": 0.0,
    })

    assert result["risk_level"] == "中风险"
    assert result["risk_score"] == 0.71
    assert result["weighted_score"] < 0.3
    assert result["hit_modalities"] == ["文本"]
    assert result["low_confidence_modalities"] == ["图像", "语音"]


def test_weak_multimodal_evidence_still_uses_weighted_score(tmp_path):
    management = setup_management(tmp_path)

    result = management.analyze_fusion({
        "content_id": "demo",
        "text_risk_score": 0.45,
        "image_risk_score": 0.38,
        "audio_risk_score": 0.30,
        "text_available": True,
        "image_available": True,
        "audio_available": True,
        "account_risk_score": 0.35,
    })

    assert result["risk_level"] == "低风险"
    assert result["risk_score"] == 0.45
    assert result["weighted_score"] < result["risk_score"]
    assert result["hit_modalities"] == []
