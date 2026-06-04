import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


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


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name = os.environ.get("AUDIO_APP_NAME", "tobacco-audio-risk-service")
    version = "0.1.0"
    host = os.environ.get("AUDIO_HOST", "0.0.0.0")
    port = env_int("AUDIO_PORT", 8020)
    asr_engine = os.environ.get("ASR_ENGINE", "mock")
    allow_asr_fallback = env_bool("ALLOW_ASR_FALLBACK", True)
    asr_model_dir = Path(os.environ.get("ASR_MODEL_DIR", "audio_models/whisper-small"))
    funasr_model = os.environ.get("FUNASR_MODEL", "paraformer-zh")
    funasr_vad_model = os.environ.get("FUNASR_VAD_MODEL", "fsmn-vad")
    funasr_punc_model = os.environ.get("FUNASR_PUNC_MODEL", "ct-punc")
    whisper_model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    asr_language = os.environ.get("ASR_LANGUAGE", "zh")
    asr_device = os.environ.get("ASR_DEVICE", "cpu")
    asr_compute_type = os.environ.get("ASR_COMPUTE_TYPE", "int8")
    use_mock_transcript = env_bool("USE_MOCK_TRANSCRIPT", False)
    mock_transcript = os.environ.get("MOCK_TRANSCRIPT", "")
    max_media_seconds = env_int("MAX_MEDIA_SECONDS", 300)
    max_file_size_mb = env_int("MAX_FILE_SIZE_MB", 200)
    audio_sample_rate = env_int("AUDIO_SAMPLE_RATE", 16000)
    enable_vad = env_bool("ENABLE_VAD", False)
    risk_high = env_float("AUDIO_RISK_HIGH", 0.85)
    risk_medium = env_float("AUDIO_RISK_MEDIUM", 0.70)
    risk_low = env_float("AUDIO_RISK_LOW", 0.50)
    upload_dir = Path(os.environ.get("AUDIO_UPLOAD_DIR", "audio_storage/uploads"))
    audio_dir = Path(os.environ.get("AUDIO_DIR", "audio_storage/audio"))
    evidence_dir = Path(os.environ.get("AUDIO_EVIDENCE_DIR", "audio_storage/evidence"))
    result_dir = Path(os.environ.get("AUDIO_RESULT_DIR", "audio_storage/results"))

    @staticmethod
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else ROOT_DIR / path


settings = Settings()
