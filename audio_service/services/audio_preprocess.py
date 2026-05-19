from pathlib import Path

from audio_service.config import settings
from audio_service.utils.file_utils import ensure_dir


class AudioPreprocessor:
    def to_16k_mono(self, media_path: Path, content_id: str) -> Path:
        target_dir = ensure_dir(settings.resolve(settings.audio_dir) / content_id)
        target = target_dir / "audio_16k_mono.wav"
        if media_path.suffix.lower() == ".wav":
            target.write_bytes(media_path.read_bytes())
        else:
            target.write_bytes(b"")
        return target
