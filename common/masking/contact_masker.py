import re

from common.schemas.text import ContactEntity


class ContactMasker:
    def mask_phone(self, text: str) -> str:
        return re.sub(r"(\d{3})\d{4}(\d{4})", r"\1****\2", text)

    def mask_qq(self, text: str) -> str:
        return re.sub(r"(\d{3})\d+(\d{3})", r"\1****\2", text)

    def mask_wechat(self, text: str) -> str:
        if len(text) <= 4:
            return text[0:1] + "****" if text else text
        return f"{text[:2]}****{text[-2:]}"

    def mask_contact_entities(self, entities: list[ContactEntity]) -> list[ContactEntity]:
        masked = []
        for entity in entities:
            value = entity.text
            if entity.type == "phone":
                value = self.mask_phone(value)
            elif entity.type == "qq":
                value = self.mask_qq(value)
            elif entity.type in {"wechat", "contact_hint"}:
                value = self.mask_wechat(value)
            masked.append(entity.model_copy(update={"masked": value}))
        return masked

