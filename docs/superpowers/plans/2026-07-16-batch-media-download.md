# 二次批次远程媒体按需下载 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 二次确认批次帖的 http/https `media_url`（爬虫缓存构造的文件链接）在识别阶段下载为本地临时文件喂给视觉/语音服务，识别后即删；下载失败退化 mock 且 `download_error` 可见。

**Architecture:** 全部改动在 `app.py`：新增 `download_media_to_temp()`（纯 `urllib.request`，带大小/时长守卫）+ `recognize_content` 识别分流分支接入（临时文件生命周期 try/finally 管理）。识别服务、分流条件、融合零改动。

**Tech Stack:** Python 3 标准库（urllib.request / tempfile / time）、pytest（stdlib ThreadingHTTPServer 模拟爬虫缓存服务器）。

## Global Constraints

- 不新增第三方依赖（纯标准库）；不改两个识别服务、不改识别分流条件与融合算法；不改写 `content_items.media_url` 字段。
- 下载守卫：仅 http/https；单文件上限 `MEDIA_DOWNLOAD_MAX_MB`（默认 200，env 可覆盖）；总时长 `MEDIA_DOWNLOAD_TIMEOUT_SECONDS`（默认 120，读循环内按墙钟累计强制）；`urlopen(timeout=30)`；跟随重定向（urllib 默认）。
- 下载失败不阻断识别：`download_error` 写入 fusion 结果 dict（必然落库），视觉通道走过时同时写入 image 结果 dict。
- 下载场景 `image_result["evidence_frame"]` 覆写回原始 `media_url`（临时文件会删除，不能留悬空路径）。
- 测试命令用 `python3 -m pytest`（本机无 `python` 命令）。
- 每个 `git commit` 结尾 trailer：`Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `app.py` | 修改 | ① `import urllib.request`；② 常量 + `download_media_to_temp()`（插在 `public_media_url` 之前）；③ `recognize_content` 识别分流分支接入 |
| `tests/test_media_download.py` | 新建 | 下载函数单测 + 识别接入集成测试（含假爬虫缓存 HTTP 服务器 fixture） |

---

## Task 1: `download_media_to_temp` 下载函数 + 单测

**Files:**
- Modify: `app.py` — import 区（约 22 行 `from urllib.parse import ...` 附近）+ `public_media_url`（约 172 行）之前插入常量与函数
- Test: `tests/test_media_download.py`（新建）

**Interfaces:**
- Consumes: 无（纯标准库）。
- Produces: `download_media_to_temp(media_url, content_type="") -> tuple[Path | None, str | None]`——成功返回 `(临时文件 Path, None)`，失败返回 `(None, 错误描述字符串)`，**不抛异常**；模块常量 `MEDIA_DOWNLOAD_MAX_MB`、`MEDIA_DOWNLOAD_TIMEOUT_SECONDS`、`MEDIA_SUFFIX_WHITELIST`（Task 2 复用）。

- [ ] **Step 1: 新建测试文件，写失败测试**

新建 `tests/test_media_download.py`：

```python
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def load_app():
    spec = importlib.util.spec_from_file_location("management_app_media", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"x" * 2048


class _MediaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v.mp4":
            self._send(MP4_BYTES, "video/mp4")
        elif self.path == "/noext":
            self._send(b"PNGDATA", "image/png")
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/v.mp4")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def _send(self, payload, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # 保持测试输出干净
        pass


@pytest.fixture
def media_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_download_success_suffix_from_url(media_server):
    m = load_app()
    path, err = m.download_media_to_temp(media_server + "/v.mp4", "视频")
    assert err is None and path is not None
    assert path.exists() and path.suffix == ".mp4"
    assert path.read_bytes() == MP4_BYTES
    path.unlink()


def test_download_suffix_from_content_type(media_server):
    m = load_app()
    path, err = m.download_media_to_temp(media_server + "/noext", "图片")
    assert err is None and path is not None and path.suffix == ".png"
    path.unlink()


def test_download_follows_redirect(media_server):
    m = load_app()
    path, err = m.download_media_to_temp(media_server + "/redirect", "视频")
    assert err is None and path is not None and path.read_bytes() == MP4_BYTES
    path.unlink()


def test_download_404_returns_error(media_server):
    m = load_app()
    path, err = m.download_media_to_temp(media_server + "/missing.mp4", "视频")
    assert path is None and err


def test_download_rejects_non_http():
    m = load_app()
    path, err = m.download_media_to_temp("ftp://example.com/a.mp4", "视频")
    assert path is None and "http" in err
    path, err = m.download_media_to_temp("", "视频")
    assert path is None and err


def test_download_size_cap_aborts_and_cleans(media_server, tmp_path):
    m = load_app()
    m.MEDIA_DOWNLOAD_MAX_MB = 0  # 上限 0MB：首个分块即超限
    path, err = m.download_media_to_temp(media_server + "/v.mp4", "视频")
    assert path is None and "上限" in err
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_media_download.py -v`
Expected: 全部 FAIL/ERROR，报 `AttributeError: ... has no attribute 'download_media_to_temp'`

- [ ] **Step 3: 实现下载函数**

`app.py` import 区，在 `import uuid` 行之后加一行：

```python
import urllib.request
```

`app.py` 在 `def public_media_url(media_url):`（约 172 行）之前插入：

```python
MEDIA_DOWNLOAD_MAX_MB = int(os.environ.get("MEDIA_DOWNLOAD_MAX_MB", "200"))
MEDIA_DOWNLOAD_TIMEOUT_SECONDS = int(os.environ.get("MEDIA_DOWNLOAD_TIMEOUT_SECONDS", "120"))
MEDIA_SUFFIX_WHITELIST = {".jpg", ".jpeg", ".png", ".bmp", ".webp",
                          ".mp4", ".mov", ".avi", ".mkv",
                          ".wav", ".mp3", ".m4a", ".aac", ".flac"}
MEDIA_CONTENT_TYPE_SUFFIX = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/bmp": ".bmp", "image/webp": ".webp",
    "video/mp4": ".mp4", "video/quicktime": ".mov", "video/x-matroska": ".mkv",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/flac": ".flac",
}
MEDIA_DEFAULT_SUFFIX = {"图片": ".jpg", "视频": ".mp4", "音频": ".mp3"}


