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
