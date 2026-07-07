#!/usr/bin/env python3
import base64
import csv
import http.client
import io
import json
import os
import random
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from email.message import Message as EmailMessage
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "demo.db"
RUNTIME_DIR = ROOT / ".runtime"
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
    "tobacco-yolo11s": {
        "name": "本地训练 / tobacco-yolo11s",
        "version": "yolo11s_small_v1-3/best.pt",
        "path": Path(os.environ.get("TOBACCO_MODEL_PATH", ROOT / "weights" / "best.pt")),
        "source_url": "",
        "description": "本地训练 YOLO11s 烟草检测，类别 cig_pack_or_carton（烟盒/条盒），训练 imgsz=1280，推理参数读 weights/args.yaml",
    },
}
DEFAULT_DETECTOR_MODEL_ID = os.environ.get("SMOKING_DETECTOR_MODEL", "basant-yolo26s")
VISION_SERVICE_URL = os.environ.get("VISION_SERVICE_URL", "http://127.0.0.1:9000")
TEXT_SERVICE_URL = os.environ.get("TEXT_SERVICE_URL", "http://127.0.0.1:8010")
AUDIO_SERVICE_URL = os.environ.get("AUDIO_SERVICE_URL", "http://127.0.0.1:8020")
AUTO_RECOGNIZE = os.environ.get("AUTO_RECOGNIZE", "true").strip().lower() not in {"0", "false", "no", "off"}
# 高风险账户反馈爬虫端：IP/端口可配置，默认指向内网爬虫服务
CRAWLER_RISK_API_BASE = os.environ.get("CRAWLER_RISK_API_BASE", "http://10.20.30.58:5001")
CRAWLER_RISK_API_PATH = os.environ.get("CRAWLER_RISK_API_PATH", "/api/internal/users/risk-score")
# 评论区用户判定为高风险的分数阈值。评论是比整帖更低的判定门槛：
# 售卖帖下的购买/交易/价格询问(怎么下单/多少钱/批发)即应上报，默认 0.65(中风险及以上)
COMMENT_HIGH_RISK_THRESHOLD = float(os.environ.get("COMMENT_HIGH_RISK_THRESHOLD", "0.65"))
# 账户二次确认：批次中高风险帖子数达此值即命中
SECONDARY_HIGH_POST_COUNT = int(os.environ.get("SECONDARY_HIGH_POST_COUNT", "2"))
# 账户二次确认：批次最高单帖综合分达此值即命中
SECONDARY_MAX_SCORE_THRESHOLD = float(os.environ.get("SECONDARY_MAX_SCORE_THRESHOLD", "0.85"))
# 账户二次确认：期望回推帖子数，仅用于日志/展示，不强校验
SECONDARY_EXPECTED_POSTS = int(os.environ.get("SECONDARY_EXPECTED_POSTS", "10"))
# 自动化审核反馈：识别为高风险的内容在识别完成后自动把风险账户反馈爬虫端，无需人工确认
AUTO_FEEDBACK_ON_RECOGNIZE = os.environ.get("AUTO_FEEDBACK_ON_RECOGNIZE", "true").strip().lower() not in {"0", "false", "no", "off"}
# 单条内容识别阶段最多给多少条评论打分（防止超大评论区拖垮识别队列）
COMMENT_SCORE_MAX = int(os.environ.get("COMMENT_SCORE_MAX", "100"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "200"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
_YOLO_MODELS = {}


class PayloadTooLarge(Exception):
    """请求体超过 MAX_UPLOAD_BYTES 上限。"""


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix):
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100, 999)}"


DB_BUSY_TIMEOUT_MS = int(os.environ.get("DB_BUSY_TIMEOUT_MS", "15000"))


