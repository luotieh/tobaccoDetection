#!/usr/bin/env python3
import json
import sys

import requests


def main() -> None:
    text = " ".join(sys.argv[1:]) or "刚到一批，懂的私聊，主页有方式"
    res = requests.post("http://127.0.0.1:8010/infer/text", json={"content_id": "demo_text_001", "source": "cli", "text": text}, timeout=10)
    print(json.dumps(res.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
