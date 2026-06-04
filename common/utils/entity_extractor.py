import re

from common.masking import ContactMasker
from common.schemas.text import BrandEntity, ContactEntity, KeywordHit


class EntityExtractor:
    def __init__(self):
        self.masker = ContactMasker()

    def extract_contacts(self, text: str) -> list[ContactEntity]:
        entities: list[ContactEntity] = []
        for match in re.finditer(r"1[3-9]\d{9}", text or ""):
            entities.append(ContactEntity(type="phone", text=match.group(0), start=match.start(), end=match.end()))
        for match in re.finditer(r"(?:qq|扣扣)\s*[:：]?\s*(\d{4,12})", text or "", flags=re.IGNORECASE):
            entities.append(ContactEntity(type="qq", text=match.group(0), start=match.start(), end=match.end()))
        for match in re.finditer(r"(微信|vx|v信|加我|主页有|看主页)[\w\-_.]{0,16}", text or "", flags=re.IGNORECASE):
            entities.append(ContactEntity(type="contact_hint", text=match.group(0), start=match.start(), end=match.end()))
        return self.masker.mask_contact_entities(entities)

    def extract_brands(self, hits: list[KeywordHit]) -> list[BrandEntity]:
        results: list[BrandEntity] = []
        seen: set[tuple[str, str]] = set()
        for hit in hits:
            if hit.dictionary != "brand_keywords":
                continue
            key = (hit.category, hit.word)
            if key in seen:
                continue
            seen.add(key)
            results.append(BrandEntity(brand=hit.category, text=hit.word, start=hit.start, end=hit.end))
        return results

