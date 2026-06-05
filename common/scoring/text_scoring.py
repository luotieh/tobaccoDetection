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
    risk_hits = [hit for hit in hits if hit.dictionary in {"risk_keywords", "slang_keywords"}]
    risk_categories = {hit.category for hit in risk_hits}
    hit_words = {hit.normalized_word or hit.word for hit in risk_hits}
    keyword_score = 0.0
    if ("risk_keywords", "trade") in hit_types:
        keyword_score = max(keyword_score, 0.75)
    if any(hit.dictionary == "slang_keywords" for hit in hits):
        keyword_score = max(keyword_score, 0.80)
    if ("risk_keywords", "price") in hit_types:
        keyword_score = max(keyword_score, 0.60)
    if ("risk_keywords", "quantity") in hit_types:
        keyword_score = max(keyword_score, 0.65)
    if len(risk_categories) >= 2:
        keyword_score = max(keyword_score, 0.95)

    semantic_scores = {item.label: item.score for item in semantics}
    semantic_score = max((item.score for item in semantics if item.label != "normal_discussion"), default=0.0)
    if (
        semantic_scores.get("sale_intent", 0.0) >= 0.75
        and semantic_scores.get("trade_lead", 0.0) >= 0.75
        and semantic_scores.get("contact_lead", 0.0) >= 0.75
    ):
        semantic_score = max(semantic_score, 0.90)
    brand_score = 0.80 if brands else 0.0
    contact_score = 0.90 if any(item.type in {"phone", "qq"} for item in contacts) else 0.75 if contacts else 0.0
    if ("risk_keywords", "contact") in hit_types:
        contact_score = max(contact_score, 0.80)
    context_score = 0.80 if ("risk_keywords", "delivery") in hit_types else 0.30 if keyword_score else 0.0
    whitelist_penalty = 0.20 if any(hit.dictionary == "whitelist_keywords" for hit in hits) else 0.0
    if whitelist_penalty and not keyword_score and not contacts:
        whitelist_penalty = 0.50
    llm_whitelist = semantic_scores.get("whitelist_context", 0.0) >= 0.80
    if llm_whitelist and not contacts and keyword_score < 0.60:
        whitelist_penalty = max(whitelist_penalty, 0.40)
    score = 0.30 * keyword_score + 0.35 * semantic_score + 0.15 * brand_score + 0.10 * contact_score + 0.10 * context_score - whitelist_penalty
    rule_floor = 0.0
    has_trade = "trade" in risk_categories
    has_contact = bool(contacts) or "contact" in risk_categories
    has_price_or_quantity = bool({"price", "quantity"} & risk_categories)
    has_delivery = "delivery" in risk_categories
    has_product = "product" in risk_categories
    has_slang = any(hit.dictionary == "slang_keywords" for hit in hits)
    has_brand = bool(brands)
    if has_trade and has_contact:
        rule_floor = max(rule_floor, 0.88)
    if has_trade and has_price_or_quantity:
        rule_floor = max(rule_floor, 0.82)
    if has_trade and has_delivery:
        rule_floor = max(rule_floor, 0.78)
    if has_product and (has_trade or has_contact or has_price_or_quantity):
        rule_floor = max(rule_floor, 0.82)
    if has_slang and (has_trade or has_contact):
        rule_floor = max(rule_floor, 0.82)
    if has_brand and (has_trade or has_price_or_quantity):
        rule_floor = max(rule_floor, 0.80)
    if len(risk_categories) >= 3 or len(hit_words) >= 4:
        rule_floor = max(rule_floor, 0.86)
    if has_trade and len(hit_words) >= 2:
        rule_floor = max(rule_floor, 0.72)
    score = max(score, rule_floor - whitelist_penalty)
    score = round(max(0.0, min(score, 1.0)), 4)
    risk_types = sorted({item.label for item in semantics if item.score >= 0.6 and item.label != "normal_discussion"})
    if has_trade:
        risk_types.extend(["sale_intent", "trade_lead"])
    if has_contact:
        risk_types.append("contact_lead")
    if has_price_or_quantity:
        risk_types.append("price_quantity")
    if has_product:
        risk_types.append("tobacco_product_mention")
    if has_slang:
        risk_types.append("slang_mention")
    if has_brand:
        risk_types.append("brand_mention")
    if any(hit.dictionary == "whitelist_keywords" for hit in hits):
        risk_types.append("whitelist_context")
    if any(hit.category == "delivery" for hit in hits):
        risk_types.append("regional_delivery_context")
    return score, risk_level(score, *thresholds), sorted(set(risk_types)) or ["normal_discussion"]
