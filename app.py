#!/usr/bin/env python3
import base64
import cgi
import http.client
import json
import os
import random
import re
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "demo.db"
MODEL_REGISTRY = {
    "basant-yolo26s": {
        "name": "basant18/Smoking-detection-YOLO26s",
        "version": "Smoking-detection-YOLO26s/best.pt",
        "path": Path(os.environ.get("SMOKING_MODEL_PATH", ROOT / "models" / "best.pt")),
        "source_url": "https://huggingface.co/basant18/Smoking-detection-YOLO26s/resolve/main/weights/best.pt",
        "description": "YOLO26s smoking detection model",
    },
    "enos-yolo11m": {
        "name": "Enos-123/smoking-detection",
        "version": "YOLOv11-Medium/best.pt",
        "path": Path(os.environ.get("ENOS_SMOKING_MODEL_PATH", ROOT / "models" / "enos-smoking-detection-best.pt")),
        "source_url": "https://huggingface.co/Enos-123/smoking-detection/resolve/main/best.pt",
        "description": "YOLOv11-Medium cigarette detector, class: cigarette",
    },
}
DEFAULT_DETECTOR_MODEL_ID = os.environ.get("SMOKING_DETECTOR_MODEL", "basant-yolo26s")
VISION_SERVICE_URL = os.environ.get("VISION_SERVICE_URL", "http://127.0.0.1:9000")
TEXT_SERVICE_URL = os.environ.get("TEXT_SERVICE_URL", "http://127.0.0.1:8010")
AUDIO_SERVICE_URL = os.environ.get("AUDIO_SERVICE_URL", "http://127.0.0.1:8020")
_YOLO_MODELS = {}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix):
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100, 999)}"


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(row) for row in rows]


def json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


SCHEMA = """
CREATE TABLE IF NOT EXISTS content_items (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  content_type TEXT NOT NULL,
  title TEXT NOT NULL,
  account_name TEXT NOT NULL,
  account_url TEXT DEFAULT '',
  content_url TEXT DEFAULT '',
  raw_text TEXT DEFAULT '',
  media_url TEXT DEFAULT '',
  publish_time TEXT DEFAULT '',
  collect_time TEXT DEFAULT '',
  recognize_status TEXT DEFAULT 'pending',
  risk_score REAL DEFAULT 0,
  risk_level TEXT DEFAULT '无风险',
  review_status TEXT DEFAULT 'unreviewed',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_configs (
  id TEXT PRIMARY KEY,
  model_name TEXT NOT NULL,
  model_type TEXT NOT NULL,
  model_version TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  threshold REAL NOT NULL,
  timeout INTEGER NOT NULL,
  enabled INTEGER NOT NULL,
  description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS fusion_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  text_weight REAL NOT NULL,
  image_weight REAL NOT NULL,
  audio_weight REAL NOT NULL,
  account_weight REAL NOT NULL,
  high_risk_threshold REAL NOT NULL,
  medium_risk_threshold REAL NOT NULL,
  low_risk_threshold REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS recognition_results (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL,
  model_type TEXT NOT NULL,
  model_version TEXT NOT NULL,
  risk_score REAL NOT NULL,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_words (
  id TEXT PRIMARY KEY,
  rule_type TEXT NOT NULL,
  word TEXT NOT NULL,
  risk_weight REAL NOT NULL,
  enabled INTEGER NOT NULL,
  remark TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_records (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL,
  review_status TEXT NOT NULL,
  review_opinion TEXT DEFAULT '',
  reviewer TEXT DEFAULT '',
  review_time TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_logs (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL,
  report_id TEXT DEFAULT '',
  push_status TEXT NOT NULL,
  push_time TEXT DEFAULT '',
  retry_count INTEGER DEFAULT 0,
  error_message TEXT DEFAULT ''
);
"""


MODELS = [
    ("m_text_001", "文本交易意图识别模型", "text", "text-risk-v0.1.0", "/api/text-service/infer-content", 0.70, 30, 1, "调用文本风险服务识别标题、正文、评论、OCR/ASR 文本中的违法售烟关键词和交易意图"),
    ("m_image_001", "Smoking-detection-YOLO26s 图像识别模型", "image", "Smoking-detection-YOLO26s/best.pt", "/api/image-detector/analyze", 0.50, 30, 1, "使用 Hugging Face basant18/Smoking-detection-YOLO26s 的 best.pt 识别图片中的香烟目标"),
    ("m_image_002", "Enos smoking-detection 图像识别模型", "image", "YOLOv11-Medium/best.pt", "/api/image-detector/analyze", 0.50, 30, 1, "使用 Hugging Face Enos-123/smoking-detection 的 best.pt 识别 cigarette 目标"),
    ("m_audio_001", "语音交易话术识别模型", "audio", "audio-risk-v0.1.0", "/api/audio-service/infer-video-audio", 0.70, 60, 1, "调用语音服务完成音视频 ASR 转写、关键词识别和交易话术评分"),
    ("m_fusion_001", "多模态融合评分模型", "fusion", "fusion-risk-v1.0", "/api/mock/fusion/analyze", 0.80, 30, 1, "综合文本、图像、语音结果输出最终风险评分"),
]


RULES = [
    ("keyword", "私聊", 0.22, "交易引流词"),
    ("keyword", "有货", 0.24, "现货表达"),
    ("keyword", "到货", 0.20, "到货表达"),
    ("keyword", "一条", 0.24, "计量交易词"),
    ("keyword", "面交", 0.20, "线下交易词"),
    ("keyword", "私信", 0.18, "引流词"),
    ("keyword", "刚到一批", 0.26, "到货交易表达"),
    ("blackword", "绿花", 0.22, "黑话示例"),
    ("blackword", "黑金刚", 0.24, "黑话示例"),
    ("blackword", "懂的来", 0.20, "暗示交易"),
    ("blackword", "老客户", 0.16, "熟客交易暗示"),
    ("brand", "中华", 0.18, "品牌词"),
    ("brand", "玉溪", 0.16, "品牌词"),
    ("brand", "黄鹤楼", 0.16, "品牌词"),
    ("whitelist", "科普", -0.25, "宣传科普"),
    ("whitelist", "新闻", -0.25, "新闻报道"),
    ("whitelist", "禁烟宣传", -0.35, "公益宣传"),
    ("region", "本地", 0.08, "地域交易暗示"),
]


