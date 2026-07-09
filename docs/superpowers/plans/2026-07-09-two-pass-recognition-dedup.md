# 两阶段识别分流 + 账户去重 + 详情多模态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首次识别只跑 LLM 文本(粗筛)、二次确认批次跑全多模态；同一高危账户只上报爬虫一次；账户详情页展示每条批次帖子的多模态识别结果。

**Architecture:** 全部改 `app.py`(标准库 + SQLite)与 `static/app.js`(原生 JS)。识别分流以 `content["confirm_batch_id"]` 是否为空为准；账户去重用一个 in-pipeline 判定门控两个 feedback 函数；详情多模态复用报告的 posts 组装(抽成共享函数)。

**Tech Stack:** Python 3 标准库、pytest、原生 JS。无新增第三方依赖。

## Global Constraints

- 不新增第三方依赖（纯标准库 / 原生 JS）。
- 不改多模态识别算法、融合权重、`analyze_fusion` 逻辑。
- 识别分流判据：`content["confirm_batch_id"]` 为空=首次=只文本；非空=二次=全多模态。
- 评论打分 `score_content_comments` 两阶段都保留（文本类）。
- 账户级去重 in-pipeline 状态集：`{"awaiting_posts", "recognizing", "pending_review", "confirmed"}`；`dismissed` 或账户不存在 → 可上报。
- 前端复用 `escapeHtml` / `routeKey` / 现有样式类；证据图走现有 `/storage/evidence/<content_id>/*.jpg` 静态路由。
- 沿用现有 DB 访问 `with db() as conn:` 与辅助 `now()`/`new_id()`/`row_to_dict`/`rows_to_list`/`json_loads`/`get_account`/`account_key_of`/`upsert_account`。
- 每个 `git commit` 结尾追加 trailer：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `app.py` | 修改 | recognize_content 分流；api_receive_user_posts 批次重识别；账户去重(account_already_in_pipeline + 两 feedback);assemble_account_posts + account_evidence_url + api_account_detail 多模态 |
| `static/app.js` | 修改 | renderAccountDetail 逐帖多模态卡片 |
| `tests/test_account_confirmation.py` | 修改 | 分流/重识别/去重/详情多模态测试 |

---

## Task 1: 识别分流 + 批次重识别

**Files:**
- Modify: `app.py` — `recognize_content`(图像/语音块加 `confirm_batch_id` 门控)、`api_receive_user_posts`(批次 UPDATE 补 `recognize_status='pending'`)
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Produces: `recognize_content` 对无 `confirm_batch_id` 内容只写 `text`+`fusion` 识别结果、不调 `analyze_image_with_vision`/`audio_service_analyze_media`；`api_receive_user_posts` 把批次内容置 `recognize_status='pending'`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_account_confirmation.py` 末尾追加：

```python
def test_recognition_splits_by_pass(tmp_path, monkeypatch):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.AUTO_RECOGNIZE = False
    m.AUTO_FEEDBACK_ON_RECOGNIZE = False
    calls = {"image": 0, "audio": 0}
    monkeypatch.setattr(m, "analyze_image_with_vision",
                        lambda payload: (calls.__setitem__("image", calls["image"] + 1) or
                                         {"image_risk_score": 0.9, "model_version": "i", "detected_objects": [], "ocr_text": []}))
    monkeypatch.setattr(m, "audio_service_analyze_media",
                        lambda content, media_path: (calls.__setitem__("audio", calls["audio"] + 1) or
                                                     {"audio_risk_score": 0.8, "model_version": "a", "transcript": ""}))
    monkeypatch.setattr(m, "text_service_analyze_content",
                        lambda content: {"text_risk_score": 0.9, "model_version": "t", "hit_keywords": [], "intent_type": "疑似交易引流"})
    monkeypatch.setattr(m, "score_content_comments", lambda content: {})
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,media_url,recognize_status,created_at,updated_at) "
                     "VALUES ('FP1','小红书','图片','t','城南优选','/tmp/x.jpg','pending',?,?)", (m.now(), m.now()))
    m.recognize_content("FP1")  # 首次(无 batch) → 不跑图像/语音
    assert calls == {"image": 0, "audio": 0}
    with m.db() as conn:
        types = {r["model_type"] for r in conn.execute("SELECT model_type FROM recognition_results WHERE content_id='FP1'").fetchall()}
    assert types == {"text", "fusion"}
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,media_url,recognize_status,account_key,confirm_batch_id,created_at,updated_at) "
                     "VALUES ('SP1','小红书','图片','t','城南优选','/tmp/x.jpg','pending','小红书:seller','B1',?,?)", (m.now(), m.now()))
    m.recognize_content("SP1")  # 二次(有 batch) → 跑图像
    assert calls["image"] == 1
    with m.db() as conn:
        types2 = {r["model_type"] for r in conn.execute("SELECT model_type FROM recognition_results WHERE content_id='SP1'").fetchall()}
    assert "image" in types2