def download_media_to_temp(media_url, content_type=""):
    """把爬虫缓存的媒体链接下载为本地临时文件，供多模态识别消费（用完由调用方删除）。
    返回 (Path, None) 或 (None, 错误描述)，不抛异常。
    守卫：仅 http/https；MEDIA_DOWNLOAD_MAX_MB 大小上限；MEDIA_DOWNLOAD_TIMEOUT_SECONDS 墙钟总时长。"""
    parsed = urlparse(media_url or "")
    if parsed.scheme not in {"http", "https"}:
        return None, f"仅支持 http/https 媒体链接：{media_url or '(空)'}"
    req = urllib.request.Request(
        media_url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TobaccoDetection/1.0"})
    max_bytes = MEDIA_DOWNLOAD_MAX_MB * 1024 * 1024
    started = time.monotonic()
    tmp = None
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            suffix = Path(urlparse(resp.geturl()).path).suffix.lower()
            if suffix not in MEDIA_SUFFIX_WHITELIST:
                mime = (resp.headers.get_content_type() or "").lower()
                suffix = MEDIA_CONTENT_TYPE_SUFFIX.get(mime) or MEDIA_DEFAULT_SUFFIX.get(content_type, ".bin")
            tmp = tempfile.NamedTemporaryFile(prefix="tobacco_media_", suffix=suffix, delete=False)
            total = 0
            while True:
                if time.monotonic() - started > MEDIA_DOWNLOAD_TIMEOUT_SECONDS:
                    raise RuntimeError(f"下载超时(>{MEDIA_DOWNLOAD_TIMEOUT_SECONDS}s)")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"超过大小上限 {MEDIA_DOWNLOAD_MAX_MB}MB")
                tmp.write(chunk)
        tmp.close()
        return Path(tmp.name), None
    except Exception as exc:
        if tmp is not None:
            tmp.close()
            Path(tmp.name).unlink(missing_ok=True)
        return None, str(exc)
```

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_media_download.py -v`
Expected: 6 passed。再跑 `python3 -m pytest -q` 全量无回归。

- [ ] **Step 5: 提交**

```bash
git add app.py tests/test_media_download.py
git commit -m "feat(media): 爬虫缓存媒体链接下载函数(大小/时长守卫+后缀推断)"
```

---

## Task 2: `recognize_content` 识别分流接入 + 集成测试

**Files:**
- Modify: `app.py` — `recognize_content` 识别分流分支（约 1562-1583 行）
- Test: `tests/test_media_download.py`（追加集成测试）

**Interfaces:**
- Consumes: Task 1 的 `download_media_to_temp(media_url, content_type) -> (Path|None, str|None)`。
- Produces: 无新接口；行为变化——批次帖 http 媒体走真实多模态，`recognition_results` 的 fusion/image 行可能含 `download_error` 键。

