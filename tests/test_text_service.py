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


@pytest.mark.anyio
async def test_models_info_exposes_semantic_engine():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/models/info")
    semantic_model = res.json()["semantic_model"]
    assert semantic_model["engine"] in {"mock", "transformers", "llm"}
    assert "mock" in semantic_model
    assert "model_dir" in semantic_model


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
    assert data["text_score"] >= 0.70
    assert "trade_lead" in data["risk_types"]


@pytest.mark.anyio
async def test_text_infer_rule_word_has_keyword_explanation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/infer/text", json={"content_id": "t_rule", "source": "comment", "text": "黑金刚"})
    data = res.json()
    assert data["hit_keywords"]
    assert data["explanation"] != "未发现明显烟草交易风险表达。"


@pytest.mark.anyio
async def test_content_infer_accumulates_body_and_comment_sale_intent():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/infer/content", json={
            "content_id": "content_sale_001",
            "platform": "小红书",
            "title": "新到分享",
            "description": "刚到一批，数量有限",
            "account_name": "城南优选",
            "account_bio": "主页有方式",
            "comments": ["多少钱一条", "想要的私聊"],
            "ocr_texts": [],
            "asr_texts": [],
            "content_url": "https://example.com",
        })
    data = res.json()
    assert data["risk_level"] in {"medium", "high"}
    assert data["text_score"] >= 0.70
    assert {"sale_intent", "trade_lead", "contact_lead", "price_quantity"} <= set(data["risk_types"])
    assert {"刚到一批", "主页有", "一条", "私聊"} <= set(data["hit_keywords"])


@pytest.mark.anyio
async def test_content_infer_scores_smoke_tube_inquiry_comments():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/infer/content", json={
            "content_id": "tube_sale_001",
            "platform": "kuaishou",
            "title": "#空纸管 #空心管空烟管空心纸管",
            "description": "#空纸管 #空心管空烟管空心纸管",
            "account_name": "小婷空管",
            "account_bio": "",
            "comments": ["6，5的多少钱一条子", "哪里下单", "5.5烟管多少钱一盒"],
            "ocr_texts": [],
            "asr_texts": [],
            "content_url": "https://example.com",
        })
    data = res.json()
    assert data["risk_level"] in {"medium", "high"}
    assert data["text_score"] >= 0.82
    assert {"trade_lead", "price_quantity", "tobacco_product_mention"} <= set(data["risk_types"])
    assert {"空心管", "空烟管", "烟管", "多少钱", "下单", "一条", "一盒"} <= set(data["hit_keywords"])
