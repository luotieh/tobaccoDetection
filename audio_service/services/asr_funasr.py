from audio_service.config import settings
from audio_service.schemas import ASRResult, ASRSegment
from audio_service.services.asr_base import BaseASR
from audio_service.services.asr_mock import MockASR


class FunASRASR(BaseASR):
    def __init__(self):
        self.model = None
        try:
            from funasr import AutoModel

            self.model = AutoModel(
                model=settings.funasr_model,
                vad_model=settings.funasr_vad_model,
                punc_model=settings.funasr_punc_model,
            )
        except Exception as exc:
            if not settings.allow_asr_fallback:
                raise RuntimeError(f"FunASR load failed: {exc}") from exc
            self.error = str(exc)
            self.fallback = MockASR()

    def transcribe(self, audio_path: str, duration: float = 0.0) -> ASRResult:
        if self.model is None:
            return self.fallback.transcribe(audio_path, duration)
        result = self.model.generate(input=audio_path)
        item = result[0] if isinstance(result, list) and result else result
        text = item.get("text", "") if isinstance(item, dict) else ""
        segments = [ASRSegment(start=0.0, end=max(duration, 0.0), text=text, confidence=None)] if text else []
        return ASRResult(transcript=text, segments=segments, language=settings.asr_language)

