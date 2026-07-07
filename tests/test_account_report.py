import base64
from pathlib import Path
import importlib.util


def load_report():
    spec = importlib.util.spec_from_file_location("account_report", Path("account_report.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_report_is_self_contained_and_has_evidence(tmp_path):
    r = load_report()
    img = tmp_path / "frame.png"
    img.write_bytes(PNG_1PX)
    account = {"account_key": "小红书:seller", "platform": "小红书", "user_id": "seller",
               "nickname": "城南优选", "description": "主页有方式", "avatar_url": "",
               "high_post_count": 2, "post_count": 3, "max_post_score": 0.91,
               "violation_type": '["图像疑似售烟","文本交易引流"]', "reviewer": "张三", "review_time": "2026-07-07 10:00:00"}
    posts = [{
        "content": {"id": "p0", "title": "刚到一批", "content_type": "图片", "content_url": "https://x/p0",
                    "risk_score": 0.91, "risk_level": "高风险"},
        "text": {"hit_keywords": [{"word": "私信"}], "intent_type": "疑似交易引流"},
        "image": {"detected_objects": ["香烟包装"], "ocr_text": ["私聊"]},
        "audio": None, "fusion": {"risk_score": 0.91},
        "evidence_images": [str(img)], "evidence_audio": [],
    }]
    html_str = r.build_account_report_html(account, posts)
    assert "<!doctype html>" in html_str.lower()
    assert "城南优选" in html_str
    assert "data:image/png;base64," in html_str        # 证据内嵌
    assert "香烟包装" in html_str
    # 自包含：无外部资源引用
    assert 'src="http' not in html_str and "href=\"http" not in html_str
    assert "2/3" in html_str or "2 / 3" in html_str      # 命中计数展示
