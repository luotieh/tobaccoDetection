from httpx import ASGITransport, AsyncClient
import pytest

from audio_service.main import app
from audio_service.schemas import ASRSegment
from audio_service.services.keyword_matcher import AudioKeywordMatcher
from audio_service.services.scoring import score_audio
from audio_service.utils.time_utils import format_timestamp


@pytest.mark.anyio
async def test_audio_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_time_format():
    assert format_timestamp(65.25) == "00:01:05.250"


def test_keyword_matcher_maps_segment_time():
    hits = AudioKeywordMatcher().match([ASRSegment(start=3.2, end=8.5, text="刚到一批，需要看主页", confidence=0.9)], "")
    assert hits[0].start_time == 3.2
    assert {hit.category for hit in hits} >= {"trade", "contact"}


def test_audio_scoring_high():
    matcher = AudioKeywordMatcher()
    hits = matcher.match([ASRSegment(start=0, end=5, text="中华刚到一批，需要看主页私聊", confidence=0.9)], "中华刚到一批，需要看主页私聊")
    brands = matcher.match_brands("中华刚到一批，需要看主页私聊")
    score, level = score_audio(hits, brands)
    assert score >= 0.85
    assert level == "high"
