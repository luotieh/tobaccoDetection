from text_service.config import settings
from text_service.schemas import KeywordHit, SemanticResult, TextEntity


LABEL_MAPPING = {
    "LABEL_0": "normal_discussion",
    "LABEL_1": "sale_intent",
    "LABEL_2": "trade_lead",
    "LABEL_3": "brand_mention",
    "LABEL_4": "slang_mention",
    "LABEL_5": "contact_lead",
    "LABEL_6": "price_quantity",
    "LABEL_7": "whitelist_context",
}


class MockSemanticClassifier:
    mock = True

    def classify(self, hits: list[KeywordHit], contacts: list[TextEntity]) -> list[SemanticResult]:
        dictionaries = {(hit.dictionary, hit.category) for hit in hits}
        labels: dict[str, float] = {}
        has_trade = ("risk_keywords", "trade") in dictionaries
        has_contact = bool(contacts) or ("risk_keywords", "contact") in dictionaries
        has_price = ("risk_keywords", "price") in dictionaries
        has_brand = any(hit.dictionary == "brand_keywords" for hit in hits)
        has_slang = any(hit.dictionary == "slang_keywords" for hit in hits)
        has_whitelist = any(hit.dictionary == "whitelist_keywords" for hit in hits)
        if has_trade and has_contact:
            labels.update({"sale_intent": 0.85, "trade_lead": 0.90, "contact_lead": 0.85})
        elif has_brand and has_price:
            labels.update({"sale_intent": 0.80, "brand_mention": 0.90, "price_quantity": 0.70})
        elif has_slang and has_trade:
            labels.update({"slang_mention": 0.85, "trade_lead": 0.80})
        elif has_trade:
            labels.update({"trade_lead": 0.70, "sale_intent": 0.62})
        if has_slang:
            labels["slang_mention"] = max(labels.get("slang_mention", 0), 0.85)
        if has_whitelist and not has_trade:
            labels.update({"whitelist_context": 0.90, "normal_discussion": 0.70})
        elif has_whitelist:
            labels["whitelist_context"] = 0.90
        if not labels:
            labels["normal_discussion"] = 0.80
        return [SemanticResult(label=label, score=round(score, 2)) for label, score in labels.items()]


class TransformersSemanticClassifier:
    def __init__(self):
        self.mock = False
        self.pipeline = None
        try:
            from transformers import pipeline

            self.pipeline = pipeline(
                "text-classification",
                model=str(settings.resolve(settings.model_dir)),
                tokenizer=str(settings.resolve(settings.model_dir)),
                top_k=None,
                truncation=True,
                max_length=settings.max_text_length,
            )
        except Exception as exc:
            self.error = str(exc)
            if not settings.use_mock_model:
                raise RuntimeError(f"Text model load failed: {exc}") from exc
            self.mock = True
            self.fallback = MockSemanticClassifier()

    def classify(self, hits: list[KeywordHit], contacts: list[TextEntity]) -> list[SemanticResult]:
        if self.mock or self.pipeline is None:
            return self.fallback.classify(hits, contacts)
        raw = self.pipeline(" ".join(hit.word for hit in hits) or "")
        items = raw[0] if raw and isinstance(raw[0], list) else raw
        return [
            SemanticResult(label=LABEL_MAPPING.get(item["label"], item["label"]), score=round(float(item["score"]), 4))
            for item in items
        ]


class SemanticClassifier:
    def __init__(self):
        if settings.use_mock_model or not settings.resolve(settings.model_dir).exists():
            self.impl = MockSemanticClassifier()
        else:
            self.impl = TransformersSemanticClassifier()
        self.mock = self.impl.mock

    def classify(self, hits: list[KeywordHit], contacts: list[TextEntity]) -> list[SemanticResult]:
        return self.impl.classify(hits, contacts)
