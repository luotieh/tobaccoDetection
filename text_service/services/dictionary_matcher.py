from common.dictionaries import DictionaryLoader, KeywordMatcher
from text_service.config import ROOT_DIR


class DictionaryMatcher:
    def __init__(self):
        data_dir = ROOT_DIR / "text_service" / "data"
        self.loader = DictionaryLoader(data_dir)
        self.matcher = KeywordMatcher(self.loader)

    def match(self, text: str):
        return self.matcher.match(text)

    def raw(self) -> dict:
        return self.loader.load_all()
