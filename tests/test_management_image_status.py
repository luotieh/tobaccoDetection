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


def test_llm_text_config_update_validates_and_persists(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    management.init_db()

    result = management.api_update_llm_text_config(
        {
            "semantic_engine": "llm",
            "use_mock_model": False,
            "transformer_model_dir": "text_models/text-risk-model",
            "llm_provider": "openai_compatible",
            "llm_model_dir": "text_models/qwen2.5-0.5b-instruct",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_key_env": "TEXT_LLM_API_KEY",
            "llm_api_key": "stored-key",
            "llm_api_model": "deepseek-chat",
            "llm_max_new_tokens": 300,
            "llm_temperature": 0.1,
            "llm_timeout_seconds": 20,
            "max_text_length": 1024,
        }
    )

    saved = result["saved"]
    assert saved["semantic_engine"] == "llm"
    assert saved["use_mock_model"] == 0
    assert saved["llm_provider"] == "openai_compatible"
    assert saved["llm_api_base_url"] == "https://api.example.com/v1"
    assert saved["llm_api_key_env"] == "TEXT_LLM_API_KEY"
    assert saved["llm_api_key_set"] is True
    assert saved["llm_api_key_masked"] == "stor...-key"
    assert "llm_api_key" not in saved
    assert saved["llm_api_model"] == "deepseek-chat"
    assert saved["llm_max_new_tokens"] == 300
    assert saved["llm_temperature"] == 0.1
    assert saved["llm_timeout_seconds"] == 20
    assert saved["max_text_length"] == 1024


def test_llm_text_config_rejects_unknown_engine(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    management.init_db()

    try:
        management.api_update_llm_text_config({"semantic_engine": "bad"})
    except ValueError as exc:
        assert "semantic_engine" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_llm_text_config_rejects_unknown_provider(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    management.init_db()

    try:
        management.api_update_llm_text_config({"semantic_engine": "llm", "llm_provider": "bad"})
    except ValueError as exc:
        assert "llm_provider" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_llm_api_health_check_reports_missing_api_key(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.delenv("TEXT_LLM_TEST_KEY", raising=False)
    management.init_db()

    result = management.api_llm_health_check(
        {
            "llm_provider": "openai_compatible",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_model": "demo-chat",
            "llm_api_key_env": "TEXT_LLM_TEST_KEY",
        }
    )

    assert result["ok"] is False
    assert result["api_key_present"] is False
    assert "API Key" in result["message"]


def test_llm_api_health_check_calls_openai_compatible_endpoint(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.setenv("TEXT_LLM_TEST_KEY", "demo-key")
    management.init_db()
    seen = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    class FakeConnection:
        def __init__(self, host, port, timeout):
            seen["host"] = host
            seen["port"] = port
            seen["timeout"] = timeout

        def request(self, method, target, body=None, headers=None):
            seen["method"] = method
            seen["target"] = target
            seen["headers"] = headers or {}

        def getresponse(self):
            return FakeResponse()

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(management.http.client, "HTTPSConnection", FakeConnection)

    result = management.api_llm_health_check(
        {
            "llm_provider": "openai_compatible",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_model": "demo-chat",
            "llm_api_key_env": "TEXT_LLM_TEST_KEY",
            "llm_timeout_seconds": 7,
        }
    )

    assert result["ok"] is True
    assert result["response_preview"] == "ok"
    assert seen["host"] == "api.example.com"
    assert seen["port"] == 443
    assert seen["timeout"] == 7
    assert seen["method"] == "POST"
    assert seen["target"] == "/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer demo-key"
    assert seen["closed"] is True


def test_llm_api_health_check_accepts_direct_key_for_one_check(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    monkeypatch.delenv("TEXT_LLM_TEST_KEY", raising=False)
    management.init_db()
    seen = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    class FakeConnection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, target, body=None, headers=None):
            seen["auth"] = (headers or {}).get("Authorization")

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(management.http.client, "HTTPSConnection", FakeConnection)

    result = management.api_llm_health_check(
        {
            "llm_provider": "openai_compatible",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_model": "demo-chat",
            "llm_api_key_env": "TEXT_LLM_TEST_KEY",
            "llm_api_key": "direct-key",
        }
    )

    assert result["ok"] is True
    assert result["api_key_source"] == "page_input"
    assert seen["auth"] == "Bearer direct-key"


def test_llm_api_health_check_uses_saved_key(tmp_path, monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "DATA_DIR", tmp_path)
    monkeypatch.setattr(management, "DB_PATH", tmp_path / "demo.db")
    management.init_db()
    management.api_update_llm_text_config(
        {
            "semantic_engine": "llm",
            "llm_provider": "openai_compatible",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_model": "demo-chat",
            "llm_api_key": "saved-key",
        }
    )
    seen = {}

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    class FakeConnection:
        def __init__(self, host, port, timeout):
            pass

        def request(self, method, target, body=None, headers=None):
            seen["auth"] = (headers or {}).get("Authorization")

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(management.http.client, "HTTPSConnection", FakeConnection)

    result = management.api_llm_health_check(
        {
            "llm_provider": "openai_compatible",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_model": "demo-chat",
        }
    )

    assert result["ok"] is True
    assert result["api_key_source"] == "saved_config"
    assert seen["auth"] == "Bearer saved-key"


def test_text_service_env_from_config_uses_saved_llm_api_key(monkeypatch):
    management = load_management_app()
    monkeypatch.setattr(management, "TEXT_SERVICE_URL", "http://127.0.0.1:8010")

    env = management.text_service_env_from_config(
        {
            "semantic_engine": "llm",
            "use_mock_model": 0,
            "transformer_model_dir": "text_models/text-risk-model",
            "llm_provider": "openai_compatible",
            "llm_model_dir": "text_models/qwen2.5-0.5b-instruct",
            "llm_api_base_url": "https://api.example.com/v1",
            "llm_api_model": "demo-chat",
            "llm_api_key": "saved-key",
            "llm_max_new_tokens": 128,
            "llm_temperature": 0.2,
            "llm_timeout_seconds": 9,
            "max_text_length": 1024,
        }
    )

    assert env["TEXT_SEMANTIC_ENGINE"] == "llm"
    assert env["TEXT_USE_MOCK_MODEL"] == "false"
    assert env["TEXT_LLM_PROVIDER"] == "openai_compatible"
    assert env["TEXT_LLM_API_BASE_URL"] == "https://api.example.com/v1"
    assert env["TEXT_LLM_API_MODEL"] == "demo-chat"
    assert env["TEXT_LLM_API_KEY"] == "saved-key"
    assert env["TEXT_PORT"] == "8010"


def test_listening_pids_on_port_parses_ss_output(monkeypatch):
    management = load_management_app()

    def fake_check_output(cmd, text=True, stderr=None):
        return 'LISTEN 0 5 0.0.0.0:8010 0.0.0.0:* users:(("python3",pid=123,fd=13))\n'

    monkeypatch.setattr(management.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(management.os, "getpid", lambda: 999)

    assert management.listening_pids_on_port(8010) == [123]