def test_batch_receive_resets_to_pending(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.AUTO_RECOGNIZE = False
    post = {"date": "2026-06-04", "url": "https://x/rp", "title": "t", "id": "rp", "videoUrl": None, "imageList": [],
            "author": {"id": "seller", "nickname": "城南优选"}, "content": "c", "comments": []}
    m.api_crawler_push({"platform": "小红书", "type": "note", "data": [post]})
    with m.db() as conn:
        cid = conn.execute("SELECT id FROM content_items LIMIT 1").fetchone()["id"]
        conn.execute("UPDATE content_items SET recognize_status='completed' WHERE id=?", (cid,))
    m.api_receive_user_posts({"platform": "小红书", "type": "note",
                              "user": {"id": "seller", "nickname": "城南优选"}, "data": [post]})
    with m.db() as conn:
        row = conn.execute("SELECT recognize_status, confirm_batch_id FROM content_items WHERE id=?", (cid,)).fetchone()
    assert row["recognize_status"] == "pending"
    assert row["confirm_batch_id"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "splits_by_pass or resets_to_pending" -v`
Expected: FAIL（首次仍调用了图像/含 image 结果；批次未重置 pending）

- [ ] **Step 3: recognize_content 图像/语音块加门控**

`app.py` `recognize_content` 中，将现有这段（`image_score=0` 起到 `audio_score = audio_result["audio_risk_score"]` 止）：

```python
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
```

替换为（图像/语音整体只在二次确认批次跑；首次只保留文本）：

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

（后续 `analyze_fusion` 调用不变：首次 `image_available=False, audio_available=False`，走单模态文本路径；结果写入循环遇 `None` 自动跳过 image/audio，首次只落 text+fusion。）

- [ ] **Step 4: api_receive_user_posts 重置 pending**

`app.py` `api_receive_user_posts` 里的批次标记 UPDATE：

```python
            conn.execute("UPDATE content_items SET account_key=?, confirm_batch_id=?, updated_at=? WHERE id=?",
                         (key, batch_id, now(), cid))
```

改为（补 `recognize_status='pending'`，使首次已识别过的同一帖子被重新按多模态识别）：

```python
            conn.execute("UPDATE content_items SET account_key=?, confirm_batch_id=?, recognize_status='pending', updated_at=? WHERE id=?",
                         (key, batch_id, now(), cid))
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "splits_by_pass or resets_to_pending" -v`
Expected: PASS。再跑全量 `python3 -m pytest -q` 确认无回归。

- [ ] **Step 6: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): 识别分流(首次文本/二次多模态) + 批次回推重置识别"
```

---

## Task 2: 账户级去重

**Files:**
- Modify: `app.py` — 新增 `account_already_in_pipeline`；`feedback_high_risk_account` 与 `feedback_high_risk_comment_users` 上报前去重
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `get_account`、`account_key_of`、`upsert_account`、`post_crawler_user_risk`。
- Produces: `account_already_in_pipeline(account_key) -> bool`；两个 feedback 函数对已在流程中的账户跳过上报。

- [ ] **Step 1: 写失败测试**

```python
def test_account_level_dedup_reports_once(tmp_path, monkeypatch):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    posted = []
    monkeypatch.setattr(m, "post_crawler_user_risk",
                        lambda platform, uid, score, timeout=5: (posted.append((platform, uid)) or {"ok": True, "status_code": 200, "response": ""}))
    content = {"platform": "小红书", "risk_score": 0.9, "author_json": '{"id": "seller", "nickname": "城南优选"}'}
    m.feedback_high_risk_account(content)
    m.feedback_high_risk_account(content)
    m.feedback_high_risk_account(content)
    assert posted == [("小红书", "seller")]  # 同账户只上报一次
    assert m.get_account("小红书:seller")["confirm_status"] == "awaiting_posts"


def test_dismissed_account_reportable_again(tmp_path, monkeypatch):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    posted = []
    monkeypatch.setattr(m, "post_crawler_user_risk",
                        lambda platform, uid, score, timeout=5: (posted.append(uid) or {"ok": True}))
    content = {"platform": "小红书", "risk_score": 0.9, "author_json": '{"id": "seller"}'}
    m.feedback_high_risk_account(content)
    assert len(posted) == 1
    m.upsert_account("小红书", "seller", status="dismissed")  # 人工误报
    m.feedback_high_risk_account(content)  # dismissed 不在流程中 → 可再次上报
    assert len(posted) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "dedup_reports_once or dismissed_account_reportable" -v`
Expected: FAIL（当前每次都上报，`posted` 长度不为 1）

- [ ] **Step 3: 新增 in-pipeline 判定**

在 `app.py` `feedback_high_risk_account` 之前插入：

```python
def account_already_in_pipeline(account_key):
    """账户是否已在二次确认流程中(已上报/识别中/待审/已确认)。用于账户级去重，避免同一账户重复上报爬虫。"""
    acc = get_account(account_key)
    return bool(acc) and acc.get("confirm_status") in ("awaiting_posts", "recognizing", "pending_review", "confirmed")
```

- [ ] **Step 4: feedback_high_risk_account 去重**

`app.py` `feedback_high_risk_account` 中，`if not user_id:` 的 return 之后、`try: upsert_account(...)` 之前插入：

```python
    if account_already_in_pipeline(account_key_of(platform, user_id)):
        return {"ok": True, "skipped": True, "reason": "账户已在二次确认流程中", "platform": platform, "id": user_id}
```

- [ ] **Step 5: feedback_high_risk_comment_users 去重 + 建账户**

`app.py` `feedback_high_risk_comment_users` 的上报循环：

```python
    for uid, info in best.items():
        try:
            result = post_crawler_user_risk(platform, uid, info["score"])
            if not result.get("ok"):
                sys.stderr.write("[crawler-feedback] 评论用户反馈失败 %s/%s: %s\n" % (platform, uid, result))
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            sys.stderr.write("[crawler-feedback] 评论用户反馈异常 %s/%s: %s\n" % (platform, uid, exc))
        feedbacks.append({"platform": platform, "id": uid, "risk_score": info["score"], "comment_level": info["comment_level"], **result})
```

替换为（已在流程中的评论用户账户跳过；否则建账户 awaiting_posts 再上报，使其后续可去重）：

```python
    for uid, info in best.items():
        if account_already_in_pipeline(account_key_of(platform, uid)):
            feedbacks.append({"platform": platform, "id": uid, "risk_score": info["score"],
                              "comment_level": info["comment_level"], "ok": True, "skipped": True,
                              "reason": "账户已在二次确认流程中"})
            continue
        try:
            upsert_account(platform, uid, status="awaiting_posts")
        except Exception as exc:
            sys.stderr.write("[account] upsert awaiting 失败 %s/%s: %s\n" % (platform, uid, exc))
        try:
            result = post_crawler_user_risk(platform, uid, info["score"])
            if not result.get("ok"):
                sys.stderr.write("[crawler-feedback] 评论用户反馈失败 %s/%s: %s\n" % (platform, uid, result))
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            sys.stderr.write("[crawler-feedback] 评论用户反馈异常 %s/%s: %s\n" % (platform, uid, exc))
        feedbacks.append({"platform": platform, "id": uid, "risk_score": info["score"], "comment_level": info["comment_level"], **result})
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "dedup_reports_once or dismissed_account_reportable" -v`
Expected: PASS。全量 `python3 -m pytest -q` 无回归。

- [ ] **Step 7: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): 账户级去重——同一高危账户只上报爬虫一次"
```

---

## Task 3: 共享 posts 组装 + 账户详情多模态

**Files:**
- Modify: `app.py` — 新增 `assemble_account_posts`、`account_evidence_url`；`generate_account_report` 复用之；`api_account_detail` 返回逐帖多模态
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `get_account`、`json_loads`、`ROOT`、`account_report.build_account_report_html`。
- Produces: `assemble_account_posts(account) -> list[dict]`（每项 `{content, text, image, audio, fusion, evidence_images(abs paths), evidence_audio}`）；`api_account_detail` 的 `posts` 每项含多模态字段与 `evidence_images`(可服务 URL)。

- [ ] **Step 1: 写失败测试**

```python
def test_account_detail_includes_multimodal(tmp_path):
    import json
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.upsert_account("小红书", "seller", user={"nickname": "城南优选"}, status="pending_review", batch_id="B1")
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,risk_score,risk_level,recognize_status,account_key,confirm_batch_id,created_at,updated_at) "
                     "VALUES ('B1_0','小红书','图片','刚到一批','城南优选',0.9,'高风险','completed','小红书:seller','B1',?,?)", (m.now(), m.now()))
        for typ, data in [("text", {"hit_keywords": [{"word": "私信"}], "intent_type": "疑似交易引流", "model_version": "t"}),
                          ("image", {"detected_objects": ["香烟包装"], "ocr_text": ["私聊"], "model_version": "i"}),
                          ("fusion", {"risk_score": 0.9, "model_version": "f"})]:
            conn.execute("INSERT INTO recognition_results VALUES (?,?,?,?,?,?,?)",
                         (m.new_id("RR"), "B1_0", typ, "v", 0.9, json.dumps(data, ensure_ascii=False), m.now()))
    detail = m.api_account_detail("小红书:seller")
    posts = detail["posts"]
    assert len(posts) == 1
    p = posts[0]
    assert p["text"]["intent_type"] == "疑似交易引流"
    assert p["image"]["detected_objects"] == ["香烟包装"]
    assert p["fusion"]["risk_score"] == 0.9
    assert p["id"] == "B1_0" and p["risk_level"] == "高风险"


