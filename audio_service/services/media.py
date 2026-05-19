import json
import shutil
import subprocess
import wave
from pathlib import Path

from audio_service.config import settings
from audio_service.utils.file_utils import ensure_dir, new_name


class MediaService:
    audio_exts = {"wav", "mp3", "m4a", "aac", "flac"}
    video_exts = {"mp4", "mov", "avi", "mkv"}

    def save_upload(self, data: bytes, filename: str, content_id: str) -> Path:
        max_bytes = settings.max_file_size_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise ValueError("FILE_TOO_LARGE")
        ext = Path(filename or "upload.bin").suffix.lower().lstrip(".") or "bin"
        if ext not in self.audio_exts | self.video_exts:
            raise ValueError("INVALID_FILE_TYPE")
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
                    duration = round(fh.getnframes() / float(fh.getframerate() or settings.audio_sample_rate), 3)
                    if duration > settings.max_media_seconds:
                        raise ValueError("MEDIA_TOO_LONG")
                    return duration
            except wave.Error:
                return 0.0
        if shutil.which("ffprobe"):
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                duration = round(float(json.loads(proc.stdout).get("format", {}).get("duration") or 0.0), 3)
                if duration > settings.max_media_seconds:
                    raise ValueError("MEDIA_TOO_LONG")
                return duration
        return 0.0

    def extract_audio_from_video(self, video_path: Path, content_id: str) -> Path:
        target_dir = ensure_dir(settings.resolve(settings.audio_dir) / content_id)
        target = target_dir / "audio_16k_mono.wav"
        if shutil.which("ffmpeg"):
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", str(settings.audio_sample_rate), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"FFmpeg audio extraction failed: {proc.stderr[-500:]}")
        else:
            target.write_bytes(b"")
        return target
