from audio_service.schemas import ASRResult


class BaseASR:
    def transcribe(self, audio_path: str, duration: float = 0.0) -> ASRResult:
        raise NotImplementedError