CONTENTS = [
    ("C001", "抖音", "视频", "今天刚到一批，懂的来", "城南优选", "今天刚到一批，想要的私信我，懂的来。", "/mock/images/cigarette_001.jpg", "高风险"),
    ("C002", "快手", "视频", "老客户私聊", "阿明生活馆", "老客户私聊，有货不多。", "/mock/images/cigarette_002.jpg", "高风险"),
    ("C003", "小红书", "图片", "礼盒分享，仅展示", "收藏笔记", "新礼盒分享，仅展示不交易。", "/mock/images/gift_001.jpg", "中风险"),
    ("C004", "微博", "文本", "禁烟宣传科普", "健康城市", "禁烟宣传科普：远离烟草危害。", "", "无风险"),
    ("C005", "抖音", "评论", "多少钱一条", "用户3948", "多少钱一条，怎么拿？", "", "高风险"),
    ("C006", "小红书", "图片", "新包装收藏展示", "包装收藏家", "新包装收藏展示，科普用途。", "/mock/images/package_001.jpg", "低风险"),
    ("C007", "快手", "视频", "本地现货，主页有方式", "同城速递", "本地现货，主页有方式，面交。", "/mock/images/cigarette_003.jpg", "高风险"),
    ("C008", "微博", "文本", "新闻报道：打击违法售烟", "法治日报", "新闻报道：多地开展打击违法售烟专项行动。", "", "无风险"),
    ("C009", "抖音", "视频", "老牌子到货", "老张杂谈", "老牌子到货，数量有限。", "/mock/images/cigarette_004.jpg", "中风险"),
    ("C010", "小红书", "评论", "怎么拿，私信吗", "用户7291", "怎么拿，私信吗？", "", "高风险"),
]


