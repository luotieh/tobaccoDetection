import json
from pathlib import Path


class DictionaryLoader:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self._cache: dict | None = None
        self._version: str = ""

    def load_all(self) -> dict:
        if self._cache is None:
            self._cache = self._load()
        return self._cache

    def reload(self) -> dict:
        self._cache = self._load()
        return self._cache

    @property
    def version(self) -> str:
        if self._cache is None:
            self.load_all()
        return self._version

    def _load(self) -> dict:
        names = ["brand_keywords", "risk_keywords", "slang_keywords", "whitelist_keywords"]
        data = {}
        versions = []
        for name in names:
            path = self.data_dir / f"{name}.json"
            if not path.exists():
                raise FileNotFoundError(f"Dictionary file not found: {path}")
            data[name] = json.loads(path.read_text(encoding="utf-8"))
            versions.append(str(int(path.stat().st_mtime)))
        self._version = ".".join(versions)
        return data

