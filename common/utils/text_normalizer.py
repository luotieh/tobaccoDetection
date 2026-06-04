import re
import unicodedata


_PHRASE_MAP = {"中華": "中华"}
_TRADITIONAL_MAP = str.maketrans({
    "華": "华",
    "煙": "烟",
    "菸": "烟",
    "價": "价",
    "貨": "货",
    "號": "号",
    "聯": "联",
    "繫": "系",
    "郵": "邮",
    "現": "现",
    "賣": "卖",
    "買": "买",
})


class TextNormalizer:
    def normalize(self, text: str | None) -> str:
        if not text:
            return ""
        value = unicodedata.normalize("NFKC", text)
        for source, target in _PHRASE_MAP.items():
            value = value.replace(source, target)
        value = value.translate(_TRADITIONAL_MAP)
        value = "".join(ch for ch in value if unicodedata.category(ch) not in {"Cf", "Cc"} or ch in "\n\t ")
        value = re.sub(r"\s+", " ", value).strip()
        return value.lower()