def test_assemble_account_posts_returns_batch(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.upsert_account("小红书", "seller", status="pending_review", batch_id="B1")
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,risk_score,risk_level,recognize_status,account_key,confirm_batch_id,created_at,updated_at) "
                     "VALUES ('B1_0','小红书','文本','t','城南优选',0.9,'高风险','completed','小红书:seller','B1',?,?)", (m.now(), m.now()))
    posts = m.assemble_account_posts(m.get_account("小红书:seller"))
    assert len(posts) == 1 and posts[0]["content"]["id"] == "B1_0"
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "detail_includes_multimodal or assemble_account_posts" -v`
Expected: FAIL（`AttributeError: assemble_account_posts`；detail 无 text/image/fusion 字段）

- [ ] **Step 3: 新增 assemble_account_posts + account_evidence_url**

在 `app.py` `generate_account_report` 之前插入：

```python
def assemble_account_posts(account):
    """组装某账户当前批次的帖子 + 多模态识别结果(text/image/audio/fusion) + 证据文件路径。
    供 api_account_detail 展示与 generate_account_report 渲染共用。"""
    batch_id = (account or {}).get("confirm_batch_id")
    with db() as conn:
        contents = rows_to_list(conn.execute(
            "SELECT * FROM content_items WHERE confirm_batch_id=? ORDER BY risk_score DESC", (batch_id,)).fetchall())
        results = {}
        for c in contents:
            rrs = rows_to_list(conn.execute(
                "SELECT model_type, result_json FROM recognition_results WHERE content_id=?", (c["id"],)).fetchall())
            results[c["id"]] = {r["model_type"]: json_loads(r["result_json"], {}) for r in rrs}
    posts = []
    for c in contents:
        by_type = results.get(c["id"], {})
        ev_dir = ROOT / "storage" / "evidence" / c["id"]
        audio_dir = ROOT / "audio_storage" / "evidence" / c["id"]
        posts.append({
            "content": c,
            "text": by_type.get("text"), "image": by_type.get("image"),
            "audio": by_type.get("audio"), "fusion": by_type.get("fusion"),
            "evidence_images": [str(p) for p in sorted(ev_dir.glob("*.jpg"))] if ev_dir.exists() else [],
            "evidence_audio": [str(p) for p in sorted(audio_dir.glob("*.wav"))] if audio_dir.exists() else [],
        })
    return posts


