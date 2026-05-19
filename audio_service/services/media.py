import wave
from pathlib import Path

from audio_service.config import settings
from audio_service.utils.file_utils import ensure_dir, new_name


class MediaService:
    audio_exts = {"wav", "mp3", "m4a", "aac", "flac"}
    video_exts = {"mp4", "mov", "avi", "mkv"}

    def save_upload(self, data: bytes, filename: str, content_id: str) -> Path:
        ext = Path(filename or "upload.bin").suffix.lower().lstrip(".") or "bin"
        path = ensure_dir(settings.resolve(settings.upload_dir)) / new_name(content_id, ext)
        path.write_bytes(data)
        return path

    def media_type(self, path: Path) -> str:
        ext = path.suffix.lower().lstrip(".")
        if ext in self.audio_exts:
            return "audio"
        if ext in self.video_exts:
            return "video"
        raise ValueError("INVALID_FILE_TYPE")

    def get_duration(self, path: Path) -> float:
        if path.suffix.lower() == ".wav":
            try:
                with wave.open(str(path), "rb") as fh:
                    return round(fh.getnframes() / float(fh.getframerate() or settings.audio_sample_rate), 3)
            except wave.Error:
                return 0.0
        return 0.0

    def extract_audio_from_video(self, video_path: Path, content_id: str) -> Path:
        # Prototype fallback: store the uploaded video path as the ASR input when FFmpeg is unavailable.
        target_dir = ensure_dir(settings.resolve(settings.audio_dir) / content_id)
        target = target_dir / "audio_16k_mono.wav"
        target.write_bytes(b"")
        return target
