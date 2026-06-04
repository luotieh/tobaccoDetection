from common.utils.entity_extractor import EntityExtractor as CommonEntityExtractor
from text_service.schemas import BrandEntity, KeywordHit, TextEntity


class EntityExtractor(CommonEntityExtractor):
    def extract_contacts(self, text: str) -> list[TextEntity]:
        return [TextEntity(type=item.type, text=item.text, masked=item.masked or item.text) for item in super().extract_contacts(text)]

    def extract_brands(self, hits: list[KeywordHit]) -> list[BrandEntity]:
        return [BrandEntity(brand=item.brand, text=item.text, confidence=item.confidence) for item in super().extract_brands(hits)]