def account_evidence_url(abs_path):
    """把证据文件绝对路径转成前端可访问的 /storage/... URL(经现有静态路由)。"""
    try:
        return "/" + str(Path(abs_path).resolve().relative_to(ROOT))
    except (ValueError, OSError):
        return ""
```

- [ ] **Step 4: generate_account_report 复用**

`app.py` `generate_account_report` 开头这段：

```python
def generate_account_report(account_key):
    """组装账户 + 批次帖子识别结果 + 证据文件，渲染 HTML 落盘，返回相对路径。"""
    with db() as conn:
        account = row_to_dict(conn.execute("SELECT * FROM accounts WHERE account_key=?", (account_key,)).fetchone())
        if not account:
            return None
        batch_id = account["confirm_batch_id"]
        contents = rows_to_list(conn.execute(
            "SELECT * FROM content_items WHERE confirm_batch_id=? ORDER BY risk_score DESC", (batch_id,)).fetchall())
        results = {}
        for c in contents:
            rrs = rows_to_list(conn.execute(
                "SELECT model_type, result_json FROM recognition_results WHERE content_id=?", (c["id"],)).fetchall())
            results[c["id"]] = {r["model_type"]: json_loads(r["result_json"], {}) for r in rrs}
    posts = []
    for c in contents:
        by_type = results.get(c["id"], {})
        ev_dir = ROOT / "storage" / "evidence" / c["id"]
        audio_dir = ROOT / "audio_storage" / "evidence" / c["id"]
        posts.append({
            "content": c,
            "text": by_type.get("text"), "image": by_type.get("image"),
            "audio": by_type.get("audio"), "fusion": by_type.get("fusion"),
            "evidence_images": [str(p) for p in sorted(ev_dir.glob("*.jpg"))] if ev_dir.exists() else [],
            "evidence_audio": [str(p) for p in sorted(audio_dir.glob("*.wav"))] if audio_dir.exists() else [],
        })
    html_str = account_report.build_account_report_html(account, posts)
