from pydantic import BaseModel, Field
from common.schemas.text import ContactEntity


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
    normalized_word: str | None = None
    dictionary: str | None = None
    start: int | None = None
    end: int | None = None
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
    asr_engine: str = "mock"
    transcript_source: str = "empty"
    duration_seconds: float
    audio_score: float
    risk_level: str
    risk_types: list[str] = Field(default_factory=list)
    transcript: str
    segments: list[ASRSegment] = Field(default_factory=list)
    hit_keywords: list[AudioKeywordHit] = Field(default_factory=list)
    brand_entities: list[BrandEntity] = Field(default_factory=list)
    contact_entities: list[ContactEntity] = Field(default_factory=list)
    evidence_segments: list[EvidenceSegment] = Field(default_factory=list)
    explanation: str
    model_version: str = "audio-risk-v0.1.0"