def db():
    # timeout + busy_timeout：锁竞争时等待而非立即 "database is locked"
    conn = sqlite3.connect(DB_PATH, timeout=DB_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    # WAL：读不阻塞写、写不阻塞读，后台自动识别与审核/更新可并发，仅写-写串行
    conn.execute(f"PRAGMA busy_timeout={DB_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def row_to_dict(row):
    return dict(row) if row else None


def rows_to_list(rows):
    return [dict(row) for row in rows]


def table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def media_content_type(path):
    suffix = path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
    }.get(suffix, "application/octet-stream")


def local_media_token(path):
    encoded = base64.urlsafe_b64encode(str(path.resolve()).encode("utf-8")).decode("ascii").rstrip("=")
    return f"/media/local/{encoded}/{path.name}"


def decode_local_media_token(token):
    padding = "=" * (-len(token) % 4)
    try:
        return Path(base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8"))
    except Exception:
        return None


def local_media_allowed(path):
    try:
        resolved = path.resolve()
    except OSError:
        return False
    allowed_roots = [ROOT, Path("/tmp")]
    return resolved.exists() and resolved.is_file() and any(root == resolved or root in resolved.parents for root in allowed_roots)


def public_media_url(media_url):
    if not media_url:
        return ""
    parsed = urlparse(media_url)
    if parsed.scheme in {"http", "https"}:
        return media_url
    media_path = resolve_media_path(media_url)
    if media_path and local_media_allowed(media_path):
        return local_media_token(media_path)
    return media_url


CONTENT_ITEM_EXTRA_COLUMNS = {
    "crawler_type": "TEXT DEFAULT ''",
    "crawler_id": "TEXT DEFAULT ''",
    "author_json": "TEXT DEFAULT ''",
    "media_list": "TEXT DEFAULT ''",
    "raw_payload": "TEXT DEFAULT ''",
    "account_key": "TEXT DEFAULT ''",
    "confirm_batch_id": "TEXT DEFAULT ''",
}

# 评论在识别阶段结合帖子上下文打分后落库，审核时直接读取
CRAWLER_COMMENT_EXTRA_COLUMNS = {
    "risk_score": "REAL DEFAULT 0",
    "risk_level": "TEXT DEFAULT ''",
    "risk_updated_at": "TEXT DEFAULT ''",
}

LLM_TEXT_CONFIG_EXTRA_COLUMNS = {
    "llm_provider": "TEXT NOT NULL DEFAULT 'local'",
    "llm_api_base_url": "TEXT NOT NULL DEFAULT ''",
    "llm_api_key_env": "TEXT NOT NULL DEFAULT 'TEXT_LLM_API_KEY'",
    "llm_api_key": "TEXT NOT NULL DEFAULT ''",
    "llm_api_model": "TEXT NOT NULL DEFAULT ''",
}


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
  crawler_type TEXT DEFAULT '',
  crawler_id TEXT DEFAULT '',
  author_json TEXT DEFAULT '',
  media_list TEXT DEFAULT '',
  raw_payload TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS crawler_comments (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL,
  comment_type TEXT NOT NULL,
  parent_comment_id TEXT DEFAULT '',
  sender_json TEXT DEFAULT '',
  content TEXT DEFAULT '',
  date TEXT DEFAULT '',
  raw_payload TEXT DEFAULT '',
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

CREATE TABLE IF NOT EXISTS llm_text_config (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  semantic_engine TEXT NOT NULL,
  use_mock_model INTEGER NOT NULL,
  transformer_model_dir TEXT NOT NULL,
  llm_provider TEXT NOT NULL DEFAULT 'local',
  llm_model_dir TEXT NOT NULL,
  llm_api_base_url TEXT NOT NULL DEFAULT '',
  llm_api_key_env TEXT NOT NULL DEFAULT 'TEXT_LLM_API_KEY',
  llm_api_key TEXT NOT NULL DEFAULT '',
  llm_api_model TEXT NOT NULL DEFAULT '',
  llm_max_new_tokens INTEGER NOT NULL,
  llm_temperature REAL NOT NULL,
  llm_timeout_seconds INTEGER NOT NULL,
  max_text_length INTEGER NOT NULL,
  updated_at TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS accounts (
  account_key TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  user_id TEXT NOT NULL,
  nickname TEXT DEFAULT '',
  description TEXT DEFAULT '',
  avatar_url TEXT DEFAULT '',
  account_risk_score REAL DEFAULT 0,
  high_post_count INTEGER DEFAULT 0,
  max_post_score REAL DEFAULT 0,
  post_count INTEGER DEFAULT 0,
  confirm_status TEXT DEFAULT 'awaiting_posts',
  confirm_batch_id TEXT DEFAULT '',
  last_confirm_at TEXT DEFAULT '',
  violation_type TEXT DEFAULT '',
  report_path TEXT DEFAULT '',
  reviewer TEXT DEFAULT '',
  review_opinion TEXT DEFAULT '',
  review_time TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
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
    ("keyword", "下单", 0.24, "下单交易表达"),
    ("keyword", "购买", 0.24, "购买交易表达"),
    ("keyword", "怎么买", 0.24, "购买交易表达"),
    ("keyword", "怎么卖", 0.24, "售卖交易表达"),
    ("keyword", "怎卖", 0.22, "售卖交易表达"),
    ("keyword", "买货", 0.24, "购买交易表达"),
    ("keyword", "怎么联系", 0.22, "联系方式引导"),
    ("keyword", "多少钱", 0.22, "询价表达"),
    ("keyword", "有货", 0.24, "现货表达"),
    ("keyword", "到货", 0.20, "到货表达"),
    ("keyword", "一条", 0.24, "计量交易词"),
    ("keyword", "一盒", 0.22, "计量交易词"),
    ("keyword", "一箱", 0.22, "计量交易词"),
    ("keyword", "十盒", 0.20, "计量交易词"),
    ("keyword", "面交", 0.20, "线下交易词"),
    ("keyword", "私信", 0.18, "引流词"),
    ("keyword", "刚到一批", 0.26, "到货交易表达"),
    ("keyword", "烟管", 0.12, "烟草相关商品词"),
    ("keyword", "空烟管", 0.16, "烟草相关商品词"),
    ("keyword", "空心管", 0.16, "烟草相关商品词"),
    ("keyword", "空管", 0.12, "烟草相关商品词"),
    ("keyword", "厂家直销", 0.18, "批发售卖表达"),
    ("keyword", "批发", 0.18, "批量售卖表达"),
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
        existing_columns = table_columns(conn, "content_items")
        for column, definition in CONTENT_ITEM_EXTRA_COLUMNS.items():
            if column not in existing_columns:
                conn.execute(f"ALTER TABLE content_items ADD COLUMN {column} {definition}")
        existing_llm_columns = table_columns(conn, "llm_text_config")
        for column, definition in LLM_TEXT_CONFIG_EXTRA_COLUMNS.items():
            if column not in existing_llm_columns:
                conn.execute(f"ALTER TABLE llm_text_config ADD COLUMN {column} {definition}")
        existing_comment_columns = table_columns(conn, "crawler_comments")
        for column, definition in CRAWLER_COMMENT_EXTRA_COLUMNS.items():
            if column not in existing_comment_columns:
                conn.execute(f"ALTER TABLE crawler_comments ADD COLUMN {column} {definition}")
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
        if conn.execute("SELECT COUNT(*) FROM llm_text_config").fetchone()[0] == 0:
            conn.execute(
                """INSERT INTO llm_text_config
                   (id, semantic_engine, use_mock_model, transformer_model_dir, llm_provider, llm_model_dir,
                    llm_api_base_url, llm_api_key_env, llm_api_key, llm_api_model, llm_max_new_tokens,
                    llm_temperature, llm_timeout_seconds, max_text_length, updated_at)
                   VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    os.environ.get("TEXT_SEMANTIC_ENGINE", "mock"),
                    1 if os.environ.get("TEXT_USE_MOCK_MODEL", "true").lower() in {"1", "true", "yes", "on"} else 0,
                    os.environ.get("TEXT_MODEL_DIR", "text_models/text-risk-model"),
                    os.environ.get("TEXT_LLM_PROVIDER", "local"),
                    os.environ.get("TEXT_LLM_MODEL_DIR", "text_models/qwen2.5-0.5b-instruct"),
                    os.environ.get("TEXT_LLM_API_BASE_URL", ""),
                    os.environ.get("TEXT_LLM_API_KEY_ENV", "TEXT_LLM_API_KEY"),
                    os.environ.get(os.environ.get("TEXT_LLM_API_KEY_ENV", "TEXT_LLM_API_KEY"), ""),
                    os.environ.get("TEXT_LLM_API_MODEL", ""),
                    int(os.environ.get("TEXT_LLM_MAX_NEW_TOKENS", "256")),
                    float(os.environ.get("TEXT_LLM_TEMPERATURE", "0.0")),
                    int(os.environ.get("TEXT_LLM_TIMEOUT_SECONDS", "10")),
                    int(os.environ.get("TEXT_MAX_TEXT_LENGTH", "512")),
                    now(),
                ),
            )
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
    hit_words = {r["word"] for r in hits + black + brands}
    product_words = {"烟管", "空烟管", "空心管", "空管"}
    inquiry_words = {"多少钱", "下单", "购买", "怎么买", "怎么卖", "怎卖", "买货", "怎么联系"}
    quantity_words = {"一条", "一盒", "一箱", "十盒"}
    lead_words = {"私聊", "私信", "有货", "到货", "刚到一批", "面交", "厂家直销", "批发"}
    score = 0.10 + sum(r["risk_weight"] for r in hits + black + brands) + sum(r["risk_weight"] for r in whitelist)
    if hit_words & product_words and hit_words & (inquiry_words | quantity_words):
        score = max(score, 0.82)
    elif hit_words & inquiry_words and hit_words & quantity_words:
        score = max(score, 0.76)
    elif hit_words & product_words and hit_words & lead_words:
        score = max(score, 0.72)
    elif len((hit_words & inquiry_words) | (hit_words & quantity_words) | (hit_words & lead_words)) >= 2:
        score = max(score, 0.70)
    if len(hit_words) >= 4:
        score = max(score, 0.86)
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
        "ready": True,
        "real_model_ready": not bool(detector.get("mock", True)),
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


def build_content_text_payload(content):
    author = json_loads(content.get("author_json"), {}) or {}
    return {
        "content_id": content["id"],
        "platform": content["platform"],
        "title": content["title"] or "",
        "description": content["raw_text"] or "",
        "account_name": content["account_name"] or "",
        "account_bio": author.get("description", ""),
        "comments": content_comment_texts(content["id"]) or ([content["raw_text"]] if content["content_type"] == "评论" and content["raw_text"] else []),
        "ocr_texts": [],
        "asr_texts": [],
        "content_url": content["content_url"] or "",
    }


def text_payload_text(payload):
    parts = [
        payload.get("title"),
        payload.get("description"),
        payload.get("account_name"),
        payload.get("account_bio"),
        *(payload.get("comments") or []),
        *(payload.get("ocr_texts") or []),
        *(payload.get("asr_texts") or []),
    ]
    return " ".join(str(item).strip() for item in parts if item and str(item).strip())


def text_service_analyze_content(content):
    payload = build_content_text_payload(content)
    result = service_post_json(TEXT_SERVICE_URL, "/infer/content", payload)
    result = merge_business_text_rules({"text": text_payload_text(payload)}, result)
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
    annotated_image = ""
    if evidence and isinstance(evidence[0], dict):
        image_path = evidence[0].get("image_path") or ""
        annotated_image = "/" + image_path.lstrip("/") if image_path and not image_path.startswith("data:") else image_path
    return {
        "detected": bool(detections),
        "confidence": max([item["confidence"] for item in detections], default=0),
        "image_risk_score": float(visual_result.get("visual_score") or 0),
        "detected_objects": [item["class_name"] for item in detections],
        "detections": detections,
        "annotated_image": annotated_image,
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


def mask_secret(value):
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def llm_text_config(include_secret=False):
    with db() as conn:
        cfg = row_to_dict(conn.execute("SELECT * FROM llm_text_config WHERE id=1").fetchone())
    if cfg and not include_secret:
        api_key = cfg.pop("llm_api_key", "") or ""
        cfg["llm_api_key_set"] = bool(api_key)
        cfg["llm_api_key_masked"] = mask_secret(api_key)
    env = {
        "TEXT_SEMANTIC_ENGINE": os.environ.get("TEXT_SEMANTIC_ENGINE", "mock"),
        "TEXT_USE_MOCK_MODEL": os.environ.get("TEXT_USE_MOCK_MODEL", "true"),
        "TEXT_MODEL_DIR": os.environ.get("TEXT_MODEL_DIR", "text_models/text-risk-model"),
        "TEXT_LLM_PROVIDER": os.environ.get("TEXT_LLM_PROVIDER", "local"),
        "TEXT_LLM_MODEL_DIR": os.environ.get("TEXT_LLM_MODEL_DIR", "text_models/qwen2.5-0.5b-instruct"),
        "TEXT_LLM_API_BASE_URL": os.environ.get("TEXT_LLM_API_BASE_URL", ""),
        "TEXT_LLM_API_KEY": mask_secret(os.environ.get(os.environ.get("TEXT_LLM_API_KEY_ENV", "TEXT_LLM_API_KEY"), "")),
        "TEXT_LLM_API_MODEL": os.environ.get("TEXT_LLM_API_MODEL", ""),
        "TEXT_LLM_MAX_NEW_TOKENS": os.environ.get("TEXT_LLM_MAX_NEW_TOKENS", "256"),
        "TEXT_LLM_TEMPERATURE": os.environ.get("TEXT_LLM_TEMPERATURE", "0.0"),
        "TEXT_LLM_TIMEOUT_SECONDS": os.environ.get("TEXT_LLM_TIMEOUT_SECONDS", "10"),
        "TEXT_MAX_TEXT_LENGTH": os.environ.get("TEXT_MAX_TEXT_LENGTH", "512"),
    }
    return {"saved": cfg, "runtime_env": env, "text_service_url": TEXT_SERVICE_URL}


def api_update_llm_text_config(payload):
    semantic_engine = str(payload.get("semantic_engine") or "mock").lower()
    if semantic_engine not in {"mock", "transformers", "llm"}:
        raise ValueError("semantic_engine must be mock, transformers or llm")
    use_mock_model = 1 if bool(payload.get("use_mock_model")) else 0
    transformer_model_dir = str(payload.get("transformer_model_dir") or "text_models/text-risk-model").strip()
    llm_provider = str(payload.get("llm_provider") or "local").lower()
    if llm_provider not in {"local", "openai_compatible"}:
        raise ValueError("llm_provider must be local or openai_compatible")
    llm_model_dir = str(payload.get("llm_model_dir") or "text_models/qwen2.5-0.5b-instruct").strip()
    llm_api_base_url = str(payload.get("llm_api_base_url") or "").strip()
    llm_api_key_env = str(payload.get("llm_api_key_env") or "TEXT_LLM_API_KEY").strip()
    llm_api_key = str(payload.get("llm_api_key") or "").strip()
    llm_api_model = str(payload.get("llm_api_model") or "").strip()
    llm_max_new_tokens = max(1, min(2048, int(payload.get("llm_max_new_tokens") or 256)))
    llm_temperature = max(0.0, min(2.0, float(payload.get("llm_temperature") or 0.0)))
    llm_timeout_seconds = max(1, min(600, int(payload.get("llm_timeout_seconds") or 10)))
    max_text_length = max(64, min(8192, int(payload.get("max_text_length") or 512)))
    with db() as conn:
        conn.execute(
            """UPDATE llm_text_config
               SET semantic_engine=?, use_mock_model=?, transformer_model_dir=?, llm_provider=?, llm_model_dir=?,
                   llm_api_base_url=?, llm_api_key_env=?, llm_api_model=?,
                   llm_max_new_tokens=?, llm_temperature=?, llm_timeout_seconds=?, max_text_length=?, updated_at=?
               WHERE id=1""",
            (
                semantic_engine,
                use_mock_model,
                transformer_model_dir,
                llm_provider,
                llm_model_dir,
                llm_api_base_url,
                llm_api_key_env,
                llm_api_model,
                llm_max_new_tokens,
                llm_temperature,
                llm_timeout_seconds,
                max_text_length,
                now(),
            ),
        )
        if llm_api_key:
            conn.execute("UPDATE llm_text_config SET llm_api_key=?, updated_at=? WHERE id=1", (llm_api_key, now()))
    return llm_text_config()


def llm_chat_completions_target(base_url):
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API Base URL must be a valid http/https URL")
    base_path = parsed.path.rstrip("/")
    target = base_path if base_path.endswith("/chat/completions") else f"{base_path}/chat/completions"
    if not target.startswith("/"):
        target = f"/{target}"
    return parsed, target


def api_llm_health_check(payload):
    cfg = llm_text_config(include_secret=True).get("saved") or {}
    merged = {**cfg, **(payload or {})}
    provider = str(merged.get("llm_provider") or "local").lower()
    if provider != "openai_compatible":
        return {
            "ok": False,
            "provider": provider,
            "message": "仅第三方 API 模式需要健康检查，请将 LLM 来源设为 openai_compatible。",
        }
    base_url = str(merged.get("llm_api_base_url") or "").strip()
    model = str(merged.get("llm_api_model") or "").strip()
    key_env = str(merged.get("llm_api_key_env") or "TEXT_LLM_API_KEY").strip()
    request_api_key = str((payload or {}).get("llm_api_key") or "").strip()
    saved_api_key = str(cfg.get("llm_api_key") or "").strip()
    api_key = request_api_key or saved_api_key or os.environ.get(key_env, "")
    api_key_source = "page_input" if request_api_key else "saved_config" if saved_api_key else "environment"
    timeout = max(1, min(60, int(merged.get("llm_timeout_seconds") or 10)))
    if not base_url or not model:
        return {"ok": False, "provider": provider, "message": "请填写 API Base URL 和 API 模型名。"}
    if not api_key:
        return {
            "ok": False,
            "provider": provider,
            "endpoint": base_url,
            "model": model,
            "api_key_env": key_env,
            "api_key_present": False,
            "api_key_source": api_key_source,
            "message": "API Key 未填写或保存，无法调用第三方 API。",
        }
    parsed, target = llm_chat_completions_target(base_url)
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "health check"}],
            "temperature": 0,
            "max_tokens": 8,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    start = datetime.now()
    conn = conn_cls(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), timeout=timeout)
    try:
        conn.request("POST", target, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        latency_ms = int((datetime.now() - start).total_seconds() * 1000)
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        if resp.status >= 400:
            error_payload = data.get("error") if isinstance(data, dict) else None
            message = error_payload.get("message") if isinstance(error_payload, dict) else error_payload
            return {
                "ok": False,
                "provider": provider,
                "endpoint": f"{parsed.scheme}://{parsed.netloc}{target}",
                "model": model,
                "status_code": resp.status,
                "latency_ms": latency_ms,
                "api_key_env": key_env,
                "api_key_present": True,
                "api_key_source": api_key_source,
                "message": message or raw[:300] or f"HTTP {resp.status}",
            }
        choices = data.get("choices") if isinstance(data, dict) else None
        content = ""
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            content = str(message.get("content") or "") if isinstance(message, dict) else str(choices[0].get("text") or "")
        return {
            "ok": True,
            "provider": provider,
            "endpoint": f"{parsed.scheme}://{parsed.netloc}{target}",
            "model": model,
            "status_code": resp.status,
            "latency_ms": latency_ms,
            "api_key_env": key_env,
            "api_key_present": True,
            "api_key_source": api_key_source,
            "response_preview": content[:120],
            "message": "第三方 API 连接正常。",
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "endpoint": base_url,
            "model": model,
            "api_key_env": key_env,
            "api_key_present": True,
            "api_key_source": api_key_source,
            "message": str(exc),
        }
    finally:
        conn.close()


def text_service_port():
    parsed = urlparse(TEXT_SERVICE_URL)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def text_service_env_from_config(cfg):
    env = os.environ.copy()
    api_key = cfg.get("llm_api_key") or env.get("TEXT_LLM_API_KEY", "")
    env.update(
        {
            "TEXT_SEMANTIC_ENGINE": str(cfg.get("semantic_engine") or "mock"),
            "TEXT_USE_MOCK_MODEL": "true" if int(cfg.get("use_mock_model") or 0) else "false",
            "TEXT_MODEL_DIR": str(cfg.get("transformer_model_dir") or "text_models/text-risk-model"),
            "TEXT_LLM_PROVIDER": str(cfg.get("llm_provider") or "local"),
            "TEXT_LLM_MODEL_DIR": str(cfg.get("llm_model_dir") or "text_models/qwen2.5-0.5b-instruct"),
            "TEXT_LLM_API_BASE_URL": str(cfg.get("llm_api_base_url") or ""),
            "TEXT_LLM_API_KEY_ENV": "TEXT_LLM_API_KEY",
            "TEXT_LLM_API_MODEL": str(cfg.get("llm_api_model") or ""),
            "TEXT_LLM_MAX_NEW_TOKENS": str(cfg.get("llm_max_new_tokens") or 256),
            "TEXT_LLM_TEMPERATURE": str(cfg.get("llm_temperature") or 0.0),
            "TEXT_LLM_TIMEOUT_SECONDS": str(cfg.get("llm_timeout_seconds") or 10),
            "TEXT_MAX_TEXT_LENGTH": str(cfg.get("max_text_length") or 512),
            "TEXT_PORT": str(text_service_port()),
        }
    )
    if api_key:
        env["TEXT_LLM_API_KEY"] = api_key
    return env


def listening_pids_on_port(port):
    try:
        output = subprocess.check_output(["ss", "-ltnp"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    pids = []
    for line in output.splitlines():
        if f":{port} " not in line:
            continue
        for pid in re.findall(r"pid=(\d+)", line):
            value = int(pid)
            if value != os.getpid() and value not in pids:
                pids.append(value)
    return pids


def stop_processes(pids):
    stopped = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            stopped.append(pid)
        except ProcessLookupError:
            continue
    deadline = time.time() + 3
    while time.time() < deadline:
        alive = []
        for pid in stopped:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                continue
        if not alive:
            return stopped
        time.sleep(0.1)
    for pid in stopped:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return stopped


def api_apply_text_service_config(payload):
    api_update_llm_text_config(payload or {})
    cfg = llm_text_config(include_secret=True).get("saved") or {}
    port = text_service_port()
    old_pids = listening_pids_on_port(port)
    stopped = stop_processes(old_pids)
    env = text_service_env_from_config(cfg)
    RUNTIME_DIR.mkdir(exist_ok=True)
    log_file = RUNTIME_DIR / "text.log"
    log_handle = log_file.open("ab")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "text_service.main:app", "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(ROOT),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_handle.close()
    (RUNTIME_DIR / "text.pid").write_text(str(proc.pid), encoding="utf-8")
    time.sleep(1.0)
    status = None
    error = ""
    try:
        status = text_service_status()
    except Exception as exc:
        error = str(exc)
    return {
        "success": bool(status),
        "message": "文本服务已按当前配置重启。" if status else "文本服务重启已发起，但状态检查失败。",
        "port": port,
        "stopped_pids": stopped,
        "started_pid": proc.pid,
        "status": status,
        "error": error,
        "applied": {
            "semantic_engine": env.get("TEXT_SEMANTIC_ENGINE"),
            "llm_provider": env.get("TEXT_LLM_PROVIDER"),
            "llm_api_base_url": env.get("TEXT_LLM_API_BASE_URL"),
            "llm_api_model": env.get("TEXT_LLM_API_MODEL"),
            "llm_api_key_set": bool(env.get("TEXT_LLM_API_KEY")),
        },
    }


def analyze_fusion(payload):
    cfg = fusion_config()
    text_score = float(payload.get("text_risk_score") or 0)
    image_score = float(payload.get("image_risk_score") or 0)
    audio_score = float(payload.get("audio_risk_score") or 0)
    modalities = [
        ("文本", text_score, bool(payload.get("text_available", True)), "文本交易引流"),
        ("图像", image_score, bool(payload.get("image_available", image_score > 0)), "图像疑似售烟"),
        ("语音", audio_score, bool(payload.get("audio_available", audio_score > 0)), "语音交易暗示"),
    ]
    available_modalities = [(name, value) for name, value, available, _ in modalities if available]
    if len(available_modalities) <= 1:
        # 单模态内容(如评论/纯文本)：直接采用该模态风险分，不做模态加权、不计账号权重
        score = available_modalities[0][1] if available_modalities else 0.0
    else:
        score = (
            text_score * cfg["text_weight"]
            + image_score * cfg["image_weight"]
            + audio_score * cfg["audio_weight"]
            + float(payload.get("account_risk_score") or 0) * cfg["account_weight"]
        )
    available_scores = [value for _, value, available, _ in modalities if available]
    strongest_modality = max(available_scores, default=0)
    if strongest_modality >= cfg["high_risk_threshold"]:
        evidence_level = "高风险"
    elif strongest_modality >= cfg["medium_risk_threshold"]:
        evidence_level = "中风险"
    elif strongest_modality >= cfg["low_risk_threshold"]:
        evidence_level = "低风险"
    else:
        evidence_level = "无风险"
    effective_score = max(score, strongest_modality)
    if strongest_modality >= cfg["high_risk_threshold"] or score >= cfg["high_risk_threshold"]:
        level = "高风险"
    elif strongest_modality >= cfg["medium_risk_threshold"] or score >= cfg["medium_risk_threshold"]:
        level = "中风险"
    elif strongest_modality >= cfg["low_risk_threshold"] or score >= cfg["low_risk_threshold"]:
        level = "低风险"
    else:
        level = "无风险"
    violation = [label for _, value, available, label in modalities if available and value >= cfg["medium_risk_threshold"]]
    hit_modalities = [name for name, value, available, _ in modalities if available and value >= cfg["medium_risk_threshold"]]
    missing_modalities = [name for name, _, available, _ in modalities if not available]
    low_modalities = [name for name, value, available, _ in modalities if available and value > 0 and value < cfg["low_risk_threshold"]]
    if violation:
        explanation = "、".join(hit_modalities) + "单模态证据已达到风险阈值，融合结果按强证据优先判定；缺失或低分模态不参与降权。"
    elif score >= cfg["low_risk_threshold"]:
        explanation = "多模态弱证据累计达到风险阈值，建议结合上下文复核。"
    else:
        explanation = "当前可用模态未触发主要违法售烟特征。"
    return {
        "risk_score": round(effective_score, 2),
        "weighted_score": round(score, 2),
        "strongest_modality_score": round(strongest_modality, 2),
        "evidence_level": evidence_level,
        "risk_level": level,
        "violation_type": violation or ["未发现明显违规"],
        "hit_modalities": hit_modalities,
        "missing_modalities": missing_modalities,
        "low_confidence_modalities": low_modalities,
        "model_explanation": explanation,
        "review_suggestion": "建议人工复核后推送监管平台。" if level in {"高风险", "中风险"} else "建议归档观察。",
        "model_version": "fusion-risk-v1.0",
    }


def comment_score_to_level(score):
    if score >= 0.85:
        return "high"
    if score >= 0.65:
        return "medium"
    if score >= 0.40:
        return "low"
    return "none"


def score_content_comments(content):
    """识别阶段：结合帖子上下文，对评论区(一级 comment + 二级 sub_comment)逐条打分。
    返回 {comment_db_id: (risk_score, risk_level)}；不占用数据库连接（在识别阶段调用）。"""
    content_id = content["id"]
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT id, content FROM crawler_comments WHERE content_id=? AND content<>'' ORDER BY date, id LIMIT ?",
            (content_id, COMMENT_SCORE_MAX),
        ).fetchall())
    if not rows:
        return {}
    post_context = " ".join(
        str(x).strip() for x in [content.get("title"), content.get("raw_text")] if x and str(x).strip()
    )[:300]
    scores = {}
    # 优先走文本服务批量(LLM，带帖子上下文)；失败回退本地规则（仅评论本身）
    try:
        items = [{"content_id": r["id"], "source": "comment", "text": r["content"], "context": post_context} for r in rows]
        resp = service_post_json(TEXT_SERVICE_URL, "/infer/batch", {"items": items}, timeout=max(120, len(items) * 8))
        for it in resp.get("items", []):
            s = float(it.get("text_score") or 0)
            scores[it.get("content_id")] = (round(s, 4), str(it.get("risk_level") or comment_score_to_level(s)))
    except Exception as exc:
        sys.stderr.write("[comment-score] 批量评分失败，回退本地规则: %s\n" % exc)
        for r in rows:
            s = float(analyze_text({"text": r["content"]}).get("text_risk_score") or 0)
            scores[r["id"]] = (round(s, 4), comment_score_to_level(s))
    return scores


def recognize_content(content_id):
    # 1) 读取阶段：仅短读，立即释放连接
    with db() as conn:
        content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone())
    if not content:
        return None
    # 2) 识别阶段：耗时的文本/图像/语音模型调用，全程不占用数据库连接/写锁
    try:
        text_result = text_service_analyze_content(content)
    except Exception as exc:
        text_result = analyze_text({"content_id": content_id, "text": text_payload_text(build_content_text_payload(content))})
        text_result["service_mode"] = "local-text-fallback"
        text_result["text_service_error"] = str(exc)
    image_score = 0
    audio_score = 0
    image_result = None
    audio_result = None
    media_path = resolve_media_path(content["media_url"])
    media_ext = media_path.suffix.lower() if media_path else ""
    is_visual_media = content["content_type"] in {"图片", "视频"} or media_ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv"}
    is_audio_media = content["content_type"] in {"音频", "视频"} or media_ext in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".avi", ".mkv"}
    if is_visual_media:
        image_result = analyze_image_with_vision({"content_id": content_id, "image_url": content["media_url"], "media_type": "video" if content["content_type"] == "视频" else "image"})
        image_score = image_result["image_risk_score"]
    if is_audio_media and media_path:
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
        "text_available": True,
        "image_available": image_result is not None,
        "audio_available": audio_result is not None,
        "account_risk_score": account_score,
    })
    # 评论区结合帖子上下文逐条打分（仍在识别阶段，不占用数据库连接）
    comment_scores = score_content_comments(content)
    # 3) 写入阶段：仅短写事务（删旧结果+写结果+更新内容+落库评论分），写锁占用极短
    with db() as conn:
        # 保护：识别期间若已有人工审核结论，则不覆盖（事务内重读，兼顾边识别边审核）
        current = conn.execute("SELECT review_status FROM content_items WHERE id=?", (content_id,)).fetchone()
        prev_review = current["review_status"] if current else None
        if prev_review in REVIEWED_STATUSES:
            review_status = prev_review
        else:
            review_status = "pending" if fusion["risk_level"] in {"高风险", "中风险"} else "unreviewed"
        conn.execute("DELETE FROM recognition_results WHERE content_id=?", (content_id,))
        for comment_db_id, (c_score, c_level) in comment_scores.items():
            conn.execute(
                "UPDATE crawler_comments SET risk_score=?, risk_level=?, risk_updated_at=? WHERE id=?",
                (c_score, c_level, now(), comment_db_id),
            )
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
        conn.execute(
            "UPDATE content_items SET recognize_status='completed', risk_score=?, risk_level=?, review_status=?, updated_at=? WHERE id=?",
            (fusion["risk_score"], fusion["risk_level"], review_status, now(), content_id),
        )
    # 自动化审核反馈：高风险内容识别完成后自动反馈风险账户(发帖人+评论区高风险用户)到爬虫端
    if AUTO_FEEDBACK_ON_RECOGNIZE and fusion["risk_level"] == "高风险":
        content["risk_score"] = fusion["risk_score"]
        content["risk_level"] = fusion["risk_level"]
        try:
            feedback_high_risk_account(content)
            feedback_high_risk_comment_users(content)
        except Exception as exc:
            sys.stderr.write("[auto-feedback] %s 自动反馈失败: %s\n" % (content_id, exc))
    return get_content_detail(content_id)


_auto_recognize_event = threading.Event()
_auto_recognize_thread = None
_auto_recognize_thread_lock = threading.Lock()


def next_pending_content_id():
    """取下一条待识别内容：新内容(created_at 最新)优先，再回溯历史未识别数据。"""
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM content_items WHERE recognize_status='pending' "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
    return row["id"] if row else None


def drain_pending_recognition():
    """顺序识别所有待识别(pending)内容，直到队列清空。"""
    while True:
        content_id = next_pending_content_id()
        if not content_id:
            break
        try:
            recognize_content(content_id)
        except Exception as exc:
            # 单条失败不能阻塞队列；标记 failed 避免无限重复处理
            sys.stderr.write("[auto-recognize] %s 识别失败: %s\n" % (content_id, exc))
            try:
                with db() as conn:
                    conn.execute(
                        "UPDATE content_items SET recognize_status='failed', updated_at=? WHERE id=?",
                        (now(), content_id),
                    )
            except Exception:
                pass


def _auto_recognize_loop():
    while True:
        _auto_recognize_event.wait()
        _auto_recognize_event.clear()
        drain_pending_recognition()


def trigger_auto_recognize():
    """触发后台顺序识别：自动识别新内容，并依次清空历史未识别(pending)队列。"""
    if not AUTO_RECOGNIZE:
        return
    global _auto_recognize_thread
    with _auto_recognize_thread_lock:
        if _auto_recognize_thread is None or not _auto_recognize_thread.is_alive():
            _auto_recognize_thread = threading.Thread(
                target=_auto_recognize_loop, name="auto-recognize", daemon=True
            )
            _auto_recognize_thread.start()
    _auto_recognize_event.set()


# 人工已处置的审核状态，重识别时保留，避免清空人工结论
REVIEWED_STATUSES = {"confirmed", "false_positive", "observing", "ignored"}
_rerecognize_lock = threading.Lock()
_rerecognize_thread = None
_rerecognize_state = {"running": False, "total": 0, "done": 0, "failed": 0, "started_at": "", "finished_at": ""}


def _rerecognize_all_worker():
    """后台重新识别所有内容：刷新帖子风险与评论风险分；保留已人工审核的状态。"""
    with db() as conn:
        rows = rows_to_list(conn.execute("SELECT id, review_status FROM content_items ORDER BY collect_time").fetchall())
    _rerecognize_state.update({"running": True, "total": len(rows), "done": 0, "failed": 0, "started_at": now(), "finished_at": ""})
    for row in rows:
        cid, prev_status = row["id"], row["review_status"]
        try:
            recognize_content(cid)
            if prev_status in REVIEWED_STATUSES:
                with db() as conn:
                    conn.execute("UPDATE content_items SET review_status=?, updated_at=? WHERE id=?", (prev_status, now(), cid))
            _rerecognize_state["done"] += 1
        except Exception as exc:
            _rerecognize_state["failed"] += 1
            sys.stderr.write("[rerecognize-all] %s 重识别失败: %s\n" % (cid, exc))
    _rerecognize_state.update({"running": False, "finished_at": now()})


def trigger_rerecognize_all():
    """启动后台重识别所有内容；已在跑则返回当前进度。"""
    global _rerecognize_thread
    with _rerecognize_lock:
        if _rerecognize_thread is not None and _rerecognize_thread.is_alive():
            return {"started": False, "message": "重识别正在进行中", "state": dict(_rerecognize_state)}
        _rerecognize_thread = threading.Thread(target=_rerecognize_all_worker, name="rerecognize-all", daemon=True)
        _rerecognize_thread.start()
    return {"started": True, "message": "已开始后台重识别所有内容", "state": dict(_rerecognize_state)}


_repush_lock = threading.Lock()
_repush_thread = None
_repush_state = {"running": False, "total": 0, "done": 0, "failed": 0, "pushed_authors": 0, "pushed_comment_users": 0, "started_at": "", "finished_at": ""}


def _repush_confirmed_worker():
    """后台对所有已确认(confirmed)内容按当前评论分补推：发帖人 + 评论区高风险用户。"""
    with db() as conn:
        rows = rows_to_list(conn.execute("SELECT id FROM content_items WHERE review_status='confirmed' ORDER BY collect_time").fetchall())
    _repush_state.update({"running": True, "total": len(rows), "done": 0, "failed": 0, "pushed_authors": 0, "pushed_comment_users": 0, "started_at": now(), "finished_at": ""})
    for row in rows:
        try:
            with db() as conn:
                content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (row["id"],)).fetchone())
            if not content:
                continue
            if feedback_high_risk_account(content).get("ok"):
                _repush_state["pushed_authors"] += 1
            comment_fbs = feedback_high_risk_comment_users(content)
            _repush_state["pushed_comment_users"] += sum(1 for c in comment_fbs if c.get("ok"))
            _repush_state["done"] += 1
        except Exception as exc:
            _repush_state["failed"] += 1
            sys.stderr.write("[repush-confirmed] %s 补推失败: %s\n" % (row["id"], exc))
    _repush_state.update({"running": False, "finished_at": now()})


def trigger_repush_confirmed():
    """启动后台补推已确认线索；已在跑则返回当前进度。"""
    global _repush_thread
    with _repush_lock:
        if _repush_thread is not None and _repush_thread.is_alive():
            return {"started": False, "message": "补推正在进行中", "state": dict(_repush_state)}
        _repush_thread = threading.Thread(target=_repush_confirmed_worker, name="repush-confirmed", daemon=True)
        _repush_thread.start()
    return {"started": True, "message": "已开始后台补推已确认线索", "state": dict(_repush_state)}


def get_content_detail(content_id):
    with db() as conn:
        content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone())
        if not content:
            return None
        results = rows_to_list(conn.execute("SELECT * FROM recognition_results WHERE content_id=? ORDER BY created_at", (content_id,)).fetchall())
        reviews = rows_to_list(conn.execute("SELECT * FROM review_records WHERE content_id=? ORDER BY review_time DESC", (content_id,)).fetchall())
        pushes = rows_to_list(conn.execute("SELECT * FROM push_logs WHERE content_id=? ORDER BY push_time DESC", (content_id,)).fetchall())
        comments = rows_to_list(conn.execute("SELECT * FROM crawler_comments WHERE content_id=? ORDER BY date, id", (content_id,)).fetchall())
    for item in results:
        item["result"] = json_loads(item.pop("result_json"), {})
    for item in comments:
        item["sender"] = json_loads(item.pop("sender_json"), {})
        item["raw"] = json_loads(item.pop("raw_payload"), {})
    content["media_preview_url"] = public_media_url(content.get("media_url", ""))
    content["author"] = json_loads(content.get("author_json"), {})
    content["media_list_parsed"] = json_loads(content.get("media_list"), [])
    return {"content": content, "results": results, "reviews": reviews, "push_logs": pushes, "comments": comments}


def parse_multipart_form(body, content_type):
    """解析 multipart/form-data，替代 Python 3.13 已移除的 cgi 模块。

    返回 (fields, files)：
      fields: {name: str}              普通文本字段
      files:  {name: {"filename", "data"}}  文件字段（data 为原始字节）

    仅用 email 模块解析文本头部，二进制内容直接从字节切片，避免编码损坏。
    """
    type_header = EmailMessage()
    type_header["content-type"] = content_type or ""
    boundary = type_header.get_param("boundary")
    if not boundary:
        raise ValueError("缺少 multipart 边界(boundary)")
    if isinstance(boundary, tuple):  # RFC 2231 编码形式
        boundary = boundary[2]
    delimiter = b"--" + boundary.encode("latin-1")

    fields = {}
    files = {}
    for segment in body.split(delimiter):
        if not segment or segment in (b"\r\n", b"--\r\n", b"--"):
            continue
        if segment.startswith(b"--"):  # 结束边界，忽略尾部
            break
        if segment.startswith(b"\r\n"):
            segment = segment[2:]
        if segment.endswith(b"\r\n"):
            segment = segment[:-2]
        header_blob, sep, content = segment.partition(b"\r\n\r\n")
        if not sep:
            continue
        part = EmailMessage()
        for line in header_blob.split(b"\r\n"):
            if b":" in line:
                key, _, val = line.decode("latin-1").partition(":")
                part[key.strip()] = val.strip()
        name = part.get_param("name", header="content-disposition")
        if name is None:
            continue
        if isinstance(name, tuple):
            name = name[2]
        filename = part.get_filename()
        if filename is not None:
            files[name] = {"filename": filename, "data": content}
        else:
            fields[name] = content.decode("utf-8", "replace")
    return fields, files


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

    def send_bytes(self, body, status=200, content_type="application/octet-stream"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _content_length(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise PayloadTooLarge("请求体过大，超过上限 %d MB" % MAX_UPLOAD_MB)
        return length

    def body_json(self):
        length = self._content_length()
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def read_multipart_form(self):
        length = self._content_length()
        body = self.rfile.read(length) if length > 0 else b""
        return parse_multipart_form(body, self.headers.get("Content-Type", ""))

    def body_multipart_image(self):
        fields, files = self.read_multipart_form()
        image = files.get("image")
        if not image:
            raise ValueError("缺少 image 文件字段")
        return {
            "image_bytes": image["data"],
            "filename": image["filename"] or "upload.jpg",
            "conf": float(fields.get("conf", 0.5)),
            "imgsz": int(fields.get("imgsz", 800)),
            "model_id": fields.get("model_id", DEFAULT_DETECTOR_MODEL_ID),
        }

    def body_multipart_file(self):
        fields, files = self.read_multipart_form()
        upload = files.get("file")
        if not upload:
            raise ValueError("缺少 file 文件字段")
        return {
            "file": {
                "data": upload["data"],
                "filename": upload["filename"] or "upload.bin",
            },
            "content_id": fields.get("content_id", ""),
            "rule_type": fields.get("rule_type", "keyword"),
            "save_evidence": fields.get("save_evidence", "true"),
        }

    def serve_static(self):
        path = urlparse(self.path).path
        if path.startswith("/media/local/"):
            parts = path.split("/")
            token = parts[3] if len(parts) >= 4 else ""
            file_path = decode_local_media_token(token)
            if file_path and local_media_allowed(file_path):
                return self.send_bytes(file_path.read_bytes(), 200, media_content_type(file_path))
            return self.send_json({"error": "not found"}, 404)
        if path.startswith("/storage/evidence/"):
            file_path = ROOT / path.lstrip("/")
            if file_path.exists() and file_path.is_file() and (ROOT / "storage" / "evidence") in file_path.resolve().parents:
                return self.send_bytes(file_path.read_bytes(), 200, media_content_type(file_path))
            return self.send_json({"error": "not found"}, 404)
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
            if path == "/api/content-facets":
                return self.send_json(api_content_facets())
            if path == "/api/contents/recognize-all":
                return self.send_json({"state": dict(_rerecognize_state)})
            if path == "/api/contents/repush-confirmed":
                return self.send_json({"state": dict(_repush_state)})
            if m := re.match(r"^/api/contents/([^/]+)/comment-feedback$", path):
                preview = comment_feedback_preview(m.group(1))
                return self.send_json(preview or {"error": "not found"}, 200 if preview else 404)
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
            if path == "/api/text-llm-config":
                return self.send_json(llm_text_config())
            if path == "/api/rules":
                return self.send_json(api_rules(qs))
            if path == "/api/reviews":
                return self.send_json(api_reviews(qs))
            if path == "/api/push":
                return self.send_json(api_push(qs))
            return self.send_json({"error": "not found"}, 404)
        except PayloadTooLarge as exc:
            return self.send_json({"error": str(exc)}, 413)
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
            if path == "/api/rules/import":
                payload = self.body_multipart_file()
                return self.send_json(api_import_rules(payload["file"], payload.get("rule_type") or "keyword"), 201)
            payload = self.body_json()
            if path == "/api/text-service/infer-text":
                return self.send_json(merge_business_text_rules(payload, service_post_json(TEXT_SERVICE_URL, "/infer/text", payload)))
            if path == "/api/text-service/infer-content":
                return self.send_json(service_post_json(TEXT_SERVICE_URL, "/infer/content", payload))
            if path == "/api/text-llm-config/health-check":
                return self.send_json(api_llm_health_check(payload))
            if path == "/api/text-llm-config/apply-text-service":
                return self.send_json(api_apply_text_service_config(payload))
            if path == "/api/contents":
                content = api_create_content(payload)
                trigger_auto_recognize()
                return self.send_json(content, 201)
            if path == "/api/contents/recognize-all":
                return self.send_json(trigger_rerecognize_all())
            if path == "/api/contents/repush-confirmed":
                return self.send_json(trigger_repush_confirmed())
            if path == "/api/crawler/push":
                result = api_crawler_push(payload)
                if result.get("created"):
                    trigger_auto_recognize()
                return self.send_json(result, 201 if result.get("success") else 400)
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
        except PayloadTooLarge as exc:
            return self.send_json({"error": str(exc)}, 413)
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
            if path == "/api/text-llm-config":
                return self.send_json(api_update_llm_text_config(payload))
            if m := re.match(r"^/api/rules/([^/]+)$", path):
                return self.send_json(api_update_rule(m.group(1), payload))
            return self.send_json({"error": "not found"}, 404)
        except PayloadTooLarge as exc:
            return self.send_json({"error": str(exc)}, 413)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)

    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            if m := re.match(r"^/api/contents/([^/]+)$", path):
                with db() as conn:
                    conn.execute("DELETE FROM content_items WHERE id=?", (m.group(1),))
                    conn.execute("DELETE FROM recognition_results WHERE content_id=?", (m.group(1),))
                    conn.execute("DELETE FROM crawler_comments WHERE content_id=?", (m.group(1),))
                return self.send_json({"success": True})
            if m := re.match(r"^/api/rules/([^/]+)$", path):
                with db() as conn:
                    conn.execute("DELETE FROM rule_words WHERE id=?", (m.group(1),))
                sync_rules_to_text_dictionaries()
                return self.send_json({"success": True})
            return self.send_json({"error": "not found"}, 404)
        except PayloadTooLarge as exc:
            return self.send_json({"error": str(exc)}, 413)
        except Exception as exc:
            return self.send_json({"error": str(exc)}, 500)


def api_dashboard():
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    with db() as conn:
        def scalar(sql, args=()):
            return conn.execute(sql, args).fetchone()[0]
        total = scalar("SELECT COUNT(*) FROM content_items")
        today_count = scalar("SELECT COUNT(*) FROM content_items WHERE collect_time LIKE ?", (today + "%",))
        completed = scalar("SELECT COUNT(*) FROM content_items WHERE recognize_status='completed'")
        high_risk = scalar("SELECT COUNT(*) FROM content_items WHERE risk_level='高风险'")
        pending_review = scalar("SELECT COUNT(*) FROM content_items WHERE review_status='pending'")
        confirmed = scalar("SELECT COUNT(*) FROM content_items WHERE review_status='confirmed'")
        push_success = scalar("SELECT COUNT(*) FROM push_logs WHERE push_status='success'")
        platform_rows = rows_to_list(conn.execute("SELECT platform name, COUNT(*) value FROM content_items GROUP BY platform").fetchall())
        risk_rows = rows_to_list(conn.execute("SELECT risk_level name, COUNT(*) value FROM content_items GROUP BY risk_level").fetchall())
        modality_rows = rows_to_list(conn.execute("SELECT model_type name, COUNT(*) value FROM recognition_results WHERE risk_score>=0.65 GROUP BY model_type").fetchall())
        trend_rows = conn.execute(
            "SELECT substr(collect_time,1,10) d, COUNT(*) c FROM content_items WHERE substr(collect_time,1,10) >= ? GROUP BY d",
            (week_ago,),
        ).fetchall()
    # 近7日真实采集量（无数据的日期补 0），不再使用随机示意值
    trend_map = {row[0]: row[1] for row in trend_rows}
    trend = []
    for i in range(6, -1, -1):
        day = datetime.now() - timedelta(days=i)
        trend.append({"name": day.strftime("%m-%d"), "value": trend_map.get(day.strftime("%Y-%m-%d"), 0)})
    return {
        "cards": {
            "今日采集内容数": today_count or total,
            "已完成识别数": completed,
            "高风险线索数": high_risk,
            "待人工审核数": pending_review,
            "已确认线索数": confirmed,
            "推送成功数": push_success,
        },
        "platforms": platform_rows,
        "risks": risk_rows,
        "modalities": modality_rows,
        "trend": trend,
    }


def api_content_facets():
    """返回内容列表筛选项的实际取值（去重），让下拉菜单覆盖拼音/中文等真实数据。"""
    with db() as conn:
        platforms = [r[0] for r in conn.execute(
            "SELECT DISTINCT platform FROM content_items WHERE platform IS NOT NULL AND platform<>'' ORDER BY platform"
        ).fetchall()]
        content_types = [r[0] for r in conn.execute(
            "SELECT DISTINCT content_type FROM content_items WHERE content_type IS NOT NULL AND content_type<>'' ORDER BY content_type"
        ).fetchall()]
    return {"platforms": platforms, "content_types": content_types}


def pagination_params(qs, default_size=20, max_size=200):
    """从查询串解析分页参数，返回 (page, page_size, offset)，越界自动钳制。"""
    def _int(value, default, lo, hi):
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default
    page = _int(qs.get("page"), 1, 1, 1_000_000)
    page_size = _int(qs.get("page_size"), default_size, 1, max_size)
    return page, page_size, (page - 1) * page_size


def api_contents(qs):
    where = " WHERE 1=1"
    args = []
    for field in ["platform", "content_type", "recognize_status", "risk_level", "review_status"]:
        if qs.get(field):
            where += f" AND {field}=?"
            args.append(qs[field])
    if qs.get("keyword"):
        where += " AND (title LIKE ? OR raw_text LIKE ? OR account_name LIKE ?)"
        kw = f"%{qs['keyword']}%"
        args.extend([kw, kw, kw])

    page, page_size, offset = pagination_params(qs)

    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM content_items" + where, args).fetchone()[0]
        rows = rows_to_list(conn.execute(
            "SELECT * FROM content_items" + where + " ORDER BY collect_time DESC LIMIT ? OFFSET ?",
            args + [page_size, offset],
        ).fetchall())
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def content_comment_texts(content_id):
    with db() as conn:
        rows = conn.execute(
            "SELECT content,sender_json FROM crawler_comments WHERE content_id=? AND content<>'' ORDER BY date, id",
            (content_id,),
        ).fetchall()
    texts = []
    for row in rows:
        sender = json_loads(row["sender_json"], {}) or {}
        text = " ".join(
            str(item).strip()
            for item in [sender.get("nickname"), sender.get("description"), row["content"]]
            if item and str(item).strip()
        )
        if text:
            texts.append(text)
    return texts


def first_text(*values):
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def ensure_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def safe_crawler_id(platform, crawler_type, item_id):
    raw = first_text(platform, "unknown"), first_text(crawler_type, "content"), first_text(item_id, uuid.uuid4().hex)
    value = "_".join(raw)
    return re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value).strip("_")[:120]


def crawler_content_type(item, crawler_type):
    typ = (crawler_type or "").lower()
    if typ == "video" or item.get("mediaList"):
        return "视频"
    if item.get("imageList"):
        return "图片"
    if item.get("videoUrl"):
        return "视频"
    return "文本"


def crawler_media_list(item):
    if item.get("mediaList") is not None:
        return [str(v) for v in ensure_list(item.get("mediaList")) if v]
    if item.get("videoUrl") is not None:
        return [str(v) for v in ensure_list(item.get("videoUrl")) if v]
    if item.get("imageList") is not None:
        return [str(v) for v in ensure_list(item.get("imageList")) if v]
    return []


def crawler_raw_text(item):
    return first_text(item.get("description"), item.get("content"))


def flatten_crawler_comments(comments):
    flattened = []
    for comment in ensure_list(comments):
        if not isinstance(comment, dict):
            continue
        flattened.append(("comment", comment))
        for sub_comment in ensure_list(comment.get("subComments")):
            if isinstance(sub_comment, dict):
                flattened.append(("sub_comment", sub_comment))
    return flattened


def upsert_crawler_comments(conn, content_id, comments):
    seen = set()
    t = now()
    for comment_type, comment in flatten_crawler_comments(comments):
        comment_id = first_text(comment.get("id"))
        if not comment_id:
            comment_id = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(comment, ensure_ascii=False, sort_keys=True)).hex
        cid = safe_crawler_id(content_id, comment_type, comment_id)
        seen.add(cid)
        sender = comment.get("sender") if isinstance(comment.get("sender"), dict) else {}
        conn.execute(
            """INSERT INTO crawler_comments
            (id,content_id,comment_type,parent_comment_id,sender_json,content,date,raw_payload,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              content_id=excluded.content_id,
              comment_type=excluded.comment_type,
              parent_comment_id=excluded.parent_comment_id,
              sender_json=excluded.sender_json,
              content=excluded.content,
              date=excluded.date,
              raw_payload=excluded.raw_payload,
              updated_at=excluded.updated_at""",
            (
                cid,
                content_id,
                comment_type,
                first_text(comment.get("parentId")),
                json.dumps(sender, ensure_ascii=False),
                first_text(comment.get("content")),
                first_text(comment.get("date")),
                json.dumps(comment, ensure_ascii=False),
                t,
                t,
            ),
        )
    if seen:
        placeholders = ",".join("?" for _ in seen)
        conn.execute(
            f"DELETE FROM crawler_comments WHERE content_id=? AND id NOT IN ({placeholders})",
            [content_id, *seen],
        )
    else:
        conn.execute("DELETE FROM crawler_comments WHERE content_id=?", (content_id,))


def crawler_item_to_content(platform, crawler_type, item):
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    media = crawler_media_list(item)
    crawler_id = first_text(item.get("id"))
    content_id = safe_crawler_id(platform, crawler_type, crawler_id)
    return {
        "id": content_id,
        "platform": first_text(platform, "未知平台"),
        "content_type": crawler_content_type(item, crawler_type),
        "title": first_text(item.get("title"), crawler_raw_text(item), "未命名内容"),
        "account_name": first_text(author.get("nickname"), author.get("id"), "未知账号"),
        "account_url": first_text(author.get("avatarUrl")),
        "content_url": first_text(item.get("url")),
        "raw_text": crawler_raw_text(item),
        "media_url": media[0] if media else "",
        "publish_time": first_text(item.get("date")),
        "crawler_type": first_text(crawler_type),
        "crawler_id": crawler_id,
        "author_json": json.dumps(author, ensure_ascii=False),
        "media_list": json.dumps(media, ensure_ascii=False),
        "raw_payload": json.dumps(item, ensure_ascii=False),
    }


def api_crawler_push(payload):
    if not isinstance(payload, dict):
        return {"error": "payload must be object"}
    platform = first_text(payload.get("platform"), "未知平台")
    crawler_type = first_text(payload.get("type"), "content")
    items = payload.get("data")
    if not isinstance(items, list):
        return {"error": "data must be list"}
    t = now()
    accepted = []
    created = 0
    updated = 0
    with db() as conn:
        for item in items:
            if not isinstance(item, dict):
                continue
            content = crawler_item_to_content(platform, crawler_type, item)
            exists = conn.execute("SELECT 1 FROM content_items WHERE id=?", (content["id"],)).fetchone()
            if exists:
                conn.execute(
                    """UPDATE content_items SET
                      platform=?,content_type=?,title=?,account_name=?,account_url=?,content_url=?,raw_text=?,media_url=?,
                      publish_time=?,collect_time=?,crawler_type=?,crawler_id=?,author_json=?,media_list=?,raw_payload=?,updated_at=?
                      WHERE id=?""",
                    (
                        content["platform"],
                        content["content_type"],
                        content["title"],
                        content["account_name"],
                        content["account_url"],
                        content["content_url"],
                        content["raw_text"],
                        content["media_url"],
                        content["publish_time"] or t,
                        t,
                        content["crawler_type"],
                        content["crawler_id"],
                        content["author_json"],
                        content["media_list"],
                        content["raw_payload"],
                        t,
                        content["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO content_items
                    (id,platform,content_type,title,account_name,account_url,content_url,raw_text,media_url,publish_time,collect_time,
                     recognize_status,risk_score,risk_level,review_status,crawler_type,crawler_id,author_json,media_list,raw_payload,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        content["id"],
                        content["platform"],
                        content["content_type"],
                        content["title"],
                        content["account_name"],
                        content["account_url"],
                        content["content_url"],
                        content["raw_text"],
                        content["media_url"],
                        content["publish_time"] or t,
                        t,
                        "pending",
                        0,
                        "无风险",
                        "unreviewed",
                        content["crawler_type"],
                        content["crawler_id"],
                        content["author_json"],
                        content["media_list"],
                        content["raw_payload"],
                        t,
                        t,
                    ),
                )
                created += 1
            upsert_crawler_comments(conn, content["id"], item.get("comments"))
            accepted.append(content["id"])
    return {"success": True, "accepted": len(accepted), "created": created, "updated": updated, "content_ids": accepted}


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
    where = " WHERE 1=1"
    args = []
    if qs.get("rule_type"):
        where += " AND rule_type=?"
        args.append(qs["rule_type"])
    page, page_size, offset = pagination_params(qs)
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM rule_words" + where, args).fetchone()[0]
        rows = rows_to_list(conn.execute(
            "SELECT * FROM rule_words" + where + " ORDER BY rule_type, created_at DESC LIMIT ? OFFSET ?",
            args + [page_size, offset],
        ).fetchall())
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def sync_rules_to_text_dictionaries():
    data_dir = ROOT / "text_service" / "data"
    if not data_dir.exists():
        return
    with db() as conn:
        rows = rows_to_list(conn.execute("SELECT * FROM rule_words WHERE enabled=1").fetchall())
    imports = {"keyword": [], "blackword": [], "brand": [], "whitelist": [], "region": []}
    for row in rows:
        word = str(row.get("word") or "").strip()
        if not word:
            continue
        typ = row.get("rule_type")
        if typ in imports:
            imports[typ].append(word)
    payload = {key: sorted(set(words)) for key, words in imports.items() if words}
    (data_dir / "management_rule_keywords.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api_create_rule(payload):
    rid = new_id("RW")
    with db() as conn:
        conn.execute(
            "INSERT INTO rule_words VALUES (?,?,?,?,?,?,?)",
            (rid, payload.get("rule_type", "keyword"), payload.get("word", ""), float(payload.get("risk_weight", 0.1)), int(payload.get("enabled", 1)), payload.get("remark", ""), now()),
        )
        row = row_to_dict(conn.execute("SELECT * FROM rule_words WHERE id=?", (rid,)).fetchone())
    sync_rules_to_text_dictionaries()
    return row


def normalize_rule_type(value):
    value = str(value or "keyword").strip()
    aliases = {
        "关键词": "keyword",
        "黑话": "blackword",
        "品牌": "brand",
        "品牌词": "brand",
        "白名单": "whitelist",
        "地域": "region",
        "地域词": "region",
    }
    return aliases.get(value, value if value in {"keyword", "blackword", "brand", "whitelist", "region"} else "keyword")


def parse_rule_upload(file_payload, default_rule_type="keyword"):
    filename = file_payload.get("filename") or ""
    text = file_payload.get("data", b"").decode("utf-8-sig", errors="ignore")
    suffix = Path(filename).suffix.lower()
    rows = []
    if suffix == ".json":
        data = json.loads(text or "[]")
        if isinstance(data, list):
            source_rows = data
        elif isinstance(data, dict):
            source_rows = []
            for typ, value in data.items():
                if isinstance(value, dict):
                    for category, words in value.items():
                        for word in words if isinstance(words, list) else [words]:
                            source_rows.append({"rule_type": typ, "word": word, "remark": str(category)})
                else:
                    for word in value if isinstance(value, list) else [value]:
                        source_rows.append({"rule_type": typ, "word": word})
        else:
            source_rows = []
        for item in source_rows:
            if isinstance(item, str):
                rows.append({"rule_type": default_rule_type, "word": item})
            elif isinstance(item, dict):
                rows.append(item)
    elif suffix == ".csv":
        csv_rows = list(csv.reader(io.StringIO(text)))
        if csv_rows:
            header = [item.strip() for item in csv_rows[0]]
            has_header = bool({"word", "词条", "rule_type", "类型"} & set(header))
            if has_header:
                rows.extend(csv.DictReader(io.StringIO(text)))
            else:
                for parts in csv_rows:
                    if parts and parts[0].strip():
                        rows.append({"word": parts[0].strip(), "rule_type": default_rule_type})
    else:
        for line in text.splitlines():
            word = line.strip()
            if word and not word.startswith("#"):
                rows.append({"rule_type": default_rule_type, "word": word})
    parsed = []
    for item in rows:
        word = str(item.get("word") or item.get("词条") or "").strip()
        if not word:
            continue
        parsed.append(
            {
                "rule_type": normalize_rule_type(item.get("rule_type") or item.get("类型") or default_rule_type),
                "word": word,
                "risk_weight": float(item.get("risk_weight") or item.get("权重") or 0.1),
                "enabled": int(item.get("enabled") if item.get("enabled") is not None else item.get("启用") if item.get("启用") is not None else 1),
                "remark": str(item.get("remark") or item.get("备注") or "文件导入").strip(),
            }
        )
    return parsed


def api_import_rules(file_payload, default_rule_type="keyword"):
    items = parse_rule_upload(file_payload, default_rule_type)
    inserted = 0
    skipped = 0
    with db() as conn:
        for item in items:
            exists = conn.execute("SELECT 1 FROM rule_words WHERE rule_type=? AND word=?", (item["rule_type"], item["word"])).fetchone()
            if exists:
                skipped += 1
                continue
            conn.execute(
                "INSERT INTO rule_words VALUES (?,?,?,?,?,?,?)",
                (new_id("RW"), item["rule_type"], item["word"], item["risk_weight"], item["enabled"], item["remark"], now()),
            )
            inserted += 1
    sync_rules_to_text_dictionaries()
    return {"success": True, "inserted": inserted, "skipped": skipped, "parsed": len(items)}


def api_update_rule(rule_id, payload):
    fields = ["rule_type", "word", "risk_weight", "enabled", "remark"]
    sets = [f"{f}=?" for f in fields if f in payload]
    args = [int(payload[f]) if f == "enabled" else payload[f] for f in fields if f in payload]
    args.append(rule_id)
    with db() as conn:
        conn.execute(f"UPDATE rule_words SET {','.join(sets)} WHERE id=?", args)
        row = row_to_dict(conn.execute("SELECT * FROM rule_words WHERE id=?", (rule_id,)).fetchone())
    sync_rules_to_text_dictionaries()
    return row


def api_reviews(qs):
    status = qs.get("review_status")
    where = " WHERE c.risk_level IN ('高风险','中风险')"
    args = []
    if status:
        where += " AND c.review_status=?"
        args.append(status)
    sql = ("""SELECT c.id content_id,c.platform,c.title,c.risk_score,c.risk_level,c.review_status,
             rr.id review_id,rr.reviewer,rr.review_time,rr.review_opinion
             FROM content_items c LEFT JOIN review_records rr ON rr.content_id=c.id"""
           + where + " GROUP BY c.id ORDER BY c.risk_score DESC LIMIT ? OFFSET ?")
    page, page_size, offset = pagination_params(qs)
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM content_items c" + where, args).fetchone()[0]
        rows = rows_to_list(conn.execute(sql, args + [page_size, offset]).fetchall())
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


def crawler_account_user_id(content):
    """从 author_json 提取平台用户ID，用于向爬虫端反馈账户风险。"""
    author = json_loads(content.get("author_json"), {})
    if isinstance(author, dict):
        return first_text(author.get("id"), author.get("uid"), author.get("user_id"))
    return ""


def post_crawler_user_risk(platform, user_id, risk_score, timeout=5):
    """向爬虫端反馈单个高风险账户：POST {platform,id,risk_score}。"""
    body = json.dumps(
        {"platform": platform, "id": user_id, "risk_score": round(float(risk_score or 0), 4)},
        ensure_ascii=False,
    ).encode("utf-8")
    parsed = urlparse(CRAWLER_RISK_API_BASE)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), timeout=timeout)
    try:
        conn.request("POST", CRAWLER_RISK_API_PATH, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
        return {"ok": 200 <= resp.status < 300, "status_code": resp.status, "response": raw[:300]}
    finally:
        conn.close()


def feedback_high_risk_account(content):
    """审核确认后把高风险账户(平台/用户id/风险分)反馈给爬虫端；尽力而为，失败不阻塞审核。"""
    platform = content.get("platform") or ""
    user_id = crawler_account_user_id(content)
    risk_score = content.get("risk_score") or 0
    if not user_id:
        return {"ok": False, "skipped": True, "reason": "缺少账户用户ID(author_json.id)", "platform": platform}
    payload = {"platform": platform, "id": user_id, "risk_score": round(float(risk_score), 4)}
    try:
        result = post_crawler_user_risk(platform, user_id, risk_score)
        if not result.get("ok"):
            sys.stderr.write("[crawler-feedback] 反馈失败 %s: %s\n" % (payload, result))
        return {**payload, **result, "endpoint": CRAWLER_RISK_API_BASE + CRAWLER_RISK_API_PATH}
    except Exception as exc:
        sys.stderr.write("[crawler-feedback] 反馈异常 %s: %s\n" % (payload, exc))
        return {**payload, "ok": False, "error": str(exc), "endpoint": CRAWLER_RISK_API_BASE + CRAWLER_RISK_API_PATH}


def comment_sender_user_id(sender):
    if not isinstance(sender, dict):
        return ""
    uid = first_text(
        sender.get("id"), sender.get("uid"), sender.get("user_id"), sender.get("userId"),
        sender.get("secUid"), sender.get("sec_uid"), sender.get("uin"), sender.get("userID"),
        sender.get("authorId"), sender.get("author_id"),
    )
    if uid:
        return uid
    # 兼容嵌套结构，如 sender.user.id
    nested = sender.get("user") if isinstance(sender.get("user"), dict) else {}
    return first_text(nested.get("id"), nested.get("uid"), nested.get("user_id"), nested.get("userId"))


def comment_feedback_preview(content_id):
    """诊断：列出该内容每条评论的用户id、风险分与是否会上报爬虫端及原因（不实际推送）。"""
    with db() as conn:
        content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone())
        if not content:
            return None
        rows = rows_to_list(conn.execute(
            "SELECT comment_type, sender_json, content, risk_score, risk_level, risk_updated_at FROM crawler_comments WHERE content_id=? ORDER BY date, id",
            (content_id,),
        ).fetchall())
    author_id = crawler_account_user_id(content)
    items = []
    for row in rows:
        sender = json_loads(row["sender_json"], {}) or {}
        uid = comment_sender_user_id(sender)
        score = float(row["risk_score"] or 0)
        scored = bool(row["risk_updated_at"])
        if not uid:
            reason = "无可识别的评论用户ID(sender 缺 id/uid 等字段)"
        elif not scored:
            reason = "该评论尚未打分(需重新识别)"
        elif uid == author_id:
            reason = "与发帖人相同，已随发帖人反馈"
        elif score < COMMENT_HIGH_RISK_THRESHOLD:
            reason = f"风险分 {round(score,4)} < 阈值 {COMMENT_HIGH_RISK_THRESHOLD}"
        else:
            reason = "会上报"
        items.append({
            "level": "一级" if row["comment_type"] == "comment" else "二级",
            "user_id": uid,
            "nickname": sender.get("nickname") or sender.get("name"),
            "risk_score": round(score, 4),
            "risk_level": row["risk_level"],
            "scored": scored,
            "would_push": reason == "会上报",
            "reason": reason,
            "content": (row["content"] or "")[:80],
            "sender_keys": sorted(sender.keys()) if isinstance(sender, dict) else [],
        })
    return {
        "content_id": content_id,
        "platform": content.get("platform"),
        "author_id": author_id,
        "threshold": COMMENT_HIGH_RISK_THRESHOLD,
        "total_comments": len(items),
        "would_push_count": sum(1 for it in items if it["would_push"]),
        "comments": items,
    }


def ensure_comments_scored(content):
    """确保评论已打分：存在未打分(risk_updated_at 为空)的评论时按需补分并落库。
    兜底覆盖“评论后补、识别早于评分逻辑、审核早于异步评分完成”等导致漏分的情况。"""
    content_id = content["id"]
    with db() as conn:
        unscored = conn.execute(
            "SELECT COUNT(*) FROM crawler_comments WHERE content_id=? AND content<>'' AND (risk_updated_at IS NULL OR risk_updated_at='')",
            (content_id,),
        ).fetchone()[0]
    if not unscored:
        return
    scores = score_content_comments(content)
    if scores:
        with db() as conn:
            for comment_db_id, (c_score, c_level) in scores.items():
                conn.execute(
                    "UPDATE crawler_comments SET risk_score=?, risk_level=?, risk_updated_at=? WHERE id=?",
                    (c_score, c_level, now(), comment_db_id),
                )


def feedback_high_risk_comment_users(content):
    """审核确认后，读取识别阶段已落库的评论风险分(一级 comment + 二级 sub_comment)，
    把高风险评论用户(平台/用户id/风险分)反馈给爬虫端；按用户去重取最高分。"""
    content_id = content["id"]
    platform = content.get("platform") or ""
    author_id = crawler_account_user_id(content)
    ensure_comments_scored(content)
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT comment_type, sender_json, risk_score FROM crawler_comments WHERE content_id=? AND content<>''",
            (content_id,),
        ).fetchall())
    best = {}
    for row in rows:
        sender = json_loads(row["sender_json"], {}) or {}
        uid = comment_sender_user_id(sender)
        score = float(row["risk_score"] or 0)
        if not uid or uid == author_id or score < COMMENT_HIGH_RISK_THRESHOLD:
            continue
        level = "一级" if row["comment_type"] == "comment" else "二级"
        if uid not in best or score > best[uid]["score"]:
            best[uid] = {"score": round(score, 4), "comment_level": level}
    feedbacks = []
    for uid, info in best.items():
        try:
            result = post_crawler_user_risk(platform, uid, info["score"])
            if not result.get("ok"):
                sys.stderr.write("[crawler-feedback] 评论用户反馈失败 %s/%s: %s\n" % (platform, uid, result))
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            sys.stderr.write("[crawler-feedback] 评论用户反馈异常 %s/%s: %s\n" % (platform, uid, exc))
        feedbacks.append({"platform": platform, "id": uid, "risk_score": info["score"], "comment_level": info["comment_level"], **result})
    return feedbacks


def api_review(content_id, payload):
    status = payload.get("review_status", "confirmed")
    rid = new_id("REV")
    with db() as conn:
        conn.execute("INSERT INTO review_records VALUES (?,?,?,?,?,?)", (rid, content_id, status, payload.get("review_opinion", ""), payload.get("reviewer", "审核员"), now()))
        conn.execute("UPDATE content_items SET review_status=?, updated_at=? WHERE id=?", (status, now(), content_id))
        record = row_to_dict(conn.execute("SELECT * FROM review_records WHERE id=?", (rid,)).fetchone())
        content = row_to_dict(conn.execute("SELECT * FROM content_items WHERE id=?", (content_id,)).fetchone())
    # 确认为违法线索后，向爬虫端反馈：发帖人 + 评论区(一级/二级)高风险用户
    if status == "confirmed" and content:
        record["crawler_feedback"] = {
            "author": feedback_high_risk_account(content),
            "comment_users": feedback_high_risk_comment_users(content),
        }
    return record


def api_push(qs):
    page, page_size, offset = pagination_params(qs)
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM push_logs").fetchone()[0]
        rows = rows_to_list(conn.execute("""SELECT p.*,c.title,c.platform,c.risk_level FROM push_logs p
            LEFT JOIN content_items c ON c.id=p.content_id ORDER BY COALESCE(p.push_time,''), p.id DESC LIMIT ? OFFSET ?""",
            (page_size, offset)).fetchall())
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


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
    # 默认监听全网卡保持兼容；置于反向代理(HTTP Basic)之后时建议设为 127.0.0.1，避免 8000 直接暴露
    host = os.environ.get("MANAGEMENT_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Demo server running: http://{host}:{port}")
    # 启动即扫描历史未识别(pending)数据，后台线程依次自动识别
    trigger_auto_recognize()
    server.serve_forever()


if __name__ == "__main__":
    main()
