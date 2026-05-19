from common.dictionaries.loader import DictionaryLoader
from common.schemas.text import KeywordHit


class KeywordMatcher:
    def __init__(self, loader: DictionaryLoader):
        self.loader = loader

    def match(self, text: str) -> list[KeywordHit]:
        lowered = (text or "").lower()
        hits: list[KeywordHit] = []
        seen: set[tuple[str, str, str, int]] = set()
        for dictionary, groups in self.loader.load_all().items():
            for category, words in groups.items():
                for word in words:
                    needle = str(word).lower()
                    start = lowered.find(needle)
                    while start >= 0:
                        key = (dictionary, category, needle, start)
                        if key not in seen:
                            seen.add(key)
                            hits.append(KeywordHit(
                                word=text[start : start + len(str(word))],
                                normalized_word=str(word),
                                category=category,
                                dictionary=dictionary,
                                start=start,
                                end=start + len(str(word)),
                            ))
                        start = lowered.find(needle, start + 1)
        return sorted(hits, key=lambda hit: (hit.start if hit.start is not None else 10**9, hit.end or 0, hit.dictionary))

