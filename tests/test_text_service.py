import pytest
from httpx import ASGITransport, AsyncClient

from text_service.main import app
from text_service.services.dictionary_matcher import DictionaryMatcher
from text_service.services.entity_extractor import EntityExtractor
from text_service.services.normalizer import TextNormalizer


@pytest.mark.anyio
async def test_text_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_normalizer_traditional_and_variant():
    assert "中华" in TextNormalizer().normalize("中華 华子")


def test_dictionary_matcher_hits_trade():
    hits = DictionaryMatcher().match("刚到一批 私聊")
    assert {hit.category for hit in hits} >= {"trade"}


def test_dictionary_matcher_covers_management_rule_words():
    hits = DictionaryMatcher().match("绿花 黑金刚 老客户 面交 本地")
    words = {hit.normalized_word for hit in hits}
    assert {"绿花", "黑金刚", "老客户", "面交", "本地"} <= words


def test_entity_extractor_masks_phone():
    entities = EntityExtractor().extract_contacts("电话 13812345678")
    assert entities[0].masked == "138****5678"


@pytest.mark.anyio
async def test_text_infer_high_risk():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/infer/text", json={"content_id": "t1", "source": "comment", "text": "刚到一批，懂的私聊，主页有方式"})
    data = res.json()
    assert data["risk_level"] in {"medium", "high"}
    assert "trade_lead" in data["risk_types"]


@pytest.mark.anyio
async def test_text_infer_rule_word_has_keyword_explanation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/infer/text", json={"content_id": "t_rule", "source": "comment", "text": "黑金刚"})
    data = res.json()
    assert data["hit_keywords"]
    assert data["explanation"] != "未发现明显烟草交易风险表达。"
