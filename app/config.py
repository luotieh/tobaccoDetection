import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    app_name: str = os.environ.get("APP_NAME", "tobacco-vision-risk-service")
    app_env: str = os.environ.get("APP_ENV", "dev")
    version: str = "0.1.0"
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = env_int("PORT", 8000)

    yolo_weights: Path = Path(os.environ.get("YOLO_WEIGHTS", "models/best.pt"))
    yolo_model_id: str = os.environ.get("YOLO_MODEL_ID", "basant-yolo26s")
    yolo_conf: float = env_float("YOLO_CONF", 0.35)
    yolo_iou: float = env_float("YOLO_IOU", 0.45)
    yolo_img_size: int = env_int("YOLO_IMG_SIZE", 960)
    use_mock_model: bool = env_bool("USE_MOCK_MODEL", False)

    enable_ocr: bool = env_bool("ENABLE_OCR", True)
    ocr_engine: str = os.environ.get("OCR_ENGINE", "rapidocr")

    video_sample_fps: float = env_float("VIDEO_SAMPLE_FPS", 1.0)
    max_video_seconds: int = env_int("MAX_VIDEO_SECONDS", 180)
    max_evidence_frames: int = env_int("MAX_EVIDENCE_FRAMES", 10)
    max_upload_mb: int = env_int("MAX_UPLOAD_MB", 200)

    upload_dir: Path = Path(os.environ.get("UPLOAD_DIR", "storage/uploads"))
    evidence_dir: Path = Path(os.environ.get("EVIDENCE_DIR", "storage/evidence"))
    result_dir: Path = Path(os.environ.get("RESULT_DIR", "storage/results"))

    risk_high: float = env_float("RISK_HIGH", 0.85)
    risk_medium: float = env_float("RISK_MEDIUM", 0.70)
    risk_low: float = env_float("RISK_LOW", 0.50)

    @staticmethod
    def resolve(path: Path) -> Path:
        return path if path.is_absolute() else ROOT_DIR / path


settings = Settings()
