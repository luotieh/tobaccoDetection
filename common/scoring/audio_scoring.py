from common.schemas.text import BrandEntity, ContactEntity, KeywordHit
from common.scoring.text_scoring import risk_level


def score_audio(
    hits: list[KeywordHit],
    brands: list[BrandEntity],
    contacts: list[ContactEntity] | None = None,
    thresholds: tuple[float, float, float] = (0.85, 0.70, 0.50),
) -> tuple[float, str, list[str]]:
    contacts = contacts or []
    categories = {hit.category for hit in hits}
    keyword_score = 0.0
    if "trade" in categories:
        keyword_score = max(keyword_score, 0.75)
    if "slang" in categories:
        keyword_score = max(keyword_score, 0.80)
    if "price" in categories:
        keyword_score = max(keyword_score, 0.60)
    if len(categories & {"trade", "contact", "price", "quantity", "slang"}) >= 2:
        keyword_score = max(keyword_score, 0.95)

    intent_score = 0.90 if "trade" in categories and "contact" in categories else 0.75 if {"price", "quantity"} <= categories else 0.45 if "trade" in categories else 0.0
    brand_score = 0.90 if brands and "trade" in categories else 0.70 if brands else 0.0
    contact_score = 0.90 if "contact" in categories or contacts else 0.75 if "slang" in categories else 0.0
    repetition_score = 0.80 if len([hit for hit in hits if hit.category in {"trade", "contact", "slang"}]) >= 3 else 0.30 if hits else 0.0
    whitelist_penalty = 0.20 if categories & {"anti_smoking", "news", "education"} else 0.0
    if whitelist_penalty and not (categories & {"trade", "contact", "price", "quantity", "slang"}):
        whitelist_penalty = 0.50
    score = 0.30 * keyword_score + 0.30 * intent_score + 0.15 * brand_score + 0.15 * contact_score + 0.10 * repetition_score - whitelist_penalty
    score = round(max(0.0, min(score, 1.0)), 4)
    risk_types = []
    if "trade" in categories:
        risk_types.extend(["sale_intent", "trade_lead"])
    if "contact" in categories or contacts:
        risk_types.append("contact_lead")
    if "slang" in categories:
        risk_types.append("slang_mention")
    if brands:
        risk_types.append("brand_mention")
    if categories & {"anti_smoking", "news", "education"}:
        risk_types.append("whitelist_context")
    return score, risk_level(score, *thresholds), sorted(set(risk_types)) or ["normal_discussion"]

