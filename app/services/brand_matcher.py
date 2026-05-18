import json
from pathlib import Path

from app.config import ROOT_DIR
from app.schemas import BrandResult, OCRText


def normalize_text(value: str) -> str:
    return value.lower().replace("中華", "中华").replace("黃鶴樓", "黄鹤楼").replace("雲煙", "云烟")


class BrandMatcher:
    def __init__(self, keyword_path: Path | None = None):
        self.keyword_path = keyword_path or ROOT_DIR / "app" / "data" / "brand_keywords.json"
        self.keywords = json.loads(self.keyword_path.read_text(encoding="utf-8"))

    def match(self, ocr_texts: list[OCRText]) -> list[BrandResult]:
        text = normalize_text(" ".join(item.text for item in ocr_texts))
        results: list[BrandResult] = []
        for brand, words in self.keywords.items():
            for word in words:
                if normalize_text(word) in text:
                    confidence = max((item.confidence for item in ocr_texts if normalize_text(word) in normalize_text(item.text)), default=0.8)
                    results.append(BrandResult(brand=brand, confidence=round(min(confidence, 1.0), 2)))
                    break
        return results
