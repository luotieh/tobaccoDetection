from common.scoring.text_scoring import score_text as common_score_text
from text_service.config import settings


def risk_level(score: float) -> str:
    if score >= settings.risk_high:
        return "high"
    if score >= settings.risk_medium:
        return "medium"
    if score >= settings.risk_low:
        return "low"
    return "none"


def score_text(hits, semantics, brands, contacts) -> tuple[float, str, list[str]]:
    return common_score_text(
        hits,
        semantics,
        brands,
        contacts,
        thresholds=(settings.risk_high, settings.risk_medium, settings.risk_low),
    )
