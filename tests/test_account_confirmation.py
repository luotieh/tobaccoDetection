import importlib.util
from pathlib import Path


def load_app():
    spec = importlib.util.spec_from_file_location("management_app_acct", Path("app.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_init_db_creates_accounts_and_content_columns(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    with m.db() as conn:
        acc_cols = m.table_columns(conn, "accounts")
        content_cols = m.table_columns(conn, "content_items")
    assert {"account_key", "platform", "user_id", "confirm_status",
            "confirm_batch_id", "high_post_count", "max_post_score",
            "report_path", "violation_type"} <= acc_cols
    assert {"account_key", "confirm_batch_id"} <= content_cols
    assert m.SECONDARY_HIGH_POST_COUNT == 2
    assert m.SECONDARY_MAX_SCORE_THRESHOLD == 0.85


def test_upsert_account_snapshot_and_no_status_regress(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    key = m.upsert_account("小红书", "seller",
                           user={"nickname": "城南优选", "description": "主页有方式", "avatarUrl": "http://x/a.jpg"},
                           status="awaiting_posts")
    assert key == "小红书:seller"
    acc = m.get_account(key)
    assert acc["nickname"] == "城南优选"
    assert acc["confirm_status"] == "awaiting_posts"
    # 推进到 recognizing
    m.upsert_account("小红书", "seller", status="recognizing", batch_id="B1")
    assert m.get_account(key)["confirm_status"] == "recognizing"
    assert m.get_account(key)["confirm_batch_id"] == "B1"
    # awaiting_posts 不应把 recognizing 回退
    m.upsert_account("小红书", "seller", status="awaiting_posts")
    assert m.get_account(key)["confirm_status"] == "recognizing"


def _note_post(pid, content="刚到一批，老客户私信"):
    return {"date": "2026-06-04 10:00:00", "url": f"https://x/{pid}", "title": "分享",
            "id": pid, "videoUrl": None, "imageList": [],
            "author": {"id": "seller", "nickname": "城南优选", "description": "主页有方式", "avatarUrl": ""},
            "content": content, "comments": []}


def _return_data_user(n=3):
    return {"platform": "小红书", "type": "note", "timeTook": 1.0,
            "user": {"id": "seller", "nickname": "城南优选", "description": "主页有方式", "avatarUrl": ""},
            "data": [_note_post(f"p{i}") for i in range(n)]}


def test_receive_user_posts_ingests_and_tags_batch(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    m.AUTO_RECOGNIZE = False  # 不启后台线程，保持确定性
    res = m.api_receive_user_posts("小红书", "seller", _return_data_user(3))
    assert res["success"] is True
    assert res["accepted"] == 3
    assert res["account_key"] == "小红书:seller"
    batch = res["confirm_batch_id"]
    acc = m.get_account("小红书:seller")
    assert acc["confirm_status"] == "recognizing"
    with m.db() as conn:
        rows = m.rows_to_list(conn.execute(
            "SELECT account_key, confirm_batch_id, recognize_status FROM content_items WHERE confirm_batch_id=?",
            (batch,)).fetchall())
    assert len(rows) == 3
    assert all(r["account_key"] == "小红书:seller" for r in rows)
    assert all(r["recognize_status"] == "pending" for r in rows)


def test_receive_user_posts_rejects_path_body_mismatch(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    res = m.api_receive_user_posts("小红书", "OTHER", _return_data_user(1))
    assert "error" in res and not res.get("success")


def test_batch_content_excluded_from_content_review_queue(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    m.AUTO_RECOGNIZE = False
    res = m.api_receive_user_posts("小红书", "seller", _return_data_user(2))
    batch = res["confirm_batch_id"]
    # 把批次内容置为高风险，验证仍不进内容审核队列
    with m.db() as conn:
        conn.execute("UPDATE content_items SET risk_level='高风险', risk_score=0.9 WHERE confirm_batch_id=?", (batch,))
    reviews = m.api_reviews({})
    assert all(item.get("risk_level") for item in reviews["items"])  # 队列本身正常
    ids_in_queue = {item["content_id"] for item in reviews["items"]}
    with m.db() as conn:
        batch_ids = {r["id"] for r in conn.execute("SELECT id FROM content_items WHERE confirm_batch_id=?", (batch,)).fetchall()}
    assert ids_in_queue.isdisjoint(batch_ids)