def init_db():
    DATA_DIR.mkdir(exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM model_configs").fetchone()[0] == 0:
            conn.executemany("INSERT INTO model_configs VALUES (?,?,?,?,?,?,?,?,?)", MODELS)
        else:
            for model in MODELS:
                exists = conn.execute("SELECT 1 FROM model_configs WHERE id=?", (model[0],)).fetchone()
                if exists:
                    conn.execute(
                        """UPDATE model_configs
                           SET model_name=?, model_type=?, model_version=?, endpoint=?, threshold=?, timeout=?, enabled=?, description=?
                           WHERE id=?""",
                        (model[1], model[2], model[3], model[4], model[5], model[6], model[7], model[8], model[0]),
                    )
                else:
                    conn.execute("INSERT INTO model_configs VALUES (?,?,?,?,?,?,?,?,?)", model)
        if conn.execute("SELECT COUNT(*) FROM fusion_config").fetchone()[0] == 0:
            conn.execute("INSERT INTO fusion_config VALUES (1,0.30,0.35,0.25,0.10,0.85,0.65,0.40)")
        if conn.execute("SELECT COUNT(*) FROM rule_words").fetchone()[0] == 0:
            for idx, (typ, word, weight, remark) in enumerate(RULES, 1):
                conn.execute(
                    "INSERT INTO rule_words VALUES (?,?,?,?,?,?,?)",
                    (f"R{idx:03d}", typ, word, weight, 1, remark, now()),
                )
        else:
            for typ, word, weight, remark in RULES:
                exists = conn.execute("SELECT 1 FROM rule_words WHERE rule_type=? AND word=?", (typ, word)).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO rule_words VALUES (?,?,?,?,?,?,?)",
                        (new_id("RW"), typ, word, weight, 1, remark, now()),
                    )
        if conn.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == 0:
            base = datetime.now()
            for idx, (cid, platform, ctype, title, account, text, media, _) in enumerate(CONTENTS):
                t = (base - timedelta(hours=idx * 3)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute(
                    """INSERT INTO content_items
                    (id,platform,content_type,title,account_name,account_url,content_url,raw_text,media_url,publish_time,collect_time,recognize_status,risk_score,risk_level,review_status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, platform, ctype, title, account, f"https://example.com/account/{cid}", f"https://example.com/content/{cid}", text, media, t, t, "pending", 0, "无风险", "unreviewed", t, t),
                )


def enabled_rules(rule_type=None):
    with db() as conn:
        if rule_type:
            rows = conn.execute("SELECT * FROM rule_words WHERE enabled=1 AND rule_type=?", (rule_type,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM rule_words WHERE enabled=1").fetchall()
    return rows_to_list(rows)


def analyze_text(payload):
    text = (payload.get("text") or "").strip()
    rules = enabled_rules()
    whitelist = [r for r in rules if r["rule_type"] == "whitelist" and r["word"] in text]
    hits = [r for r in rules if r["rule_type"] == "keyword" and r["word"] in text]
    black = [r for r in rules if r["rule_type"] == "blackword" and r["word"] in text]
    brands = [r for r in rules if r["rule_type"] == "brand" and r["word"] in text]
    score = 0.10 + sum(r["risk_weight"] for r in hits + black + brands) + sum(r["risk_weight"] for r in whitelist)
    score = max(0, min(0.96, score))
    return {
        "text_risk_score": round(score, 2),
        "hit_keywords": [r["word"] for r in hits],
        "hit_black_words": [r["word"] for r in black],
        "intent_type": "疑似交易引流" if score >= 0.65 else "未发现明确交易意图",
        "evidence_text": text[:120],
        "confidence": round(min(0.95, 0.55 + score * 0.45), 2),
        "model_version": "text-risk-v1.0",
    }


def analyze_image(payload):
    key = f"{payload.get('content_id', '')} {payload.get('image_url', '')}"
    risky = any(token in key for token in ["C001", "C002", "C007", "C009", "cigarette"])
    medium = any(token in key for token in ["C003", "gift", "package"])
    score = 0.95 if risky else 0.55 if medium else 0.18
    return {
        "image_risk_score": score,
        "detected_objects": ["香烟包装", "条盒"] if score >= 0.65 else ["礼盒包装"] if medium else [],
        "brand": "疑似中华" if risky else "未识别",
        "ocr_text": ["私聊", "到货"] if risky else ["仅展示"] if medium else [],
        "confidence": 0.92 if risky else 0.68 if medium else 0.41,
        "evidence_frame": payload.get("image_url") or "/mock/images/evidence_001.jpg",
        "model_version": "image-risk-v1.0",
    }


def resolve_media_path(media_url):
    if not media_url:
        return None
    parsed = urlparse(media_url)
    if parsed.scheme in {"http", "https"}:
        return None
    raw_path = parsed.path if parsed.scheme else media_url
    path = Path(raw_path)
    candidates = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.extend([ROOT / raw_path.lstrip("/"), ROOT / "static" / raw_path.lstrip("/")])
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


def vision_service_path(path):
    parsed = urlparse(VISION_SERVICE_URL)
    return f"{parsed.path.rstrip('/')}{path}" if parsed.path else path


def call_vision_image_service(content_id, image_path, conf=0.35, model_id=None):
    parsed = urlparse(VISION_SERVICE_URL)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("VISION_SERVICE_URL 仅支持 http/https")
    boundary = f"----tobacco-{uuid.uuid4().hex}"
    data = image_path.read_bytes()
    fields = [
        ("content_id", content_id.encode("utf-8"), None),
        ("conf", str(conf).encode("utf-8"), None),
        ("save_evidence", b"true", None),
        ("file", data, image_path.name),
    ]
    if model_id:
        fields.insert(2, ("model_id", str(model_id).encode("utf-8"), None))
    body = bytearray()
    for name, value, filename in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        if filename:
            body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode("utf-8"))
            body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
        else:
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(value)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), timeout=30)
    try:
        conn.request(
            "POST",
            vision_service_path("/infer/image"),
            body=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))},
        )
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        if resp.status >= 400:
            raise RuntimeError(raw or f"视觉服务返回 HTTP {resp.status}")
        return json.loads(raw)
    finally:
        conn.close()


def call_vision_video_service(content_id, video_path, conf=0.35, model_id=None):
    parsed = urlparse(VISION_SERVICE_URL)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("VISION_SERVICE_URL 仅支持 http/https")
    fields = {"content_id": content_id, "conf": conf}
    if model_id:
        fields["model_id"] = model_id
    return service_post_file(
        VISION_SERVICE_URL,
        "/infer/video",
        {"data": video_path.read_bytes(), "filename": video_path.name},
        fields=fields,
        timeout=180,
    )


def call_vision_image_service_bytes(content_id, image_bytes, filename, conf=0.35, model_id=None):
    suffix = Path(filename or "upload.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        suffix = ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(image_bytes)
        tmp.flush()
        return call_vision_image_service(content_id, Path(tmp.name), conf=conf, model_id=model_id)


def vision_service_status(selected_model_id=None):
    parsed = urlparse(VISION_SERVICE_URL)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("VISION_SERVICE_URL 仅支持 http/https")
    suffix = f"?model_id={selected_model_id}" if selected_model_id else ""
    data = service_get(VISION_SERVICE_URL, f"/models/info{suffix}", timeout=10)
    detector = data.get("detector", {})
    current_id = detector.get("model_id") or selected_model_id or "default"
    raw_models = detector.get("available_models") or [{"id": current_id, "weights": detector.get("weights", ""), "model_exists": detector.get("model_exists", False), "model_size_mb": detector.get("model_size_mb", 0)}]
    models = [
        {
            "id": item.get("id"),
            "name": item.get("id"),
            "version": Path(item.get("weights", "")).name or item.get("id"),
            "description": "视觉服务 YOLO 模型",
            "model_path": item.get("weights", ""),
            "model_exists": item.get("model_exists", False),
            "model_size_mb": item.get("model_size_mb", 0),
        }
        for item in raw_models
    ]
    current = next((item for item in models if item["id"] == current_id), models[0] if models else {})
    return {
        **current,
        "service_url": VISION_SERVICE_URL,
        "service_mode": "vision-service",
        "current_model_id": current_id,
        "models": models,
        "dependencies": {
            "vision_service": "ok",
            "detector_type": detector.get("type", "-"),
            "ocr": data.get("ocr", {}).get("engine", "-"),
            "ocr_mock": data.get("ocr", {}).get("mock", "-"),
        },
        "ready": not bool(detector.get("mock", True)),
        "mock": detector.get("mock", True),
    }


def service_request(base_url, method, path, body=None, content_type=None, timeout=60):
    parsed = urlparse(base_url)
    target = path if path.startswith("/") else f"/{path}"
    if parsed.path and parsed.path != "/":
        target = parsed.path.rstrip("/") + target
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), timeout=timeout)
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    try:
        conn.request(method, target, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        if resp.status >= 400:
            message = data.get("detail") or data.get("error") or raw or f"HTTP {resp.status}"
            raise RuntimeError(message)
        return data
    finally:
        conn.close()


def service_get(base_url, path, timeout=10):
    return service_request(base_url, "GET", path, timeout=timeout)


def service_post_json(base_url, path, payload, timeout=60):
    return service_request(
        base_url,
        "POST",
        path,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        content_type="application/json; charset=utf-8",
        timeout=timeout,
    )


def service_post_file(base_url, path, file_payload, fields=None, timeout=120):
    boundary = f"----tobacco-{uuid.uuid4().hex}"
    parts = []
    for name, value in (fields or {}).items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    filename = file_payload["filename"]
    parts.extend([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n".encode("utf-8"),
        b"Content-Type: application/octet-stream\r\n\r\n",
        file_payload["data"],
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    return service_request(
        base_url,
        "POST",
        path,
        body=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=timeout,
    )


def text_service_analyze_content(content):
    payload = {
        "content_id": content["id"],
        "platform": content["platform"],
        "title": content["title"] or "",
        "description": content["raw_text"] or "",
        "account_name": content["account_name"] or "",
        "account_bio": "",
        "comments": [content["raw_text"]] if content["content_type"] == "评论" and content["raw_text"] else [],
        "ocr_texts": [],
        "asr_texts": [],
        "content_url": content["content_url"] or "",
    }
    result = service_post_json(TEXT_SERVICE_URL, "/infer/content", payload)
    result = merge_business_text_rules({"text": " ".join([payload["title"], payload["description"], payload["account_name"]])}, result)
    result["text_risk_score"] = float(result.get("text_score") or 0)
    result["model_version"] = result.get("model_version", "text-risk-v0.1.0")
    result["service_mode"] = "text-service"
    return result


def audio_service_analyze_media(content, media_path):
    media_type = "video" if content["content_type"] == "视频" or media_path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"} else "audio"
    endpoint = "/infer/video-audio" if media_type == "video" else "/infer/audio"
    result = service_post_file(
        AUDIO_SERVICE_URL,
        endpoint,
        {"data": media_path.read_bytes(), "filename": media_path.name},
        fields={"content_id": content["id"], "save_evidence": "true"},
        timeout=240,
    )
    result["audio_risk_score"] = float(result.get("audio_score") or 0)
    result["model_version"] = result.get("model_version", "audio-risk-v0.1.0")
    result["service_mode"] = "audio-service"
    return result


def text_service_status():
    return {
        "base_url": TEXT_SERVICE_URL,
        "health": service_get(TEXT_SERVICE_URL, "/health"),
        "models": service_get(TEXT_SERVICE_URL, "/models/info"),
    }


def audio_service_status():
    return {
        "base_url": AUDIO_SERVICE_URL,
        "health": service_get(AUDIO_SERVICE_URL, "/health"),
        "models": service_get(AUDIO_SERVICE_URL, "/models/info"),
    }


def merge_business_text_rules(payload, result):
    text = (payload.get("text") or "").strip()
    if not text:
        return result
    rules = enabled_rules()
    matched = [r for r in rules if r["word"] and r["word"] in text]
    if not matched:
        return result

    existing_words = {item.get("word") for item in result.get("hit_keywords", []) if isinstance(item, dict)}
    additions = []
    risk_types = set(result.get("risk_types") or [])
    for rule in matched:
        word = rule["word"]
        if word not in existing_words:
            start = text.find(word)
            category = {
                "keyword": "trade",
                "blackword": "slang",
                "brand": "brand",
                "whitelist": "whitelist",
                "region": "delivery",
            }.get(rule["rule_type"], rule["rule_type"])
            additions.append({
                "word": word,
                "normalized_word": word,
                "category": category,
                "dictionary": "management_rule_words",
                "start": start,
                "end": start + len(word) if start >= 0 else None,
            })
        if rule["rule_type"] == "keyword":
            risk_types.update({"sale_intent", "trade_lead"})
        elif rule["rule_type"] == "blackword":
            risk_types.add("slang_mention")
        elif rule["rule_type"] == "brand":
            risk_types.add("brand_mention")
        elif rule["rule_type"] == "whitelist":
            risk_types.add("whitelist_context")
        elif rule["rule_type"] == "region":
            risk_types.add("regional_delivery_context")

    if additions:
        result["hit_keywords"] = (result.get("hit_keywords") or []) + additions
    if risk_types:
        result["risk_types"] = sorted(risk_types - {"normal_discussion"}) or sorted(risk_types)
    positive_rules = [r for r in matched if r["rule_type"] != "whitelist"]
    if positive_rules and result.get("risk_level") == "none":
        result["risk_level"] = "low"
        result["text_score"] = max(float(result.get("text_score") or 0), 0.5)
    if positive_rules and result.get("explanation") == "未发现明显烟草交易风险表达。":
        words = "、".join(r["word"] for r in positive_rules[:8])
        result["explanation"] = f"文本命中管理端规则词库：{words}，需要结合上下文复核。"
    return result


def visual_result_to_image_result(visual_result, evidence_frame):
    detections = visual_result.get("detected_objects") or []
    ocr_items = visual_result.get("ocr_text") or []
    brands = visual_result.get("brand_results") or []
    return {
        "image_risk_score": float(visual_result.get("visual_score") or 0),
        "detected_objects": [item.get("label_zh") or item.get("class_name") for item in detections],
        "brand": "、".join(item.get("brand", "") for item in brands if item.get("brand")) or "未识别",
        "ocr_text": [item.get("text", "") for item in ocr_items if item.get("text")],
        "confidence": max([float(item.get("confidence") or 0) for item in detections], default=float(visual_result.get("visual_score") or 0)),
        "evidence_frame": evidence_frame,
        "scene_tags": visual_result.get("scene_tags") or [],
        "risk_level": visual_result.get("risk_level", "none"),
        "visual_score": visual_result.get("visual_score", 0),
        "visual_service_result": visual_result,
        "model_version": visual_result.get("model_version", "vision-tobacco-v0.1.0"),
    }


def yolo_result_to_image_result(yolo_result, evidence_frame):
    detections = yolo_result.get("detections") or []
    return {
        "image_risk_score": float(yolo_result.get("image_risk_score") or 0),
        "detected_objects": yolo_result.get("detected_objects") or [],
        "brand": "未识别",
        "ocr_text": [],
        "confidence": float(yolo_result.get("confidence") or 0),
        "evidence_frame": evidence_frame,
        "detections": detections,
        "model_id": yolo_result.get("model_id"),
        "model_name": yolo_result.get("model_name"),
        "model_version": yolo_result.get("model_version", "Smoking-detection-YOLO26s/best.pt"),
    }


def analyze_image_with_vision(payload):
    media_path = resolve_media_path(payload.get("image_url"))
    if not media_path:
        return analyze_image(payload)
    content_id = payload.get("content_id") or new_id("IMG")
    evidence_frame = str(media_path)
    try:
        if media_path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"} or payload.get("media_type") == "video":
            visual_result = call_vision_video_service(content_id, media_path, conf=float(payload.get("conf") or 0.35), model_id=payload.get("model_id"))
        else:
            visual_result = call_vision_image_service(content_id, media_path, conf=float(payload.get("conf") or 0.35), model_id=payload.get("model_id"))
        return visual_result_to_image_result(visual_result, evidence_frame)
    except Exception as exc:
        try:
            yolo_result = yolo_detect_image(media_path.read_bytes(), filename=media_path.name, conf=float(payload.get("conf") or 0.5), model_id=payload.get("model_id"))
            result = yolo_result_to_image_result(yolo_result, evidence_frame)
            result["vision_fallback_reason"] = str(exc)
            return result
        except Exception as inner_exc:
            result = analyze_image(payload)
            result["vision_fallback_reason"] = str(exc)
            result["yolo_fallback_reason"] = str(inner_exc)
            return result


def detector_model_info(model_id, cfg):
    path = cfg["path"]
    return {
        "id": model_id,
        "name": cfg["name"],
        "version": cfg["version"],
        "description": cfg["description"],
        "model_path": str(path),
        "model_exists": path.exists(),
        "model_size_mb": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
        "model_source_url": cfg["source_url"],
    }


def normalize_detector_model_id(model_id=None):
    if model_id in MODEL_REGISTRY:
        return model_id
    if DEFAULT_DETECTOR_MODEL_ID in MODEL_REGISTRY:
        return DEFAULT_DETECTOR_MODEL_ID
    return next(iter(MODEL_REGISTRY))


def image_detector_status(selected_model_id=None):
    try:
        return vision_service_status(selected_model_id)
    except Exception as exc:
        fallback_reason = str(exc)
    deps = {}
    for module in ["ultralytics", "cv2", "torch"]:
        try:
            imported = __import__(module)
            deps[module] = getattr(imported, "__version__", "installed")
        except Exception as exc:
            deps[module] = f"missing: {exc}"
    model_id = normalize_detector_model_id(selected_model_id)
    models = [detector_model_info(mid, cfg) for mid, cfg in MODEL_REGISTRY.items()]
    current = next(item for item in models if item["id"] == model_id)
    return {
        **current,
        "service_url": VISION_SERVICE_URL,
        "service_mode": "local-yolo-fallback",
        "vision_service_error": fallback_reason,
        "current_model_id": model_id,
        "models": models,
        "dependencies": deps,
        "ready": current["model_exists"] and all(not str(v).startswith("missing:") for v in deps.values()),
    }


def visual_result_to_detector_result(visual_result, model_id=None):
    detections = []
    for item in visual_result.get("detected_objects") or []:
        bbox = item.get("bbox") or [0, 0, 0, 0]
        detections.append({
            "class_id": item.get("class_id", 0),
            "class_name": item.get("class_name") or item.get("label_zh") or "unknown",
            "confidence": float(item.get("confidence") or 0),
            "box": {
                "x1": bbox[0] if len(bbox) > 0 else 0,
                "y1": bbox[1] if len(bbox) > 1 else 0,
                "x2": bbox[2] if len(bbox) > 2 else 0,
                "y2": bbox[3] if len(bbox) > 3 else 0,
            },
        })
    evidence = visual_result.get("evidence_frames") or []
    return {
        "detected": bool(detections),
        "confidence": max([item["confidence"] for item in detections], default=0),
        "image_risk_score": float(visual_result.get("visual_score") or 0),
        "detected_objects": [item["class_name"] for item in detections],
        "detections": detections,
        "annotated_image": evidence[0].get("image_path") if evidence and isinstance(evidence[0], dict) else "",
        "model_id": model_id or "vision-service",
        "model_name": "tobacco-vision-risk-service",
        "model_version": visual_result.get("model_version", "vision-tobacco-v0.1.0"),
        "service_mode": "vision-service",
        "visual_service_result": visual_result,
    }


def vision_detect_image(image_bytes, filename="", conf=0.5, model_id=None, imgsz=None):
    content_id = f"detector_{uuid.uuid4().hex[:12]}"
    visual_result = call_vision_image_service_bytes(content_id, image_bytes, filename, conf=conf, model_id=model_id)
    return visual_result_to_detector_result(visual_result, model_id=model_id)


def load_yolo_model(model_id=None):
    model_id = normalize_detector_model_id(model_id)
    if model_id in _YOLO_MODELS:
        return _YOLO_MODELS[model_id], MODEL_REGISTRY[model_id]
    cfg = MODEL_REGISTRY[model_id]
    model_path = cfg["path"]
    if not model_path.exists():
        raise RuntimeError(f"模型文件不存在：{model_path}，请从 {cfg['source_url']} 下载 best.pt")
    try:
        from ultralytics import YOLO
    except Exception as exc:
        raise RuntimeError("缺少 ultralytics 依赖，请先执行：pip install -r requirements.txt") from exc
    _YOLO_MODELS[model_id] = YOLO(str(model_path))
    return _YOLO_MODELS[model_id], cfg


def yolo_detect_image(image_bytes, filename="", conf=0.5, imgsz=800, model_id=None):
    if not image_bytes:
        raise ValueError("请上传图片文件")
    suffix = Path(filename or "upload.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
        suffix = ".jpg"
    model_id = normalize_detector_model_id(model_id)
    model, cfg = load_yolo_model(model_id)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
        tmp.write(image_bytes)
        tmp.flush()
        results = model.predict(source=tmp.name, imgsz=int(imgsz), conf=float(conf), verbose=False)
    result = results[0]
    names = getattr(result, "names", {}) or getattr(model, "names", {}) or {}
    detections = []
    boxes = getattr(result, "boxes", None)
    if boxes is not None:
        for box in boxes:
            cls_id = int(box.cls[0].item())
            score = float(box.conf[0].item())
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            detections.append({
                "class_id": cls_id,
                "class_name": names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id),
                "confidence": round(score, 4),
                "box": {
                    "x1": round(xyxy[0], 2),
                    "y1": round(xyxy[1], 2),
                    "x2": round(xyxy[2], 2),
                    "y2": round(xyxy[3], 2),
                },
            })
    max_conf = max([d["confidence"] for d in detections], default=0)
    annotated_image = ""
    try:
        import cv2
        plotted = result.plot()
        ok, encoded = cv2.imencode(".jpg", plotted)
        if ok:
            annotated_image = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
    except Exception:
        annotated_image = ""
    return {
        "model_id": model_id,
        "model_name": cfg["name"],
        "model_version": cfg["version"],
        "image_risk_score": round(max_conf, 4),
        "detected": bool(detections),
        "detected_objects": sorted({d["class_name"] for d in detections}),
        "detections": detections,
        "confidence": round(max_conf, 4),
        "threshold": float(conf),
        "image_size": int(imgsz),
        "annotated_image": annotated_image,
    }


def analyze_audio(payload):
    cid = payload.get("content_id", "")
    risky = cid in {"C001", "C002", "C007"}
    medium = cid == "C009"
    score = 0.93 if risky else 0.62 if medium else 0.12
    transcript = "今天刚到一批，想要的私信我" if risky else "老牌子到货，数量有限" if medium else ""
    return {
        "audio_risk_score": score,
        "transcript": transcript,
        "hit_keywords": ["刚到一批", "私信"] if risky else ["到货"] if medium else [],
        "intent_type": "疑似交易引流" if score >= 0.65 else "未发现明确交易意图",
        "timestamp": "00:12-00:18" if score >= 0.65 else "",
        "confidence": 0.90 if risky else 0.61 if medium else 0.35,
        "model_version": "audio-risk-v1.0",
    }


def fusion_config():
    with db() as conn:
        return row_to_dict(conn.execute("SELECT * FROM fusion_config WHERE id=1").fetchone())


def analyze_fusion(payload):
    cfg = fusion_config()
    text_score = float(payload.get("text_risk_score") or 0)
    image_score = float(payload.get("image_risk_score") or 0)
    audio_score = float(payload.get("audio_risk_score") or 0)
    score = (
        text_score * cfg["text_weight"]
        + image_score * cfg["image_weight"]
        + audio_score * cfg["audio_weight"]
        + float(payload.get("account_risk_score") or 0) * cfg["account_weight"]
    )
    strongest_modality = max(text_score, image_score, audio_score)
    effective_score = max(score, strongest_modality if strongest_modality >= 0.50 else score)
    if effective_score >= cfg["high_risk_threshold"]:
        level = "高风险"
    elif effective_score >= cfg["medium_risk_threshold"]:
        level = "中风险"
    elif effective_score >= cfg["low_risk_threshold"]:
        level = "低风险"
    elif strongest_modality >= 0.85:
        level = "高风险"
    elif strongest_modality >= 0.70:
        level = "中风险"
    elif strongest_modality >= 0.50:
        level = "低风险"
    else:
        level = "无风险"
    violation = []
    if image_score >= 0.65:
        violation.append("图像疑似售烟")
    if text_score >= 0.65:
        violation.append("文本交易引流")
    if audio_score >= 0.65:
        violation.append("语音交易暗示")
    return {
        "risk_score": round(effective_score, 2),
        "weighted_score": round(score, 2),
        "risk_level": level,
        "violation_type": violation or ["未发现明显违规"],
        "hit_modalities": [name for name, value in [("文本", payload.get("text_risk_score", 0)), ("图像", payload.get("image_risk_score", 0)), ("语音", payload.get("audio_risk_score", 0))] if float(value or 0) >= 0.65],
        "model_explanation": "该内容同时出现香烟包装、交易关键词或口播引流表达，综合判断存在违法售烟风险。" if violation else "当前内容未触发主要违法售烟特征。",
        "review_suggestion": "建议人工复核后推送监管平台。" if level in {"高风险", "中风险"} else "建议归档观察。",
        "model_version": "fusion-risk-v1.0",
    }


def recognize_content(content_id):
    with db() as conn:
        content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone())
        if not content:
            return None
        conn.execute("DELETE FROM recognition_results WHERE content_id=?", (content_id,))
        try:
            text_result = text_service_analyze_content(content)
        except Exception as exc:
            text_result = analyze_text({"content_id": content_id, "text": f"{content['title']} {content['raw_text']}"})
            text_result["service_mode"] = "local-text-fallback"
            text_result["text_service_error"] = str(exc)
        image_score = 0
        audio_score = 0
        image_result = None
        audio_result = None
        media_path = resolve_media_path(content["media_url"])
        if content["media_url"] or content["content_type"] in {"图片", "视频"}:
            image_result = analyze_image_with_vision({"content_id": content_id, "image_url": content["media_url"], "media_type": "video" if content["content_type"] == "视频" else "image"})
            image_score = image_result["image_risk_score"]
        if content["content_type"] in {"视频", "音频"} and media_path:
            try:
                audio_result = audio_service_analyze_media(content, media_path)
            except Exception as exc:
                audio_result = analyze_audio({"content_id": content_id, "audio_url": content["media_url"]})
                audio_result["service_mode"] = "local-audio-fallback"
                audio_result["audio_service_error"] = str(exc)
            audio_score = audio_result["audio_risk_score"]
        account_score = 0.70 if any(w in content["account_name"] for w in ["同城", "优选", "生活馆"]) else 0.25
        fusion = analyze_fusion({
            "content_id": content_id,
            "text_risk_score": text_result["text_risk_score"],
            "image_risk_score": image_score,
            "audio_risk_score": audio_score,
            "account_risk_score": account_score,
        })
        for typ, result, score_key in [
            ("text", text_result, "text_risk_score"),
            ("image", image_result, "image_risk_score"),
            ("audio", audio_result, "audio_risk_score"),
            ("fusion", fusion, "risk_score"),
        ]:
            if not result:
                continue
            conn.execute(
                "INSERT INTO recognition_results VALUES (?,?,?,?,?,?,?)",
                (new_id("RR"), content_id, typ, result["model_version"], float(result[score_key]), json.dumps(result, ensure_ascii=False), now()),
            )
        review_status = "pending" if fusion["risk_level"] in {"高风险", "中风险"} else "unreviewed"
        conn.execute(
            "UPDATE content_items SET recognize_status='completed', risk_score=?, risk_level=?, review_status=?, updated_at=? WHERE id=?",
            (fusion["risk_score"], fusion["risk_level"], review_status, now(), content_id),
        )
    return get_content_detail(content_id)


def get_content_detail(content_id):
    with db() as conn:
        content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone())
        if not content:
            return None
        results = rows_to_list(conn.execute("SELECT * FROM recognition_results WHERE content_id=? ORDER BY created_at", (content_id,)).fetchall())
        reviews = rows_to_list(conn.execute("SELECT * FROM review_records WHERE content_id=? ORDER BY review_time DESC", (content_id,)).fetchall())
        pushes = rows_to_list(conn.execute("SELECT * FROM push_logs WHERE content_id=? ORDER BY push_time DESC", (content_id,)).fetchall())
    for item in results:
        item["result"] = json_loads(item.pop("result_json"), {})
    return {"content": content, "results": results, "reviews": reviews, "push_logs": pushes}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200, content_type="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def body_multipart_image(self):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        image = form["image"] if "image" in form else None
        if image is None or not getattr(image, "file", None):
            raise ValueError("缺少 image 文件字段")
        def form_value(name, default):
            return form[name].value if name in form and not getattr(form[name], "filename", None) else default
        return {
            "image_bytes": image.file.read(),
            "filename": image.filename or "upload.jpg",
            "conf": float(form_value("conf", 0.5)),
            "imgsz": int(form_value("imgsz", 800)),
            "model_id": form_value("model_id", DEFAULT_DETECTOR_MODEL_ID),
        }

    def body_multipart_file(self):
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        upload = form["file"] if "file" in form else None
        if upload is None or not getattr(upload, "file", None):
            raise ValueError("缺少 file 文件字段")

        def form_value(name, default=""):
            return form[name].value if name in form and not getattr(form[name], "filename", None) else default

        return {
            "file": {
                "data": upload.file.read(),
                "filename": upload.filename or "upload.bin",
            },
            "content_id": form_value("content_id"),
            "save_evidence": form_value("save_evidence", "true"),
        }

    def serve_static(self):
        path = urlparse(self.path).path
        file_path = STATIC_DIR / ("index.html" if path in {"/", ""} else path.lstrip("/"))
        if not file_path.exists() or not file_path.is_file() or STATIC_DIR not in file_path.resolve().parents:
            file_path = STATIC_DIR / "index.html"
        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self.send_text(file_path.read_text(encoding="utf-8"), 200, content_type)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if not path.startswith("/api/"):
            return self.serve_static()
        try:
            if path == "/api/dashboard":
                return self.send_json(api_dashboard())
            if path == "/api/contents":
                return self.send_json(api_contents(qs))
            if m := re.match(r"^/api/contents/([^/]+)$", path):
                detail = get_content_detail(m.group(1))
                return self.send_json(detail or {"error": "not found"}, 200 if detail else 404)
            if path == "/api/models":
                with db() as conn:
                    return self.send_json(rows_to_list(conn.execute("SELECT * FROM model_configs ORDER BY model_type").fetchall()))
            if path == "/api/image-detector/status":
                return self.send_json(image_detector_status(qs.get("model_id")))
            if path == "/api/text-service/status":
                return self.send_json(text_service_status())
            if path == "/api/audio-service/status":
                return self.send_json(audio_service_status())
            if path == "/api/fusion-config":
                return self.send_json(fusion_config())
            if path == "/api/rules":
                return self.send_json(api_rules(qs))
            if path == "/api/reviews":
                return self.send_json(api_reviews(qs))
            if path == "/api/push":
                return self.send_json(api_push(qs))
            return self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/image-detector/analyze":
                payload = self.body_multipart_image()
                try:
                    return self.send_json(vision_detect_image(**payload))
                except Exception as exc:
                    result = yolo_detect_image(**payload)
                    result["service_mode"] = "local-yolo-fallback"
                    result["vision_service_error"] = str(exc)
                    return self.send_json(result)
            if path in {"/api/audio-service/infer-audio", "/api/audio-service/infer-video-audio"}:
                payload = self.body_multipart_file()
                service_path = "/infer/audio" if path.endswith("infer-audio") else "/infer/video-audio"
                fields = {"save_evidence": payload["save_evidence"]}
                if payload["content_id"]:
                    fields["content_id"] = payload["content_id"]
                return self.send_json(service_post_file(AUDIO_SERVICE_URL, service_path, payload["file"], fields))
            payload = self.body_json()
            if path == "/api/text-service/infer-text":
                return self.send_json(merge_business_text_rules(payload, service_post_json(TEXT_SERVICE_URL, "/infer/text", payload)))
            if path == "/api/text-service/infer-content":
                return self.send_json(service_post_json(TEXT_SERVICE_URL, "/infer/content", payload))
            if path == "/api/contents":
                return self.send_json(api_create_content(payload), 201)
            if m := re.match(r"^/api/contents/([^/]+)/recognize$", path):
                detail = recognize_content(m.group(1))
                return self.send_json(detail or {"error": "not found"}, 200 if detail else 404)
            if path == "/api/rules":
                return self.send_json(api_create_rule(payload), 201)
            if m := re.match(r"^/api/contents/([^/]+)/review$", path):
                return self.send_json(api_review(m.group(1), payload))
            if m := re.match(r"^/api/contents/([^/]+)/push-queue$", path):
                return self.send_json(api_create_push(m.group(1)), 201)
            if m := re.match(r"^/api/push/([^/]+)/send$", path):
                return self.send_json(api_send_push(m.group(1)))
            if path == "/api/mock/text/analyze":
                return self.send_json(analyze_text(payload))
            if path == "/api/mock/image/analyze":
                return self.send_json(analyze_image(payload))
            if path == "/api/mock/audio/analyze":
                return self.send_json(analyze_audio(payload))
            if path == "/api/mock/fusion/analyze":
                return self.send_json(analyze_fusion(payload))
            if path == "/api/mock/regulatory-platform/push":
                return self.send_json(mock_regulatory_push())
            return self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_PUT(self):
        path = urlparse(self.path).path
        try:
            payload = self.body_json()
            if m := re.match(r"^/api/contents/([^/]+)$", path):
                return self.send_json(api_update_content(m.group(1), payload))
            if m := re.match(r"^/api/models/([^/]+)$", path):
                return self.send_json(api_update_model(m.group(1), payload))
            if path == "/api/fusion-config":
                return self.send_json(api_update_fusion(payload))
            if m := re.match(r"^/api/rules/([^/]+)$", path):
                return self.send_json(api_update_rule(m.group(1), payload))
            return self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            if m := re.match(r"^/api/contents/([^/]+)$", path):
                with db() as conn:
                    conn.execute("DELETE FROM content_items WHERE id=?", (m.group(1),))
                    conn.execute("DELETE FROM recognition_results WHERE content_id=?", (m.group(1),))
                return self.send_json({"success": True})
            if m := re.match(r"^/api/rules/([^/]+)$", path):
                with db() as conn:
                    conn.execute("DELETE FROM rule_words WHERE id=?", (m.group(1),))
                return self.send_json({"success": True})
            return self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)


def api_dashboard():
    with db() as conn:
        contents = rows_to_list(conn.execute("SELECT * FROM content_items").fetchall())
        pushes = rows_to_list(conn.execute("SELECT * FROM push_logs").fetchall())
        platform_rows = rows_to_list(conn.execute("SELECT platform name, COUNT(*) value FROM content_items GROUP BY platform").fetchall())
        risk_rows = rows_to_list(conn.execute("SELECT risk_level name, COUNT(*) value FROM content_items GROUP BY risk_level").fetchall())
        modality_rows = rows_to_list(conn.execute("SELECT model_type name, COUNT(*) value FROM recognition_results WHERE risk_score>=0.65 GROUP BY model_type").fetchall())
    today = datetime.now().strftime("%Y-%m-%d")
    trend = []
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%m-%d")
        trend.append({"name": day, "value": random.randint(4, 18)})
    return {
        "cards": {
            "今日采集内容数": sum(1 for c in contents if c["collect_time"].startswith(today)) or len(contents),
            "已完成识别数": sum(1 for c in contents if c["recognize_status"] == "completed"),
            "高风险线索数": sum(1 for c in contents if c["risk_level"] == "高风险"),
            "待人工审核数": sum(1 for c in contents if c["review_status"] == "pending"),
            "已确认线索数": sum(1 for c in contents if c["review_status"] == "confirmed"),
            "推送成功数": sum(1 for p in pushes if p["push_status"] == "success"),
        },
        "platforms": platform_rows,
        "risks": risk_rows,
        "modalities": modality_rows,
        "trend": trend,
    }


def api_contents(qs):
    sql = "SELECT * FROM content_items WHERE 1=1"
    args = []
    for field in ["platform", "content_type", "recognize_status", "risk_level", "review_status"]:
        if qs.get(field):
            sql += f" AND {field}=?"
            args.append(qs[field])
    if qs.get("keyword"):
        sql += " AND (title LIKE ? OR raw_text LIKE ? OR account_name LIKE ?)"
        kw = f"%{qs['keyword']}%"
        args.extend([kw, kw, kw])
    sql += " ORDER BY collect_time DESC"
    with db() as conn:
        return rows_to_list(conn.execute(sql, args).fetchall())


def api_create_content(payload):
    cid = payload.get("id") or new_id("C")
    t = now()
    with db() as conn:
        conn.execute(
            """INSERT INTO content_items
            (id,platform,content_type,title,account_name,account_url,content_url,raw_text,media_url,publish_time,collect_time,recognize_status,risk_score,risk_level,review_status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (cid, payload.get("platform", "抖音"), payload.get("content_type", "文本"), payload.get("title", "未命名内容"), payload.get("account_name", "未知账号"), payload.get("account_url", ""), payload.get("content_url", ""), payload.get("raw_text", ""), payload.get("media_url", ""), payload.get("publish_time", t), payload.get("collect_time", t), "pending", 0, "无风险", "unreviewed", t, t),
        )
    return get_content_detail(cid)["content"]


def api_update_content(content_id, payload):
    fields = ["platform", "content_type", "title", "account_name", "account_url", "content_url", "raw_text", "media_url", "publish_time", "collect_time"]
    sets = [f"{f}=?" for f in fields if f in payload]
    args = [payload[f] for f in fields if f in payload]
    if not sets:
        return get_content_detail(content_id)["content"]
    sets.append("updated_at=?")
    args.extend([now(), content_id])
    with db() as conn:
        conn.execute(f"UPDATE content_items SET {','.join(sets)} WHERE id=?", args)
    return get_content_detail(content_id)["content"]


def api_update_model(model_id, payload):
    fields = ["model_name", "model_type", "model_version", "endpoint", "threshold", "timeout", "enabled", "description"]
    sets = [f"{f}=?" for f in fields if f in payload]
    args = [int(payload[f]) if f == "enabled" else payload[f] for f in fields if f in payload]
    args.append(model_id)
    with db() as conn:
        conn.execute(f"UPDATE model_configs SET {','.join(sets)} WHERE id=?", args)
        return row_to_dict(conn.execute("SELECT * FROM model_configs WHERE id=?", (model_id,)).fetchone())


def api_update_fusion(payload):
    fields = ["text_weight", "image_weight", "audio_weight", "account_weight", "high_risk_threshold", "medium_risk_threshold", "low_risk_threshold"]
    args = [float(payload.get(f, fusion_config()[f])) for f in fields]
    with db() as conn:
        conn.execute("UPDATE fusion_config SET text_weight=?,image_weight=?,audio_weight=?,account_weight=?,high_risk_threshold=?,medium_risk_threshold=?,low_risk_threshold=? WHERE id=1", args)
    return fusion_config()


def api_rules(qs):
    sql = "SELECT * FROM rule_words WHERE 1=1"
    args = []
    if qs.get("rule_type"):
        sql += " AND rule_type=?"
        args.append(qs["rule_type"])
    sql += " ORDER BY rule_type, created_at DESC"
    with db() as conn:
        return rows_to_list(conn.execute(sql, args).fetchall())


def api_create_rule(payload):
    rid = new_id("RW")
    with db() as conn:
        conn.execute(
            "INSERT INTO rule_words VALUES (?,?,?,?,?,?,?)",
            (rid, payload.get("rule_type", "keyword"), payload.get("word", ""), float(payload.get("risk_weight", 0.1)), int(payload.get("enabled", 1)), payload.get("remark", ""), now()),
        )
        return row_to_dict(conn.execute("SELECT * FROM rule_words WHERE id=?", (rid,)).fetchone())


def api_update_rule(rule_id, payload):
    fields = ["rule_type", "word", "risk_weight", "enabled", "remark"]
    sets = [f"{f}=?" for f in fields if f in payload]
    args = [int(payload[f]) if f == "enabled" else payload[f] for f in fields if f in payload]
    args.append(rule_id)
    with db() as conn:
        conn.execute(f"UPDATE rule_words SET {','.join(sets)} WHERE id=?", args)
        return row_to_dict(conn.execute("SELECT * FROM rule_words WHERE id=?", (rule_id,)).fetchone())


def api_reviews(qs):
    status = qs.get("review_status")
    sql = """SELECT c.id content_id,c.platform,c.title,c.risk_score,c.risk_level,c.review_status,
             rr.id review_id,rr.reviewer,rr.review_time,rr.review_opinion
             FROM content_items c LEFT JOIN review_records rr ON rr.content_id=c.id
             WHERE c.risk_level IN ('高风险','中风险')"""
    args = []
    if status:
        sql += " AND c.review_status=?"
        args.append(status)
    sql += " GROUP BY c.id ORDER BY c.risk_score DESC"
    with db() as conn:
        return rows_to_list(conn.execute(sql, args).fetchall())


def api_review(content_id, payload):
    status = payload.get("review_status", "confirmed")
    rid = new_id("REV")
    with db() as conn:
        conn.execute("INSERT INTO review_records VALUES (?,?,?,?,?,?)", (rid, content_id, status, payload.get("review_opinion", ""), payload.get("reviewer", "审核员"), now()))
        conn.execute("UPDATE content_items SET review_status=?, updated_at=? WHERE id=?", (status, now(), content_id))
        return row_to_dict(conn.execute("SELECT * FROM review_records WHERE id=?", (rid,)).fetchone())


def api_push(qs):
    with db() as conn:
        return rows_to_list(conn.execute("""SELECT p.*,c.title,c.platform,c.risk_level FROM push_logs p
            LEFT JOIN content_items c ON c.id=p.content_id ORDER BY COALESCE(p.push_time,''), p.id DESC""").fetchall())


def api_create_push(content_id):
    pid = new_id("P")
    with db() as conn:
        existing = conn.execute("SELECT * FROM push_logs WHERE content_id=? AND push_status IN ('waiting','retrying')", (content_id,)).fetchone()
        if existing:
            return row_to_dict(existing)
        conn.execute("INSERT INTO push_logs VALUES (?,?,?,?,?,?,?)", (pid, content_id, "", "waiting", "", 0, ""))
        return row_to_dict(conn.execute("SELECT * FROM push_logs WHERE id=?", (pid,)).fetchone())


def mock_regulatory_push():
    ok = random.random() > 0.22
    if ok:
        return {"success": True, "message": "推送成功", "report_id": f"R{datetime.now().strftime('%Y%m%d%H%M%S')}"}
    return {"success": False, "message": "接口超时，等待重试"}


def api_send_push(push_id):
    result = mock_regulatory_push()
    with db() as conn:
        row = row_to_dict(conn.execute("SELECT * FROM push_logs WHERE id=?", (push_id,)).fetchone())
        if not row:
            return {"error": "not found"}
        if result["success"]:
            conn.execute("UPDATE push_logs SET report_id=?,push_status='success',push_time=?,error_message='' WHERE id=?", (result["report_id"], now(), push_id))
        else:
            conn.execute("UPDATE push_logs SET push_status='failed',push_time=?,retry_count=retry_count+1,error_message=? WHERE id=?", (now(), result["message"], push_id))
        return row_to_dict(conn.execute("SELECT * FROM push_logs WHERE id=?", (push_id,)).fetchone())


def main():
    init_db()
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Demo server running: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