```

替换为（复用共享函数）：

```python
def generate_account_report(account_key):
    """组装账户 + 批次帖子识别结果 + 证据文件，渲染 HTML 落盘，返回相对路径。"""
    account = get_account(account_key)
    if not account:
        return None
    batch_id = account["confirm_batch_id"]
    posts = assemble_account_posts(account)
    html_str = account_report.build_account_report_html(account, posts)
```

（`generate_account_report` 后半段 `safe_key = ...` 起不变。）

- [ ] **Step 5: api_account_detail 返回多模态**

`app.py` `api_account_detail` 整体替换为：

```python
def api_account_detail(account_key):
    account = get_account(account_key)
    if not account:
        return None
    posts = []
    for p in assemble_account_posts(account):
        c = p["content"]
        posts.append({
            "id": c["id"], "title": c["title"], "content_type": c["content_type"],
            "content_url": c["content_url"], "risk_score": c["risk_score"],
            "risk_level": c["risk_level"], "recognize_status": c["recognize_status"],
            "text": p["text"], "image": p["image"], "audio": p["audio"], "fusion": p["fusion"],
            "evidence_images": [u for u in (account_evidence_url(x) for x in p["evidence_images"]) if u],
        })
    account["posts"] = posts
    account["violation_type_parsed"] = json_loads(account.get("violation_type"), [])
    return account
```

- [ ] **Step 6: 运行确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "detail_includes_multimodal or assemble_account_posts or account_review" -v`
Expected: PASS（含既有 `test_account_review_confirm_generates_report` 确认报告不回归）。全量 `python3 -m pytest -q` 无回归。

