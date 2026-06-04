from audio_service.schemas import ASRResult
from audio_service.services.asr_base import BaseASR
from audio_service.services.asr_mock import MockASR


class ExternalASR(BaseASR):
    def __init__(self):
        self.fallback = MockASR()

    def transcribe(self, audio_path: str, duration: float = 0.0) -> ASRResult:
        return self.fallback.transcribe(audio_path, duration)
