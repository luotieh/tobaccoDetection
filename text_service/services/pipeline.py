import json

from text_service.config import settings
from text_service.schemas import ContentInferRequest, ContentInferResult, EvidenceText, FieldResult, TextInferResult
from text_service.services.dictionary_matcher import DictionaryMatcher
from text_service.services.entity_extractor import EntityExtractor
from text_service.services.explanation import explain
from text_service.services.normalizer import TextNormalizer
from text_service.services.scoring import score_text
from text_service.services.semantic_classifier import SemanticClassifier


class TextRiskPipeline:
    def __init__(self):
        self.normalizer = TextNormalizer()
        self.matcher = DictionaryMatcher()
        self.extractor = EntityExtractor()
        self.classifier = SemanticClassifier()

    def info(self) -> dict:
        return {
            "semantic_model": {"enabled": True, "mock": self.classifier.mock, "model_dir": str(settings.model_dir), "labels": list(json.loads((settings.resolve(__import__('pathlib').Path('text_service/data/label_mapping.json'))).read_text(encoding='utf-8')).keys())},
            "rules": {"enabled": settings.enable_rules, "dictionaries": list(self.matcher.raw().keys())},
        }

    def infer_text(self, content_id: str, source: str, text: str) -> TextInferResult:
        normalized = self.normalizer.normalize(text)
        hits = self.matcher.match(normalized) if settings.enable_rules else []
        contacts = self.extractor.extract_contacts(normalized)
        brands = self.extractor.extract_brands(hits)
        semantics = self.classifier.classify(hits, contacts)
        score, level, risk_types = score_text(hits, semantics, brands, contacts)
        evidence = [EvidenceText(source=source, text=text, start=0, end=len(text))] if hits or contacts else []
        return TextInferResult(
            content_id=content_id,
            source=source,
            text_score=score,
            risk_level=level,
            risk_types=risk_types,
            hit_keywords=hits,
            brand_entities=brands,
            contact_entities=contacts,
            evidence_text=evidence,
            explanation=explain(hits, brands, contacts, risk_types),
        )

    def infer_content(self, req: ContentInferRequest) -> ContentInferResult:
        fields: list[tuple[str, str]] = [
            ("title", req.title),
            ("description", req.description),
            ("account_name", req.account_name),
            ("account_bio", req.account_bio),
        ]
        fields += [("comments", item) for item in req.comments]
        fields += [("ocr_texts", item) for item in req.ocr_texts]
        fields += [("asr_texts", item) for item in req.asr_texts]
        results = [self.infer_text(req.content_id, field, text) for field, text in fields if text]
        max_score = max((item.text_score for item in results), default=0.0)
        all_hits = [hit for item in results for hit in item.hit_keywords]
        all_contacts = [entity for item in results for entity in item.contact_entities]
        all_brands = [brand for item in results for brand in item.brand_entities]
        all_semantics = self.classifier.classify(all_hits, all_contacts) if results else []
        aggregate_score, aggregate_level, aggregate_types = score_text(all_hits, all_semantics, all_brands, all_contacts)
        active_fields = {item.source for item in results if item.text_score >= settings.risk_low or item.hit_keywords or item.contact_entities}
        if len(active_fields) >= 2 and aggregate_score >= settings.risk_low:
            aggregate_score = min(1.0, max(aggregate_score, max_score + 0.08))
            aggregate_level = score_text([], [], [], [])[1]
            if aggregate_score >= settings.risk_high:
                aggregate_level = "high"
            elif aggregate_score >= settings.risk_medium:
                aggregate_level = "medium"
            elif aggregate_score >= settings.risk_low:
                aggregate_level = "low"
        final_score = max(max_score, aggregate_score)
        final_level = aggregate_level
        if max_score > aggregate_score and results:
            final_level = results[[item.text_score for item in results].index(max_score)].risk_level
        risk_types = sorted({typ for item in results for typ in item.risk_types if typ != "normal_discussion"} | {typ for typ in aggregate_types if typ != "normal_discussion"})
        field_results = [
            FieldResult(field=item.source, score=item.text_score, risk_types=item.risk_types, evidence=[ev.text for ev in item.evidence_text])
            for item in results
            if item.text_score > 0 or item.evidence_text
        ]
        hit_words = sorted({hit.normalized_word or hit.word for item in results for hit in item.hit_keywords})
        brands = sorted({brand.brand for item in results for brand in item.brand_entities})
        contacts = sorted({entity.masked for item in results for entity in item.contact_entities})
        explanation = "多字段文本中出现交易、品牌、联系方式或白名单语境，已完成综合文本风险判断。" if results else "未提供可识别文本。"
        return ContentInferResult(
            content_id=req.content_id,
            text_score=round(final_score, 4),
            risk_level=score_text([], [], [], [])[1] if not results else final_level,
            risk_types=risk_types or ["normal_discussion"],
            field_results=field_results,
            hit_keywords=hit_words,
            brand_entities=brands,
            contact_entities=contacts,
            explanation=explanation,
        )


pipeline = TextRiskPipeline()
