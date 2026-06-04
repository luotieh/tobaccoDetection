import importlib.util
from pathlib import Path


def load_management_app():
    spec = importlib.util.spec_from_file_location("management_app_crawler", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_crawler_push_accepts_docs_payload_and_comments(tmp_path):
    management = load_management_app()
    management.DB_PATH = tmp_path / "demo.db"
    management.init_db()

    payload = {
        "platform": "小红书",
        "type": "note",
        "timeTook": 1.2,
        "data": [
            {
                "date": "2026-06-04 10:00:00",
                "url": "https://example.com/note/abc",
                "title": "到货分享",
                "id": "abc",
                "videoUrl": None,
                "imageList": ["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"],
                "author": {
                    "id": "u1",
                    "nickname": "城南优选",
                    "description": "本地生活",
                    "avatarUrl": "https://cdn.example.com/avatar.jpg",
                },
                "content": "刚到一批，老客户私信。",
                "comments": [
                    {
                        "date": "2026-06-04 10:01:00",
                        "id": "c1",
                        "sender": {
                            "id": "u2",
                            "nickname": "买家",
                            "description": None,
                            "avatarUrl": "https://cdn.example.com/u2.jpg",
                        },
                        "content": "多少钱一条",
                        "subComments": [
                            {
                                "date": "2026-06-04 10:02:00",
                                "id": "c2",
                                "sender": {
                                    "id": "u1",
                                    "nickname": "城南优选",
                                    "description": "本地生活",
                                    "avatarUrl": "https://cdn.example.com/avatar.jpg",
                                },
                                "content": "私聊",
                                "parentId": "c1",
                            }
                        ],
                        "parentId": "abc",
                    }
                ],
            }
        ],
    }

    result = management.api_crawler_push(payload)

    assert result["success"] is True
    assert result["created"] == 1
    assert result["updated"] == 0
    content_id = result["content_ids"][0]
    detail = management.get_content_detail(content_id)
    assert detail["content"]["platform"] == "小红书"
    assert detail["content"]["content_type"] == "图片"
    assert detail["content"]["crawler_id"] == "abc"
    assert detail["content"]["media_url"] == "https://cdn.example.com/a.jpg"
    assert detail["content"]["media_list_parsed"] == ["https://cdn.example.com/a.jpg", "https://cdn.example.com/b.jpg"]
    assert detail["content"]["author"]["nickname"] == "城南优选"
    assert [item["content"] for item in detail["comments"]] == ["多少钱一条", "私聊"]


def test_crawler_push_upserts_existing_content(tmp_path):
    management = load_management_app()
    management.DB_PATH = tmp_path / "demo.db"
    management.init_db()

    payload = {
        "platform": "抖音",
        "type": "video",
        "timeTook": 0.5,
        "data": [
            {
                "date": "2026-06-04",
                "url": "https://example.com/video/v1",
                "title": "旧标题",
                "id": "v1",
                "coverUrl": "https://cdn.example.com/cover.jpg",
                "mediaList": ["https://cdn.example.com/v1.mp4"],
                "author": {"id": "a1", "nickname": "作者", "description": None, "avatarUrl": ""},
                "description": "旧内容",
                "comments": [],
            }
        ],
    }

    first = management.api_crawler_push(payload)
    payload["data"][0]["title"] = "新标题"
    payload["data"][0]["description"] = "新内容"
    second = management.api_crawler_push(payload)

    assert first["created"] == 1
    assert second["created"] == 0
    assert second["updated"] == 1
    detail = management.get_content_detail(second["content_ids"][0])
    assert detail["content"]["content_type"] == "视频"
    assert detail["content"]["title"] == "新标题"
    assert detail["content"]["raw_text"] == "新内容"


def test_text_service_payload_includes_crawler_comments_and_author_bio(tmp_path, monkeypatch):
    management = load_management_app()
    management.DB_PATH = tmp_path / "demo.db"
    management.init_db()
    payload = {
        "platform": "小红书",
        "type": "note",
        "timeTook": 1.2,
        "data": [
            {
                "date": "2026-06-04 10:00:00",
                "url": "https://example.com/note/text",
                "title": "普通标题",
                "id": "text",
                "videoUrl": None,
                "imageList": [],
                "author": {
                    "id": "seller",
                    "nickname": "普通作者",
                    "description": "主页有方式",
                    "avatarUrl": "",
                },
                "content": "普通正文",
                "comments": [
                    {
                        "date": "2026-06-04 10:01:00",
                        "id": "c1",
                        "sender": {"id": "buyer", "nickname": "买家", "description": "想要一条", "avatarUrl": ""},
                        "content": "多少钱一条",
                        "subComments": [
                            {
                                "date": "2026-06-04 10:02:00",
                                "id": "c2",
                                "sender": {"id": "seller", "nickname": "普通作者", "description": "主页有方式", "avatarUrl": ""},
                                "content": "私聊",
                                "parentId": "c1",
                            }
                        ],
                        "parentId": "text",
                    }
                ],
            }
        ],
    }
    content_id = management.api_crawler_push(payload)["content_ids"][0]
    content = management.get_content_detail(content_id)["content"]
    captured = {}

    def fake_service_post_json(base_url, path, body, timeout=30):
        captured["body"] = body
        return {
            "content_id": body["content_id"],
            "text_score": 0.0,
            "risk_level": "none",
            "risk_types": ["normal_discussion"],
            "hit_keywords": [],
            "brand_entities": [],
            "contact_entities": [],
            "field_results": [],
            "explanation": "未发现明显烟草交易风险表达。",
            "model_version": "text-risk-v0.1.0",
        }

    monkeypatch.setattr(management, "service_post_json", fake_service_post_json)
    result = management.text_service_analyze_content(content)

    assert captured["body"]["account_bio"] == "主页有方式"
    assert captured["body"]["comments"] == ["买家 想要一条 多少钱一条", "普通作者 主页有方式 私聊"]
    assert result["text_risk_score"] >= 0.5
    assert {"一条", "私聊"}.issubset({item["word"] for item in result["hit_keywords"]})
