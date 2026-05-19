from common.utils.text_normalizer import TextNormalizer as BaseTextNormalizer
from text_service.config import settings

VARIANT_MAP = {"薇": "微信", "卫星": "微信", "企鹅": "qq", "扣扣": "qq", "华子": "中华", "楼子": "黄鹤楼"}


class TextNormalizer(BaseTextNormalizer):
    def normalize(self, text: str) -> str:
        value = (text or "")[: settings.max_text_length]
        value = super().normalize(value) if settings.enable_traditional_to_simplified else value.lower()
        for source, target in VARIANT_MAP.items():
            value = value.replace(source, target)
        return value
