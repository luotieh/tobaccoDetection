from pathlib import Path

from common.dictionaries import DictionaryLoader, KeywordMatcher
from common.masking import ContactMasker
from common.scoring import score_text
from common.schemas.text import SemanticResult
from common.utils.entity_extractor import EntityExtractor
from common.utils.text_normalizer import TextNormalizer
from common.utils.time_utils import seconds_to_timestamp, validate_time_range


def test_common_normalizer_handles_empty_fullwidth_and_traditional():
    assert TextNormalizer().normalize(None) == ""
    assert TextNormalizer().normalize("中華　ABC") == "中华 abc"


def test_common_dictionary_matcher_and_version():
    loader = DictionaryLoader(Path("text_service/data"))
    hits = KeywordMatcher(loader).match("刚到一批，主页有")
    assert loader.version
    assert {hit.category for hit in hits} >= {"trade", "contact"}


def test_common_contact_masker_and_entities():
    masker = ContactMasker()
    assert masker.mask_phone("13812345678") == "138****5678"
    entity = EntityExtractor().extract_contacts("电话 13812345678，主页有方式")
    assert {item.type for item in entity} >= {"phone", "contact_hint"}


def test_common_time_utils():
    assert seconds_to_timestamp(65.25) == "00:01:05.250"
    assert validate_time_range(0.0, 1.0)


def test_common_text_scoring_whitelist_penalty():
    hits = KeywordMatcher(DictionaryLoader(Path("text_service/data"))).match("控烟宣传活动，未成年人禁止吸烟")
    score, level, risk_types = score_text(hits, [SemanticResult(label="whitelist_context", score=0.9)], [], [])
    assert score < 0.5
    assert level == "none"
    assert "whitelist_context" in risk_types

