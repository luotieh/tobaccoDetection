import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    app_name = os.environ.get("TEXT_APP_NAME", "tobacco-text-risk-service")
    app_env = os.environ.get("TEXT_APP_ENV", "dev")
    version = "0.1.0"
    host = os.environ.get("TEXT_HOST", "0.0.0.0")
    port = env_int("TEXT_PORT", 8010)
    use_mock_model = env_bool("TEXT_USE_MOCK_MODEL", True)
    semantic_engine = os.environ.get("TEXT_SEMANTIC_ENGINE", "mock")
    model_dir = Path(os.environ.get("TEXT_MODEL_DIR", "text_models/text-risk-model"))
    llm_provider = os.environ.get("TEXT_LLM_PROVIDER", "local")
    llm_model_dir = Path(os.environ.get("TEXT_LLM_MODEL_DIR", "text_models/qwen2.5-0.5b-instruct"))
    llm_api_base_url = os.environ.get("TEXT_LLM_API_BASE_URL", "")
    llm_api_key_env = os.environ.get("TEXT_LLM_API_KEY_ENV", "TEXT_LLM_API_KEY")
    llm_api_model = os.environ.get("TEXT_LLM_API_MODEL", "")
    llm_max_new_tokens = env_int("TEXT_LLM_MAX_NEW_TOKENS", 256)
    llm_temperature = env_float("TEXT_LLM_TEMPERATURE", 0.0)
    llm_timeout_seconds = env_int("TEXT_LLM_TIMEOUT_SECONDS", 10)
    # 批量推理并发线程数（LLM 调用为 I/O 密集，可并发；过大易触发上游限流）
    batch_max_workers = env_int("TEXT_BATCH_MAX_WORKERS", 8)
    max_text_length = env_int("TEXT_MAX_TEXT_LENGTH", 512)
    enable_rules = env_bool("TEXT_ENABLE_RULES", True)
    enable_traditional_to_simplified = env_bool("TEXT_ENABLE_TRADITIONAL_TO_SIMPLIFIED", True)
    enable_masking = env_bool("TEXT_ENABLE_MASKING", True)
    risk_high = env_float("TEXT_RISK_HIGH", 0.85)
    risk_medium = env_float("TEXT_RISK_MEDIUM", 0.70)
    risk_low = env_float("TEXT_RISK_LOW", 0.50)
    result_dir = Path(os.environ.get("TEXT_RESULT_DIR", "text_storage/results"))

    @staticmethod
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else ROOT_DIR / path


settings = Settings()
