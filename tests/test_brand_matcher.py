from app.schemas import OCRText
from app.services.brand_matcher import BrandMatcher


def test_match_chinese_brand():
    result = BrandMatcher().match([OCRText(text="硬中华 现货", confidence=0.91)])
    assert result[0].brand == "中华"


def test_match_foreign_brand():
    result = BrandMatcher().match([OCRText(text="Marlboro low price", confidence=0.88)])
    assert result[0].brand == "外烟"


def test_no_brand():
    assert BrandMatcher().match([OCRText(text="普通图片", confidence=0.8)]) == []
