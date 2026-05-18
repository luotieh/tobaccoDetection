from typing import Literal

from pydantic import BaseModel, Field


class Detection(BaseModel):
    class_name: str
    label_zh: str
    bbox: list[float]
    confidence: float
    timestamp: str | None = None


class OCRText(BaseModel):
    text: str
    confidence: float
    bbox: list[float] | None = None


class BrandResult(BaseModel):
    brand: str
    confidence: float
    source: str = "ocr_keyword"


class EvidenceFrame(BaseModel):
    timestamp: str | None = None
    image_path: str
    description: str


class VisualResult(BaseModel):
    content_id: str
    media_type: Literal["image", "video"]
    visual_score: float
    risk_level: Literal["high", "medium", "low", "none"]
    detected_objects: list[Detection] = Field(default_factory=list)
    brand_results: list[BrandResult] = Field(default_factory=list)
    ocr_text: list[OCRText] = Field(default_factory=list)
    scene_tags: list[str] = Field(default_factory=list)
    evidence_frames: list[EvidenceFrame] = Field(default_factory=list)
    model_version: str = "vision-tobacco-v0.1.0"


class VideoVisualResult(VisualResult):
    duration_seconds: float
    sampled_frames: int


class ErrorDetail(BaseModel):
    code: str
    message: str


class ModelInfo(BaseModel):
    detector: dict
    ocr: dict
