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
    res = m.api_receive_user_posts(_return_data_user(3))
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


def test_receive_user_posts_rejects_missing_identity(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    # platform / user.id 现在只来自 body，缺任一即拒绝(不再有 URL 路径参数)
    missing_uid = _return_data_user(1)
    missing_uid["user"] = {"id": "", "nickname": "x"}
    assert not m.api_receive_user_posts(missing_uid).get("success")
    missing_platform = _return_data_user(1)
    missing_platform["platform"] = ""
    assert not m.api_receive_user_posts(missing_platform).get("success")


def test_batch_content_excluded_from_content_review_queue(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    m.AUTO_RECOGNIZE = False
    res = m.api_receive_user_posts(_return_data_user(2))
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


def _seed_batch(m, batch="B1", key="小红书:seller", levels_scores=((("高风险", 0.9),) * 2)):
    m.upsert_account("小红书", "seller", status="recognizing", batch_id=batch)
    with m.db() as conn:
        for i, (level, score) in enumerate(levels_scores):
            conn.execute(
                "INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
                "risk_score,risk_level,account_key,confirm_batch_id,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"{batch}_{i}", "小红书", "文本", "t", "城南优选", "completed", score, level, key, batch, m.now(), m.now()),
            )


def test_aggregate_hits_on_count(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    _seed_batch(m, levels_scores=(("高风险", 0.9), ("高风险", 0.88)))
    out = m.aggregate_account_confirmation("小红书:seller", "B1")
    assert out["high_post_count"] == 2
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"


def test_aggregate_hits_on_max_score_even_if_count_low(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    _seed_batch(m, levels_scores=(("高风险", 0.9), ("中风险", 0.5)))  # 计数 1 < 2，但最高分 0.9 >= 0.85
    out = m.aggregate_account_confirmation("小红书:seller", "B1")
    assert out["high_post_count"] == 1
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"


def test_aggregate_hits_on_count_alone_below_max_threshold(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    # 2 条高风险但单帖分都 < 0.85：仅计数信号命中，最高分信号不命中
    _seed_batch(m, levels_scores=(("高风险", 0.6), ("高风险", 0.7)))
    out = m.aggregate_account_confirmation("小红书:seller", "B1")
    assert out["high_post_count"] == 2
    assert out["max_post_score"] < m.SECONDARY_MAX_SCORE_THRESHOLD
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"


def test_aggregate_dismisses_when_below_all_thresholds(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    _seed_batch(m, levels_scores=(("中风险", 0.5), ("低风险", 0.3)))
    m.aggregate_account_confirmation("小红书:seller", "B1")
    assert m.get_account("小红书:seller")["confirm_status"] == "dismissed"


def test_finalize_waits_until_all_terminal(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    _seed_batch(m, levels_scores=(("高风险", 0.9), ("高风险", 0.9)))
    with m.db() as conn:  # 其中一条仍在 pending
        conn.execute("UPDATE content_items SET recognize_status='pending' WHERE id='B1_1'")
    m.maybe_finalize_confirm_batch({"account_key": "小红书:seller", "confirm_batch_id": "B1"})
    assert m.get_account("小红书:seller")["confirm_status"] == "recognizing"  # 未聚合
    with m.db() as conn:  # 补齐终态（failed 也算终态）
        conn.execute("UPDATE content_items SET recognize_status='failed' WHERE id='B1_1'")
    m.maybe_finalize_confirm_batch({"account_key": "小红书:seller", "confirm_batch_id": "B1"})
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"


def test_feedback_creates_awaiting_account(tmp_path, monkeypatch):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    # 避免真实网络：桩掉出站 POST
    monkeypatch.setattr(m, "post_crawler_user_risk", lambda *a, **k: {"ok": True, "status_code": 200, "response": ""})
    content = {"platform": "小红书", "risk_score": 0.9,
               "author_json": '{"id": "seller", "nickname": "城南优选"}'}
    m.feedback_high_risk_account(content)
    acc = m.get_account("小红书:seller")
    assert acc is not None
    assert acc["confirm_status"] == "awaiting_posts"


def test_account_review_confirm_generates_report(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    # 造一个 pending_review 账户 + 批次内容
    m.upsert_account("小红书", "seller",
                     user={"nickname": "城南优选", "description": "主页有方式", "avatarUrl": ""},
                     status="recognizing", batch_id="B1")
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
                     "risk_score,risk_level,account_key,confirm_batch_id,created_at,updated_at) "
                     "VALUES ('B1_0','小红书','文本','刚到一批','城南优选','completed',0.9,'高风险','小红书:seller','B1',?,?)",
                     (m.now(), m.now()))
    m.aggregate_account_confirmation("小红书:seller", "B1")
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"
    # 列表按状态过滤
    listing = m.api_accounts({"confirm_status": "pending_review"})
    assert any(a["account_key"] == "小红书:seller" for a in listing["items"])
    # 审核确认 → 生成报告
    res = m.api_account_review("小红书:seller", {"review_status": "confirmed", "reviewer": "张三"})
    assert res["success"] and res["report_path"]
    assert (m.ROOT / res["report_path"]).exists()
    assert m.get_account("小红书:seller")["confirm_status"] == "confirmed"
    html_str = m.api_account_report("小红书:seller")
    assert html_str and "城南优选" in html_str


def test_account_review_dismiss_no_report(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.upsert_account("小红书", "seller", status="pending_review", batch_id="B1")
    res = m.api_account_review("小红书:seller", {"review_status": "dismissed", "reviewer": "李四"})
    assert res["success"] and not res["report_path"]
    assert m.get_account("小红书:seller")["confirm_status"] == "dismissed"


def _text_content_row(m, cid, batch_id="", account_key=""):
    with m.db() as conn:
        conn.execute(
            "INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
            "risk_score,risk_level,media_url,account_key,confirm_batch_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, "小红书", "文本", "刚到一批", "城南优选", "pending", 0, "无风险", "",
             account_key, batch_id, m.now(), m.now()),
        )


def test_recognize_content_skips_auto_feedback_for_batch_post(tmp_path, monkeypatch):
    """Fix 1 回归：confirm_batch_id 帖子识别为高风险后，不得再次触发爬虫账户反馈(否则造成
    接收->识别->反馈->接收 自激循环)；非批次帖子的反馈行为不能被这个改动误伤。"""
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.AUTO_FEEDBACK_ON_RECOGNIZE = True
    monkeypatch.setattr(m, "text_service_analyze_content",
                        lambda content: {"text_risk_score": 0.95, "model_version": "t",
                                         "hit_keywords": [{"word": "私信"}], "intent_type": "疑似交易引流"})
    monkeypatch.setattr(m, "score_content_comments", lambda content: {})
    calls = {"account": 0, "comment_users": 0}
    monkeypatch.setattr(m, "feedback_high_risk_account", lambda content: calls.__setitem__("account", calls["account"] + 1))
    monkeypatch.setattr(m, "feedback_high_risk_comment_users", lambda content: calls.__setitem__("comment_users", calls["comment_users"] + 1))

    # 批次帖子：带 confirm_batch_id/account_key，识别为高风险也不应触发反馈
    _text_content_row(m, "BATCH_0", batch_id="B1", account_key="小红书:seller")
    m.recognize_content("BATCH_0")
    assert calls["account"] == 0
    assert calls["comment_users"] == 0

    # 非批次帖子：无 confirm_batch_id，高风险识别应照常触发反馈(防止改动误伤正常路径)
    _text_content_row(m, "SOLO_0")
    m.recognize_content("SOLO_0")
    assert calls["account"] == 1
    assert calls["comment_users"] == 1


def test_aggregate_does_not_revert_human_reviewed_account(tmp_path):
    """Fix 2 回归：账户已被人工审核为 confirmed 后，若聚合被重新触发(如“全部重新识别”跑过批次里的
    最后一条帖子)，不能把人工结论打回 pending_review。"""
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    _seed_batch(m, levels_scores=(("高风险", 0.9), ("高风险", 0.88)))
    out = m.aggregate_account_confirmation("小红书:seller", "B1")
    assert out["high_post_count"] == 2
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"

    # 模拟人工审核：确认该账户
    review = m.api_account_review("小红书:seller", {"review_status": "confirmed", "reviewer": "张三"})
    assert review["success"]
    assert m.get_account("小红书:seller")["confirm_status"] == "confirmed"

    # 再次触发聚合(例如批次内容被重新识别，最后一条帖子完成后再次 finalize)
    m.aggregate_account_confirmation("小红书:seller", "B1")
    acc = m.get_account("小红书:seller")
    assert acc["confirm_status"] == "confirmed"  # 未被打回 pending_review
    assert acc["reviewer"] == "张三"


def test_end_to_end_receive_recognize_confirm_report(tmp_path, monkeypatch):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.AUTO_RECOGNIZE = False  # 手动 drain，确定性
    # 无外部服务：文本高分、评论空、无图无音（纯文本帖）
    monkeypatch.setattr(m, "text_service_analyze_content",
                        lambda content: {"text_risk_score": 0.95, "model_version": "t",
                                         "hit_keywords": [{"word": "私信"}], "intent_type": "疑似交易引流"})
    monkeypatch.setattr(m, "score_content_comments", lambda content: {})
    payload = {"platform": "小红书", "type": "note", "timeTook": 1.0,
               "user": {"id": "seller", "nickname": "城南优选", "description": "主页有方式", "avatarUrl": ""},
               "data": [{"date": "2026-06-04", "url": f"https://x/p{i}", "title": "刚到一批", "id": f"p{i}",
                         "videoUrl": None, "imageList": [],
                         "author": {"id": "seller", "nickname": "城南优选", "description": "主页有方式", "avatarUrl": ""},
                         "content": "刚到一批，老客户私信", "comments": []} for i in range(3)]}
    res = m.api_receive_user_posts(payload)
    assert res["success"] and res["accepted"] == 3
    m.drain_pending_recognition()                       # 同步处理识别队列 → 触发聚合
    acc = m.get_account("小红书:seller")
    assert acc["confirm_status"] == "pending_review"
    assert acc["high_post_count"] == 3
    review = m.api_account_review("小红书:seller", {"review_status": "confirmed", "reviewer": "张三"})
    assert review["report_path"]
    assert (m.ROOT / review["report_path"]).exists()


def test_new_id_unique_under_rapid_same_second_calls():
    # 回归：旧版 new_id 仅 3 位随机数，单秒内大量插入(如 drain 连续识别多条的 recognition_results)
    # 会 UNIQUE 冲突。5000 次快速调用必落在同一秒的时间戳前缀，故只有后缀能区分。
    m = load_app()
    ids = [m.new_id("RR") for _ in range(5000)]
    assert len(set(ids)) == len(ids)


def test_failed_post_still_finalizes_batch(tmp_path, monkeypatch):
    # 回归：批次里某帖识别抛异常被标 failed 时，drain 也要触发账户聚合，
    # 否则该帖恰为最后一条到终态者时账户会永远卡在 recognizing。
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"
    m.init_db()
    m.upsert_account("小红书", "seller", status="recognizing", batch_id="BF1")
    with m.db() as conn:
        for i, (st, lvl, sc) in enumerate([("completed", "高风险", 0.9), ("completed", "高风险", 0.9), ("pending", "无风险", 0.0)]):
            conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
                         "risk_score,risk_level,account_key,confirm_batch_id,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (f"BF1_{i}", "小红书", "文本", "t", "城南优选", st, sc, lvl, "小红书:seller", "BF1", m.now(), m.now()))

    def boom(cid):
        raise RuntimeError("recognition boom")

    monkeypatch.setattr(m, "recognize_content", boom)
    m.drain_pending_recognition()
    # 2 条 completed 高风险 → 双信号命中 → pending_review，而非卡在 recognizing
    assert m.get_account("小红书:seller")["confirm_status"] == "pending_review"
