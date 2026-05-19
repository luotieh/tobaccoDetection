from common.schemas.text import BrandEntity, ContactEntity, KeywordHit, SemanticResult


def risk_level(score: float, high: float = 0.85, medium: float = 0.70, low: float = 0.50) -> str:
    if score >= high:
        return "high"
    if score >= medium:
        return "medium"
    if score >= low:
        return "low"
    return "none"


def score_text(
    hits: list[KeywordHit],
    semantics: list[SemanticResult],
    brands: list[BrandEntity],
    contacts: list[ContactEntity],
    thresholds: tuple[float, float, float] = (0.85, 0.70, 0.50),
) -> tuple[float, str, list[str]]:
    hit_types = {(hit.dictionary, hit.category) for hit in hits}
    keyword_score = 0.0
    if ("risk_keywords", "trade") in hit_types:
        keyword_score = max(keyword_score, 0.75)
    if any(hit.dictionary == "slang_keywords" for hit in hits):
        keyword_score = max(keyword_score, 0.80)
    if ("risk_keywords", "price") in hit_types:
        keyword_score = max(keyword_score, 0.60)
    if len({hit.category for hit in hits if hit.dictionary in {"risk_keywords", "slang_keywords"}}) >= 2:
        keyword_score = max(keyword_score, 0.95)

    semantic_score = max((item.score for item in semantics if item.label != "normal_discussion"), default=0.0)
    brand_score = 0.80 if brands else 0.0
    contact_score = 0.90 if any(item.type in {"phone", "qq"} for item in contacts) else 0.75 if contacts else 0.0
    context_score = 0.80 if ("risk_keywords", "delivery") in hit_types else 0.30 if keyword_score else 0.0
    whitelist_penalty = 0.20 if any(hit.dictionary == "whitelist_keywords" for hit in hits) else 0.0
    if whitelist_penalty and not keyword_score and not contacts:
        whitelist_penalty = 0.50
    score = 0.30 * keyword_score + 0.35 * semantic_score + 0.15 * brand_score + 0.10 * contact_score + 0.10 * context_score - whitelist_penalty
    score = round(max(0.0, min(score, 1.0)), 4)
    risk_types = sorted({item.label for item in semantics if item.score >= 0.6 and item.label != "normal_discussion"})
    if any(hit.dictionary == "whitelist_keywords" for hit in hits):
        risk_types.append("whitelist_context")
    return score, risk_level(score, *thresholds), sorted(set(risk_types)) or ["normal_discussion"]

