from pydantic import BaseModel, Field
from common.schemas.text import BrandEntity, ContactEntity as TextEntity, KeywordHit, SemanticResult


class EvidenceText(BaseModel):
    source: str
    text: str
    start: int
    end: int

class TextInferRequest(BaseModel):
    content_id: str
    source: str = "text"
    text: str
    # 可选上下文（如帖子标题/正文）：仅供 LLM 理解语义，不参与规则命中，避免污染评分
    context: str = ""


class ContentInferRequest(BaseModel):
    content_id: str
    platform: str | None = None
    title: str = ""
    description: str = ""
    account_name: str = ""
    account_bio: str = ""
    comments: list[str] = Field(default_factory=list)
    ocr_texts: list[str] = Field(default_factory=list)
    asr_texts: list[str] = Field(default_factory=list)
    content_url: str | None = None


class BatchInferRequest(BaseModel):
    items: list[TextInferRequest]


class TextInferResult(BaseModel):
    content_id: str
    source: str
    text_score: float
    risk_level: str
    risk_types: list[str]
    hit_keywords: list[KeywordHit] = Field(default_factory=list)
    brand_entities: list[BrandEntity] = Field(default_factory=list)
    contact_entities: list[TextEntity] = Field(default_factory=list)
    evidence_text: list[EvidenceText] = Field(default_factory=list)
    explanation: str
    model_version: str = "text-risk-v0.1.0"


class FieldResult(BaseModel):
    field: str
    score: float
    risk_types: list[str]
    evidence: list[str]


class ContentInferResult(BaseModel):
    content_id: str
    text_score: float
    risk_level: str
    risk_types: list[str]
    field_results: list[FieldResult]
    hit_keywords: list[str]
    brand_entities: list[str]
    contact_entities: list[str]
    explanation: str
    model_version: str = "text-risk-v0.1.0"


class BatchInferResult(BaseModel):
    items: list[TextInferResult]