- [ ] **Step 7: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "refactor(account): 抽 assemble_account_posts 共享 + 账户详情返回逐帖多模态"
```

---

## Task 4: 前端账户详情逐帖多模态卡片

**Files:**
- Modify: `static/app.js` — 新增 `accountPostMultimodal(p)`；`renderAccountDetail` 用它渲染逐帖多模态
- Verification: 手动冒烟（本仓库前端无单测）

- [ ] **Step 1: 读现有前端账户详情**

Read `static/app.js` 的 `renderAccountDetail`（约 `function renderAccountDetail`）与 `accountPostsTable`、`escapeHtml`、`riskTag`、`routeKey`、`api()` 定义，确认复用它们的写法与政务后台样式类。

- [ ] **Step 2: 新增逐帖多模态渲染函数**

在 `static/app.js` `accountPostsTable` 附近新增：

```javascript
function accountPostMultimodal(p) {
  const parts = [];
  const kw = ((p.text && p.text.hit_keywords) || []).map(h => (h && typeof h === "object") ? h.word : h).filter(Boolean);
  if (kw.length) parts.push(`<div><b>文本命中：</b>${escapeHtml(kw.join("、"))}</div>`);
  if (p.text && p.text.intent_type) parts.push(`<div><b>交易意图：</b>${escapeHtml(p.text.intent_type)}</div>`);
  const objs = (p.image && p.image.detected_objects) || [];
  if (objs.length) parts.push(`<div><b>检测对象：</b>${escapeHtml(objs.join("、"))}</div>`);
  const ocr = (p.image && p.image.ocr_text) || [];
  if (ocr.length) parts.push(`<div><b>OCR：</b>${escapeHtml(ocr.join("、"))}</div>`);
  if (p.audio && p.audio.transcript) parts.push(`<div><b>语音转写：</b>${escapeHtml(p.audio.transcript)}</div>`);
  const imgs = (p.evidence_images || [])
    .map(u => `<img src="${escapeHtml(u)}" alt="证据帧" style="max-width:160px;max-height:160px;margin:4px;border:1px solid #ddd;border-radius:4px">`)
    .join("");
  if (imgs) parts.push(`<div>${imgs}</div>`);
  return `<div class="panel" style="margin:8px 0">
    <h4 style="margin:0 0 6px">${escapeHtml(p.title || p.id)} <span style="font-weight:normal;color:#c0392b">${riskTag(p.risk_level)} · ${Number(p.risk_score || 0).toFixed(2)}</span></h4>
    ${parts.join("") || "<div class='meta'>该帖未命中多模态特征</div>"}</div>`;
}
```

- [ ] **Step 3: renderAccountDetail 渲染逐帖多模态**

`static/app.js` `renderAccountDetail` 里的批次帖子面板：

```javascript
    <div class="panel"><h3 class="section-title">批次帖子（${(acc.posts || []).length}）</h3><div class="table-wrap">${accountPostsTable(acc.posts || [])}</div></div>
```

替换为（概览表 + 逐帖多模态证据）：

```javascript
    <div class="panel"><h3 class="section-title">批次帖子（${(acc.posts || []).length}）</h3><div class="table-wrap">${accountPostsTable(acc.posts || [])}</div></div>
    <div class="panel"><h3 class="section-title">逐帖多模态证据</h3>${(acc.posts || []).map(accountPostMultimodal).join("") || "<p class='meta'>暂无帖子</p>"}</div>
```

- [ ] **Step 4: 手动冒烟验证**

```bash
node --check static/app.js
python3 app.py 8777 &
# 造一个 pending_review 账户 + 带多模态结果的批次帖(直接写库或走接口)，然后：
curl --noproxy '*' -s 'http://127.0.0.1:8777/api/accounts/%E5%B0%8F%E7%BA%A2%E4%B9%A6:seller' | head -c 400
curl --noproxy '*' -s http://127.0.0.1:8777/static/app.js | grep -c accountPostMultimodal
kill %1
```
浏览器打开 `http://127.0.0.1:8777/#account/<encoded key>`：确认详情页出现「逐帖多模态证据」，每帖显示文本命中/检测对象/OCR/证据帧。无法交互验证的部分如实说明。

- [ ] **Step 5: 提交**

```bash
git add static/app.js
git commit -m "feat(account): 前端账户详情逐帖多模态证据卡片"
```

---

## Self-Review（作者自查，已执行）

**Spec coverage：** ①识别分流(T1)、批次重识别(T1)、②账户级去重含评论用户(T2)、③assemble_account_posts 共享 + api_account_detail 多模态(T3)、前端逐帖多模态(T4)——spec 各节均有对应任务。评论打分保留(T1 未动 score_content_comments)。

**Placeholder scan：** 无 TBD/TODO；每步含完整代码与确切替换锚点。

**Type consistency：** `account_already_in_pipeline(account_key)->bool`(T2 定义/T2 调用)、`assemble_account_posts(account)->list`(T3 定义、generate_account_report/api_account_detail 调用)、`account_evidence_url(abs_path)->str`(T3)、前端 `accountPostMultimodal(p)`(T4 定义/调用) 全程签名一致；in-pipeline 状态集与 spec 一致；`confirm_batch_id` 判据一致。
