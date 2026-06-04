import importlib.util
from pathlib import Path


def load_management_app():
    spec = importlib.util.spec_from_file_location("management_app", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_vision_service_status_is_ready_when_mock_service_is_reachable(monkeypatch):
    management = load_management_app()

    def fake_service_get(base_url, path, timeout=10):
        assert path == "/models/info"
        return {
            "detector": {
                "type": "yolo",
                "weights": "models/best.pt",
                "mock": True,
                "model_id": "basant-yolo26s",
                "model_exists": False,
                "model_size_mb": 0,
                "available_models": [
                    {
                        "id": "basant-yolo26s",
                        "weights": "models/best.pt",
                        "model_exists": False,
                        "model_size_mb": 0,
                    }
                ],
            },
            "ocr": {"enabled": True, "engine": "rapidocr", "mock": True},
        }

    monkeypatch.setattr(management, "service_get", fake_service_get)

    status = management.vision_service_status()

    assert status["ready"] is True
    assert status["mock"] is True
    assert status["real_model_ready"] is False
    assert status["service_mode"] == "vision-service"


def test_visual_result_to_detector_result_returns_served_evidence_path():
    management = load_management_app()

    result = management.visual_result_to_detector_result(
        {
            "visual_score": 0.5,
            "detected_objects": [
                {
                    "class_name": "cigarette_pack",
                    "confidence": 0.76,
                    "bbox": [1, 2, 3, 4],
                }
            ],
            "evidence_frames": [
                {
                    "image_path": "storage/evidence/demo/evidence_001.jpg",
                    "description": "demo",
                }
            ],
            "model_version": "vision-tobacco-v0.1.0",
        }
    )

    assert result["annotated_image"] == "/storage/evidence/demo/evidence_001.jpg"


def test_public_media_url_exposes_existing_tmp_media(tmp_path):
    management = load_management_app()
    media = tmp_path / "demo.wav"
    media.write_bytes(b"demo")

    url = management.public_media_url(str(media))

    assert url.startswith("/media/local/")
    token = url.split("/")[3]
    assert management.decode_local_media_token(token) == media
