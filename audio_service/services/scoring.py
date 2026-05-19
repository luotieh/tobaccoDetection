from common.scoring.audio_scoring import score_audio as common_score_audio
from audio_service.config import settings


def risk_level(score: float) -> str:
    if score >= settings.risk_high:
        return "high"
    if score >= settings.risk_medium:
        return "medium"
    if score >= settings.risk_low:
        return "low"
    return "none"


def score_audio_with_types(hits, brands, contacts=None) -> tuple[float, str, list[str]]:
    return common_score_audio(
        hits,
        brands,
        contacts or [],
        thresholds=(settings.risk_high, settings.risk_medium, settings.risk_low),
    )


def score_audio(hits, brands) -> tuple[float, str]:
    score, level, _ = score_audio_with_types(hits, brands)
    return score, level