- [ ] **Step 1: 写失败集成测试**

在 `tests/test_media_download.py` 末尾追加：

```python
def _prep_app(tmp_path):
    """加载 app 模块 + 隔离库 + 屏蔽外部文本服务(用本地 analyze_text 兜底形状)。"""
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    m.text_service_analyze_content = lambda content: m.analyze_text(
        {"content_id": content["id"], "text": content.get("raw_text") or content.get("title") or ""})
    return m


def _seed_batch_post(m, media_url, content_type="视频", cid="BM1"):
    with m.db() as conn:
        conn.execute(
            "INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
            "account_key,confirm_batch_id,media_url,created_at,updated_at) "
            "VALUES (?,?,?,'t','a','pending','小红书:u1','B9',?,?,?)",
            (cid, "小红书", content_type, media_url, m.now(), m.now()))


def _result_json(m, cid, model_type):
    with m.db() as conn:
        row = conn.execute(
            "SELECT result_json FROM recognition_results WHERE content_id=? AND model_type=?",
            (cid, model_type)).fetchone()
    return json.loads(row["result_json"]) if row else None


def test_batch_url_media_downloaded_fed_locally_and_cleaned(tmp_path, media_server):
    m = _prep_app(tmp_path)
    src = media_server + "/v.mp4"
    seen = {}

    def fake_vision(payload):
        p = Path(payload["image_url"])
        seen["vision_local"] = p.is_absolute() and p.exists()
        seen["vision_path"] = p
        return {"image_risk_score": 0.9, "detected_objects": [], "brand": "", "ocr_text": [],
                "confidence": 0.9, "evidence_frame": payload["image_url"], "model_version": "test-v"}

    def fake_audio(content, media_path):
        seen["audio_local"] = Path(str(media_path)).exists()
        return {"audio_risk_score": 0.8, "model_version": "test-a"}

    m.analyze_image_with_vision = fake_vision
    m.audio_service_analyze_media = fake_audio
    _seed_batch_post(m, src, "视频")
    m.recognize_content("BM1")

    assert seen["vision_local"] and seen["audio_local"]          # 服务收到当时存在的本地文件
    assert not seen["vision_path"].exists()                      # 识别后临时文件已删
    with m.db() as conn:
        row = conn.execute("SELECT recognize_status FROM content_items WHERE id='BM1'").fetchone()
    assert row["recognize_status"] == "completed"
    assert _result_json(m, "BM1", "image")["evidence_frame"] == src   # 回指原链接
    assert "download_error" not in _result_json(m, "BM1", "fusion")


def test_batch_url_download_failure_visible(tmp_path, media_server):
    m = _prep_app(tmp_path)
    _seed_batch_post(m, media_server + "/missing.mp4", "视频", cid="BM2")
    m.recognize_content("BM2")
    with m.db() as conn:
        row = conn.execute("SELECT recognize_status FROM content_items WHERE id='BM2'").fetchone()
    assert row["recognize_status"] == "completed"                # 失败不阻断识别
    assert "download_error" in _result_json(m, "BM2", "image")   # mock 退化可见
    assert "download_error" in _result_json(m, "BM2", "fusion")


def test_first_pass_http_media_never_downloads(tmp_path, media_server):
    m = _prep_app(tmp_path)
    calls = []
    original = m.download_media_to_temp
    m.download_media_to_temp = lambda *a, **k: (calls.append(a), original(*a, **k))[1]
    with m.db() as conn:
        conn.execute(
            "INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
            "media_url,created_at,updated_at) VALUES ('FP1','小红书','视频','t','a','pending',?,?,?)",
            (media_server + "/v.mp4", m.now(), m.now()))
    m.recognize_content("FP1")
    assert calls == []                                           # 首轮(无批次)不下载
    assert _result_json(m, "FP1", "image") is None               # 分流:首轮无 image 行
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_media_download.py -k "batch_url or first_pass" -v`
Expected: 前两个 FAIL（服务收到的是 URL 非本地路径 / 无 download_error 键）；`first_pass` 本就应 PASS（现状不下载）——若它也 FAIL 说明理解有误，停下检查。

- [ ] **Step 3: 接入 recognize_content**

`app.py` `recognize_content` 里这段（约 1562-1583 行）：

```python
    image_score = 0
    audio_score = 0
    image_result = None
    audio_result = None
    # 识别分流：首次识别(无 confirm_batch_id)只跑 LLM 文本粗筛；
    # 二次确认批次(有 confirm_batch_id)才对高危账户的帖子跑图像/视频/语音多模态。
    if content.get("confirm_batch_id"):
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
```

