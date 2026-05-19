from audio_service.config import settings
from audio_service.schemas import ASRResult, ASRSegment
from audio_service.services.asr_base import BaseASR
from audio_service.services.asr_mock import MockASR


class WhisperASR(BaseASR):
    def __init__(self):
        self.mock = True
        self.model = None
        try:
            from faster_whisper import WhisperModel

            model_name = str(settings.asr_model_dir) if settings.asr_model_dir.exists() else settings.whisper_model_size
            self.model = WhisperModel(model_name, device=settings.asr_device, compute_type=settings.asr_compute_type)
            self.mock = False
        except Exception as exc:
            if not settings.allow_asr_fallback:
                raise RuntimeError(f"Whisper ASR load failed: {exc}") from exc
            self.error = str(exc)
            self.fallback = MockASR()

    def transcribe(self, audio_path: str, duration: float = 0.0) -> ASRResult:
        if self.mock or self.model is None:
            return self.fallback.transcribe(audio_path, duration)
        raw_segments, info = self.model.transcribe(audio_path, language=settings.asr_language)
        segments = [ASRSegment(start=float(item.start), end=float(item.end), text=item.text.strip(), confidence=None) for item in raw_segments]
        return ASRResult(transcript="".join(item.text for item in segments).strip(), segments=segments, language=getattr(info, "language", settings.asr_language))
