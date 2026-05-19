#!/usr/bin/env python3
import json

import requests

payload = {
    "items": [
        {"content_id": "c1", "source": "comment", "text": "还有货吗，私聊"},
        {"content_id": "c2", "source": "title", "text": "控烟宣传活动"},
    ]
}
res = requests.post("http://127.0.0.1:8010/infer/batch", json=payload, timeout=10)
print(json.dumps(res.json(), ensure_ascii=False, indent=2))
