import json

from audio_service.config import ROOT_DIR
from audio_service.schemas import ASRSegment, AudioKeywordHit, BrandEntity


class AudioKeywordMatcher:
    def __init__(self):
        data_dir = ROOT_DIR / "audio_service" / "data"
        self.risk = json.loads((data_dir / "audio_risk_keywords.json").read_text(encoding="utf-8"))
        self.brands = json.loads((data_dir / "brand_keywords.json").read_text(encoding="utf-8"))
        self.whitelist = json.loads((data_dir / "whitelist_keywords.json").read_text(encoding="utf-8"))

    def match(self, segments: list[ASRSegment], transcript: str) -> list[AudioKeywordHit]:
        hits: list[AudioKeywordHit] = []
        for segment in segments or [ASRSegment(start=None or 0.0, end=None or 0.0, text=transcript, confidence=None)]:
            text = segment.text.lower()
            for category, words in {**self.risk, **self.whitelist}.items():
                for word in words:
                    if word.lower() in text:
                        hits.append(AudioKeywordHit(word=word, normalized_word=word, category=category, dictionary="audio_risk_keywords" if category not in {"anti_smoking", "news", "education"} else "whitelist_keywords", start_time=segment.start, end_time=segment.end, segment_text=segment.text))
        return hits

    def match_brands(self, transcript: str) -> list[BrandEntity]:
        text = transcript.lower()
        results = []
        for brand, words in self.brands.items():
            if any(word.lower() in text for word in words):
                results.append(BrandEntity(brand=brand, text=brand, confidence=0.80))
        return results

    def dictionaries(self) -> dict:
        return {"audio_risk_keywords": self.risk, "brand_keywords": self.brands, "whitelist_keywords": self.whitelist}
