from pydantic import BaseModel


class KeywordHit(BaseModel):
    word: str
    normalized_word: str | None = None
    category: str
    dictionary: str
    start: int | None = None
    end: int | None = None


class ContactEntity(BaseModel):
    type: str
    text: str
    masked: str | None = None
    start: int | None = None
    end: int | None = None


class BrandEntity(BaseModel):
    brand: str
    text: str
    confidence: float = 0.85
    start: int | None = None
    end: int | None = None


class SemanticResult(BaseModel):
    label: str
    score: float