整体替换为：

```python
    image_score = 0
    audio_score = 0
    image_result = None
    audio_result = None
    # 识别分流：首次识别(无 confirm_batch_id)只跑 LLM 文本粗筛；
    # 二次确认批次(有 confirm_batch_id)才对高危账户的帖子跑图像/视频/语音多模态。
    if content.get("confirm_batch_id"):
        media_url = content["media_url"] or ""
        media_path = resolve_media_path(media_url)
        downloaded_tmp = None
        download_error = None
        # 爬虫缓存链接：本地无此媒体且是 http(s) 时按需下载为临时文件（识别完即删）
        if media_path is None and urlparse(media_url).scheme in {"http", "https"}:
            url_ext = Path(urlparse(media_url).path).suffix.lower()
            if content["content_type"] in {"图片", "视频", "音频"} or url_ext in MEDIA_SUFFIX_WHITELIST:
                downloaded_tmp, download_error = download_media_to_temp(media_url, content["content_type"])
                if download_error:
                    sys.stderr.write("[media-download] %s 下载失败: %s\n" % (content_id, download_error))
                media_path = downloaded_tmp
        try:
            media_ext = media_path.suffix.lower() if media_path else ""
            is_visual_media = content["content_type"] in {"图片", "视频"} or media_ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv"}
            is_audio_media = content["content_type"] in {"音频", "视频"} or media_ext in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".mp4", ".mov", ".avi", ".mkv"}
            if is_visual_media:
                image_source = str(media_path) if media_path else media_url
                image_result = analyze_image_with_vision({"content_id": content_id, "image_url": image_source, "media_type": "video" if content["content_type"] == "视频" else "image"})
                if downloaded_tmp is not None:
                    image_result["evidence_frame"] = media_url  # 临时文件会删除，证据帧字段回指爬虫缓存原链接
                if download_error:
                    image_result["download_error"] = download_error
                image_score = image_result["image_risk_score"]
            if is_audio_media and media_path:
                try:
                    audio_result = audio_service_analyze_media(content, media_path)
                except Exception as exc:
                    audio_result = analyze_audio({"content_id": content_id, "audio_url": media_url})
                    audio_result["service_mode"] = "local-audio-fallback"
                    audio_result["audio_service_error"] = str(exc)
                audio_score = audio_result["audio_risk_score"]
        finally:
            if downloaded_tmp is not None:
                downloaded_tmp.unlink(missing_ok=True)
```

然后在紧随其后的 `fusion = analyze_fusion({...})` 调用**之后**（`comment_scores = score_content_comments(content)` 之前）加：

```python
    if content.get("confirm_batch_id") and download_error:
        fusion["download_error"] = download_error
```

注意：`download_error` 变量只在批次分支内定义，上面这行必须用 `content.get("confirm_batch_id") and ...` 短路保护（首轮内容不会进批次分支、变量未定义——Python 短路后不会求值 `download_error`。若实现时静态检查报未定义，可在分支外初始化 `download_error = None`，等价）。

- [ ] **Step 4: 运行确认通过**

Run: `python3 -m pytest tests/test_media_download.py -v`
Expected: 9 passed（6 单测 + 3 集成）。

- [ ] **Step 5: 全量回归**

Run: `python3 -m pytest -q`
Expected: 全部通过（101 + 9 = 110 附近，以实际为准），无回归。

- [ ] **Step 6: 提交**

```bash
git add app.py tests/test_media_download.py
git commit -m "feat(media): 二次批次http媒体识别时按需下载喂服务+失败可见(download_error)"
```

---

## Self-Review（作者自查，已执行）

**Spec coverage：** 下载函数与守卫（T1）、识别接入/临时文件生命周期/evidence_frame 回指/download_error 双落点（T2）、首轮不受影响（T2 测试3）、测试全套（T1 Step1 + T2 Step1）——spec 各节均有任务。预取队列为 spec 明确非目标，无任务，正确。

**Placeholder scan：** 无 TBD/TODO；每步含完整代码与确切锚点。

**Type consistency：** `download_media_to_temp(media_url, content_type)` 返回 `(Path|None, str|None)` 在 T1 定义、T2 按此消费；`MEDIA_SUFFIX_WHITELIST` T1 定义、T2 引用；测试断言的 `download_error`/`evidence_frame` 键名与实现一致；`unlink(missing_ok=True)` 为 Python 3.8+ 特性，本机 3.12/服务器 3.10 均可用。
