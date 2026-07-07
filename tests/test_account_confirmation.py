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
