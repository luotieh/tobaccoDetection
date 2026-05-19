from audio_service.config import settings
from audio_service.schemas import ASRResult, ASRSegment
from audio_service.services.asr_base import BaseASR
from audio_service.services.asr_mock import MockASR


class WhisperASR(BaseASR):
    def __init__(self):
        self.mock = True
        self.model = None
        try:
            import whisper

            self.model = whisper.load_model(str(settings.asr_model_dir), device=settings.asr_device)
            self.mock = False
        except Exception:
            self.fallback = MockASR()

    def transcribe(self, audio_path: str, duration: float = 0.0) -> ASRResult:
        if self.mock or self.model is None:
            return self.fallback.transcribe(audio_path, duration)
        result = self.model.transcribe(audio_path, language=settings.asr_language)
        segments = [ASRSegment(start=float(s.get("start", 0)), end=float(s.get("end", 0)), text=s.get("text", ""), confidence=None) for s in result.get("segments", [])]
        return ASRResult(transcript=result.get("text", ""), segments=segments, language=result.get("language", settings.asr_language))
