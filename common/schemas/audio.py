from pydantic import BaseModel


class ASRSegment(BaseModel):
    start: float
    end: float
    text: str
    confidence: float | None = None


class ASRResult(BaseModel):
    transcript: str
    segments: list[ASRSegment]
    language: str | None = "zh"

