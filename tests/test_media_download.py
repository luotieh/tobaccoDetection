import importlib.util
import json
import tempfile
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
        elif self.path == "/blob":
            self._send(MP4_BYTES, "application/octet-stream")
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
    srv.server_close()


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


def test_download_suffix_fallback_from_content_type_label(media_server):
    m = load_app()
    path, err = m.download_media_to_temp(media_server + "/blob", "视频")
    assert err is None and path is not None and path.suffix == ".mp4"
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


def test_download_malformed_url_returns_error():
    m = load_app()
    path, err = m.download_media_to_temp("http://[::1", "视频")
    assert path is None and err


def test_download_size_cap_aborts_and_cleans(media_server):
    m = load_app()
    m.MEDIA_DOWNLOAD_MAX_MB = 0  # 上限 0MB：首个分块即超限
    tmp_dir = Path(tempfile.gettempdir())
    before = set(tmp_dir.glob("tobacco_media_*"))
    path, err = m.download_media_to_temp(media_server + "/v.mp4", "视频")
    assert path is None and "上限" in err
    assert set(tmp_dir.glob("tobacco_media_*")) == before  # 半成品临时文件已清理


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
