from audio_service.config import settings
from audio_service.schemas import ASRResult, ASRSegment
from audio_service.services.asr_base import BaseASR


class MockASR(BaseASR):
    def transcribe(self, audio_path: str, duration: float = 0.0) -> ASRResult:
        text = settings.mock_transcript
        if not text:
            return ASRResult(transcript="", segments=[], language=settings.asr_language)
        end = max(duration, 1.0)
        return ASRResult(transcript=text, segments=[ASRSegment(start=0.0, end=end, text=text, confidence=0.80)], language=settings.asr_language)
