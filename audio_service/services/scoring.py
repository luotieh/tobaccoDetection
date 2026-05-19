from audio_service.config import settings
from audio_service.schemas import AudioKeywordHit, BrandEntity


def risk_level(score: float) -> str:
    if score >= settings.risk_high:
        return "high"
    if score >= settings.risk_medium:
        return "medium"
    if score >= settings.risk_low:
        return "low"
    return "none"


def score_audio(hits: list[AudioKeywordHit], brands: list[BrandEntity]) -> tuple[float, str]:
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
    contact_score = 0.90 if "contact" in categories else 0.75 if "slang" in categories else 0.0
    segment_count = len({hit.segment_text for hit in hits if hit.category in {"trade", "contact", "slang"}})
    repetition_score = 0.80 if segment_count >= 2 else 0.30 if segment_count == 1 else 0.0
    whitelist_penalty = 0.20 if categories & {"anti_smoking", "news", "education"} else 0.0
    if whitelist_penalty and not (categories & {"trade", "contact", "price", "quantity", "slang"}):
        whitelist_penalty = 0.50
    score = 0.30 * keyword_score + 0.30 * intent_score + 0.15 * brand_score + 0.15 * contact_score + 0.10 * repetition_score - whitelist_penalty
    score = round(max(0.0, min(score, 1.0)), 4)
    return score, risk_level(score)
