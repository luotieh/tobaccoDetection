from pydantic import BaseModel, Field


class ASRSegment(BaseModel):
    start: float
    end: float
    text: str
    confidence: float | None = None


class ASRResult(BaseModel):
    transcript: str
    segments: list[ASRSegment]
    language: str | None = "zh"


class AudioKeywordHit(BaseModel):
    word: str
    category: str
    start_time: float | None = None
    end_time: float | None = None
    segment_text: str | None = None


class BrandEntity(BaseModel):
    brand: str
    text: str
    confidence: float = 0.8


class EvidenceSegment(BaseModel):
    start: float
    end: float
    audio_path: str
    text: str
    description: str


class AudioRiskResult(BaseModel):
    content_id: str
    media_type: str
    duration_seconds: float
    audio_score: float
    risk_level: str
    transcript: str
    segments: list[ASRSegment] = Field(default_factory=list)
    hit_keywords: list[AudioKeywordHit] = Field(default_factory=list)
    brand_entities: list[BrandEntity] = Field(default_factory=list)
    evidence_segments: list[EvidenceSegment] = Field(default_factory=list)
    explanation: str
    model_version: str = "audio-risk-v0.1.0"
