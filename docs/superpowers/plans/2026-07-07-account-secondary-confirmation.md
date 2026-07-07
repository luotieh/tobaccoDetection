# 账户二次确认闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 爬虫把高危账户的近 10 条多模态帖子 POST 回本平台新接口，识别聚合成账户级判定，人工审核后生成自包含 HTML 证据报告。

**Architecture:** 全部落在管理服务 `app.py`（标准库 + SQLite），识别复用现有异步后台循环与三个 FastAPI 识别服务；账户为一等实体（新增 `accounts` 表）；报告生成拆到独立模块 `account_report.py`（纯函数、可独立测试）。

**Tech Stack:** Python 3.10+ 标准库（`http.server`、`sqlite3`）、pytest。无新增第三方依赖。

## Global Constraints

- 不新增第三方依赖；报告为自包含 HTML（base64 内嵌证据，无外链），不引入 PDF 库。
- 不改视觉/文本/语音三个 FastAPI 服务及其 schema，不改 `analyze_fusion` 算法。
- 沿用现有迁移机制：整表用 `SCHEMA` 常量 `CREATE TABLE IF NOT EXISTS`；`content_items` 加列走 `CONTENT_ITEM_EXTRA_COLUMNS`。
- 沿用现有 DB 访问：`with db() as conn:`；辅助 `now()`、`new_id(prefix)`、`row_to_dict`、`rows_to_list`、`json_loads(value, default)`、`first_text(*values)`。
- 测试沿用 `tests/test_crawler_push.py` 的 `importlib` 载入 `app.py`、设 `DB_PATH`、`init_db()` 模式。
- 账户判定双信号阈值：`SECONDARY_HIGH_POST_COUNT=2`、`SECONDARY_MAX_SCORE_THRESHOLD=0.85`（env 可配）。
- `account_key = f"{platform}:{user_id}"`。
- 每个 `git commit` 结尾追加 trailer：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`（下方步骤为简洁用 `-m`，提交时补上 trailer）。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `app.py` | 修改 | schema/config、接收接口、账户 upsert/状态机、聚合器、账户端点、路由、recognize/feedback/reviews 挂钩 |
| `account_report.py` | 新建 | `build_account_report_html(account, posts)` 纯函数生成自包含 HTML |
| `docs/__init__.py` | 修改 | 新增 `ReturnDataUser` TypedDict 契约 |
| `tests/test_account_confirmation.py` | 新建 | schema/helpers/接收/聚合/feedback/端点/e2e |
| `tests/test_account_report.py` | 新建 | HTML 生成与自包含断言 |
| `static/app.js`、`static/index.html` | 修改 | 「账户二次确认」视图 |
| `.env.example` | 修改 | 新增配置项说明 |

---

## Task 1: 数据模型 — accounts 表 + content_items 列 + 配置

**Files:**
- Modify: `app.py` — `SCHEMA` 常量（`app.py:316` `push_logs` 之后、闭合 `"""` 之前）、`CONTENT_ITEM_EXTRA_COLUMNS`（`app.py:174-180`）、配置区（`app.py:63` 之后）
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Produces: `accounts` 表；`content_items.account_key`、`content_items.confirm_batch_id` 列；常量 `SECONDARY_HIGH_POST_COUNT`、`SECONDARY_MAX_SCORE_THRESHOLD`、`SECONDARY_EXPECTED_POSTS`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_account_confirmation.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_init_db_creates_accounts_and_content_columns -v`
Expected: FAIL（`accounts` 表不存在 / `AttributeError: SECONDARY_HIGH_POST_COUNT`）

- [ ] **Step 3: 加 accounts 表到 SCHEMA**

在 `app.py` `SCHEMA` 常量里 `push_logs` 表定义之后、结尾 `"""`（`app.py:316`）之前插入：

```sql

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
```

- [ ] **Step 4: 给 content_items 加列**

`app.py:174` `CONTENT_ITEM_EXTRA_COLUMNS` 字典末尾加两项：

```python
CONTENT_ITEM_EXTRA_COLUMNS = {
    "crawler_type": "TEXT DEFAULT ''",
    "crawler_id": "TEXT DEFAULT ''",
    "author_json": "TEXT DEFAULT ''",
    "media_list": "TEXT DEFAULT ''",
    "raw_payload": "TEXT DEFAULT ''",
    "account_key": "TEXT DEFAULT ''",
    "confirm_batch_id": "TEXT DEFAULT ''",
}
```

- [ ] **Step 5: 加配置常量**

在 `app.py:63`（`COMMENT_HIGH_RISK_THRESHOLD` 之后）加：

```python
# 账户二次确认：批次中高风险帖子数达此值即命中
SECONDARY_HIGH_POST_COUNT = int(os.environ.get("SECONDARY_HIGH_POST_COUNT", "2"))
# 账户二次确认：批次最高单帖综合分达此值即命中
SECONDARY_MAX_SCORE_THRESHOLD = float(os.environ.get("SECONDARY_MAX_SCORE_THRESHOLD", "0.85"))
# 账户二次确认：期望回推帖子数，仅用于日志/展示，不强校验
SECONDARY_EXPECTED_POSTS = int(os.environ.get("SECONDARY_EXPECTED_POSTS", "10"))
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_init_db_creates_accounts_and_content_columns -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): accounts 表 + content_items 批次列 + 二次确认配置"
```

---

## Task 2: ReturnDataUser 契约 + 账户 upsert/状态机

**Files:**
- Modify: `docs/__init__.py`（末尾追加 `ReturnDataUser`）
- Modify: `app.py`（在 `crawler_account_user_id` 之前，`app.py:2589` 附近，或紧跟辅助函数区加入账户辅助）
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `now`、`row_to_dict`、`first_text`、`db`（Task 现有）。
- Produces:
  - `account_key_of(platform, user_id) -> str`
  - `get_account(account_key) -> dict | None`
  - `upsert_account(platform, user_id, user=None, status=None, batch_id=None, conn=None) -> str`（返回 account_key；`status='awaiting_posts'` 不回退已推进状态）

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_upsert_account_snapshot_and_no_status_regress -v`
Expected: FAIL（`AttributeError: upsert_account`）

- [ ] **Step 3: 加账户辅助函数**

在 `app.py` `crawler_account_user_id`（`app.py:2590`）之前插入：

```python
def account_key_of(platform, user_id):
    return f"{platform}:{user_id}"


def get_account(account_key):
    with db() as conn:
        return row_to_dict(conn.execute("SELECT * FROM accounts WHERE account_key=?", (account_key,)).fetchone())


def _account_status_allows(current, new):
    # awaiting_posts 不回退已推进的状态；其余状态允许显式设置
    if new == "awaiting_posts":
        return current in ("", "awaiting_posts")
    return True


def upsert_account(platform, user_id, user=None, status=None, batch_id=None, conn=None):
    """建/更新账户实体。user 为 UserData 快照；status 走无回退规则；batch_id 更新当前批次。"""
    if conn is None:
        with db() as own:
            return upsert_account(platform, user_id, user=user, status=status, batch_id=batch_id, conn=own)
    key = account_key_of(platform, user_id)
    user = user if isinstance(user, dict) else {}
    t = now()
    existing = row_to_dict(conn.execute("SELECT * FROM accounts WHERE account_key=?", (key,)).fetchone())
    if existing is None:
        conn.execute(
            "INSERT INTO accounts (account_key,platform,user_id,nickname,description,avatar_url,"
            "confirm_status,confirm_batch_id,last_confirm_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (key, platform, user_id, first_text(user.get("nickname")), first_text(user.get("description")),
             first_text(user.get("avatarUrl")), status or "awaiting_posts", batch_id or "", t if batch_id else "", t, t),
        )
        return key
    sets = ["updated_at=?"]
    args = [t]
    if user:
        sets += ["nickname=?", "description=?", "avatar_url=?"]
        args += [first_text(user.get("nickname"), existing["nickname"]),
                 first_text(user.get("description"), existing["description"]),
                 first_text(user.get("avatarUrl"), existing["avatar_url"])]
    if status and _account_status_allows(existing["confirm_status"], status):
        sets.append("confirm_status=?")
        args.append(status)
    if batch_id:
        sets += ["confirm_batch_id=?", "last_confirm_at=?"]
        args += [batch_id, t]
    args.append(key)
    conn.execute(f"UPDATE accounts SET {','.join(sets)} WHERE account_key=?", args)
    return key
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_upsert_account_snapshot_and_no_status_regress -v`
Expected: PASS

- [ ] **Step 5: 追加 ReturnDataUser 契约**

`docs/__init__.py` 末尾（`ReturnData` 之后）追加：

```python
class ReturnDataUser(TypedDict):
    # 平台
    platform: str
    # 用户（被判定为高危、需二次确认的账户）
    user: UserData
    # 耗时
    timeTook: float
    # 返回数据类型
    type: str
    # 该用户近 10 条帖子（多模态）
    data: list[VideoData | NoteData]
```

- [ ] **Step 6: 提交**

```bash
git add app.py docs/__init__.py tests/test_account_confirmation.py
git commit -m "feat(account): ReturnDataUser 契约 + 账户 upsert/状态机辅助"
```

---

## Task 3: 接收接口 + 路由 + 排除内容审核队列

**Files:**
- Modify: `app.py` — 加 `api_receive_user_posts`（放在 `api_crawler_push` 之后，`app.py:2376` 附近）；`do_POST` 加路由（`app.py:1987` 之后）；import 加 `unquote`（`app.py:22`）；`api_reviews` WHERE（`app.py:2574`）
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `api_crawler_push`（返回 `{success, content_ids, created, updated}`）、`upsert_account`、`account_key_of`、`trigger_auto_recognize`、`new_id`、`first_text`。
- Produces: `api_receive_user_posts(platform, user_id, payload) -> dict`（成功含 `success/account_key/confirm_batch_id/accepted/skipped`；失败含 `error`）。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k receive_user_posts -v`
Expected: FAIL（`AttributeError: api_receive_user_posts`）

- [ ] **Step 3: import 加 unquote**

`app.py:22` 改为：

```python
from urllib.parse import parse_qs, unquote, urlparse
```

- [ ] **Step 4: 实现接收接口**

在 `api_crawler_push`（结束于 `app.py:2375`）之后插入：

```python
def api_receive_user_posts(platform, user_id, payload):
    """阶段③接收：爬虫回推某高危账户近 10 条多模态帖子（ReturnDataUser）。
    校验 → 建/更新账户(recognizing) → 生成批次 → 复用 crawler_push 入库并打批次标记 → 触发异步识别。"""
    if not isinstance(payload, dict):
        return {"error": "payload 必须为对象"}
    body_user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    body_uid = first_text(body_user.get("id"))
    body_platform = first_text(payload.get("platform"))
    if body_uid and body_uid != user_id:
        return {"error": "path user_id 与 body user.id 不一致"}
    if body_platform and body_platform != platform:
        return {"error": "path platform 与 body platform 不一致"}
    items = payload.get("data")
    if not isinstance(items, list) or not items:
        return {"error": "data 必须为非空列表"}
    batch_id = new_id("BATCH")
    key = account_key_of(platform, user_id)
    push = api_crawler_push({"platform": platform, "type": first_text(payload.get("type"), "content"), "data": items})
    content_ids = push.get("content_ids", []) if isinstance(push, dict) else []
    with db() as conn:
        for cid in content_ids:
            conn.execute("UPDATE content_items SET account_key=?, confirm_batch_id=?, updated_at=? WHERE id=?",
                         (key, batch_id, now(), cid))
        upsert_account(platform, user_id, user=body_user, status="recognizing", batch_id=batch_id, conn=conn)
    trigger_auto_recognize()
    return {"success": True, "account_key": key, "confirm_batch_id": batch_id,
            "accepted": len(content_ids), "skipped": max(0, len(items) - len(content_ids))}
```

- [ ] **Step 5: 加路由**

`do_POST` 中，`app.py:1987` 的 `/api/crawler/push` 分支之后插入：

```python
            if m := re.match(r"^/api/users/([^/]+)/([^/]+)$", path):
                result = api_receive_user_posts(unquote(m.group(1)), unquote(m.group(2)), payload)
                return self.send_json(result, 202 if result.get("success") else 400)
```

- [ ] **Step 6: api_reviews 排除批次内容**

`app.py:2574` 一行改为（内容审核队列排除二次确认批次帖子）：

```python
    where = " WHERE c.risk_level IN ('高风险','中风险') AND (c.confirm_batch_id IS NULL OR c.confirm_batch_id='')"
```

- [ ] **Step 7: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "receive_user_posts or review_queue" -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): POST /api/users/<platform>/<user_id> 接收 + 批次标记 + 排除内容审核队列"
```

---

## Task 4: 账户级聚合（双信号）+ 批次完成挂钩

**Files:**
- Modify: `app.py` — 加 `collect_violation_types`、`aggregate_account_confirmation`、`maybe_finalize_confirm_batch`（放在 `upsert_account` 之后）；`recognize_content` 末尾（`app.py:1599` `return` 之前）挂钩
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `SECONDARY_HIGH_POST_COUNT`、`SECONDARY_MAX_SCORE_THRESHOLD`、`rows_to_list`、`json_loads`。
- Produces:
  - `aggregate_account_confirmation(account_key, batch_id, rows=None) -> dict`（写账户聚合指标+状态，返回 `{confirm_status, high_post_count, max_post_score}`）
  - `maybe_finalize_confirm_batch(content) -> None`（批次全部到终态时触发聚合）

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "aggregate or finalize" -v`
Expected: FAIL（`AttributeError: aggregate_account_confirmation`）

- [ ] **Step 3: 实现聚合与挂钩函数**

在 `upsert_account` 之后插入：

```python
def collect_violation_types(conn, batch_id):
    """从批次内容的 fusion 识别结果里并集违规类型，best-effort。"""
    rows = rows_to_list(conn.execute(
        "SELECT rr.result_json FROM recognition_results rr "
        "JOIN content_items c ON c.id=rr.content_id "
        "WHERE c.confirm_batch_id=? AND rr.model_type='fusion'", (batch_id,)).fetchall())
    types = []
    for r in rows:
        data = json_loads(r["result_json"], {})
        for key in ("violation_type", "risk_types"):
            val = data.get(key)
            if isinstance(val, list):
                for v in val:
                    if v and v not in types:
                        types.append(v)
    return types


def aggregate_account_confirmation(account_key, batch_id, rows=None):
    """双信号聚合：count(高风险) 或 max(综合分) 达阈 → pending_review，否则 dismissed。"""
    with db() as conn:
        if rows is None:
            rows = rows_to_list(conn.execute(
                "SELECT recognize_status, risk_level, risk_score FROM content_items WHERE confirm_batch_id=?", (batch_id,)).fetchall())
        # 只按识别成功(completed)的帖子聚合；failed 帖子不计入高危信号
        completed = [r for r in rows if r["recognize_status"] == "completed"]
        high_post_count = sum(1 for r in completed if r["risk_level"] == "高风险")
        max_post_score = max([float(r["risk_score"] or 0) for r in completed], default=0.0)
        post_count = len(rows)
        hit = high_post_count >= SECONDARY_HIGH_POST_COUNT or max_post_score >= SECONDARY_MAX_SCORE_THRESHOLD
        status = "pending_review" if hit else "dismissed"
        violation = collect_violation_types(conn, batch_id)
        conn.execute(
            "UPDATE accounts SET account_risk_score=?, high_post_count=?, max_post_score=?, post_count=?, "
            "confirm_status=?, violation_type=?, updated_at=? WHERE account_key=? AND confirm_batch_id=?",
            (max_post_score, high_post_count, max_post_score, post_count, status,
             json.dumps(violation, ensure_ascii=False), now(), account_key, batch_id),
        )
    return {"confirm_status": status, "high_post_count": high_post_count, "max_post_score": max_post_score}


def maybe_finalize_confirm_batch(content):
    """某条帖子识别完成后：若属于二次确认批次且批次全部到终态(completed/failed)，触发账户聚合。"""
    batch_id = (content or {}).get("confirm_batch_id")
    account_key = (content or {}).get("account_key")
    if not batch_id or not account_key:
        return
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT recognize_status, risk_level, risk_score FROM content_items WHERE confirm_batch_id=?",
            (batch_id,)).fetchall())
    if not rows or any(r["recognize_status"] not in ("completed", "failed") for r in rows):
        return
    aggregate_account_confirmation(account_key, batch_id, rows)
```

- [ ] **Step 4: recognize_content 末尾挂钩**

`app.py:1599` `return get_content_detail(content_id)` 之前插入一行（`content` 为函数开头读入的行、含 `account_key`/`confirm_batch_id`）：

```python
    maybe_finalize_confirm_batch(content)
```

说明：后台识别为顺序处理（`drain_pending_recognition` 逐条），批次最后一条完成时才满足"全部终态"，聚合恰好触发一次，无需加锁。

- [ ] **Step 5: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "aggregate or finalize" -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): 双信号聚合 + 批次完成挂钩 recognize_content"
```

---

## Task 5: 阶段②衔接 — 上报高危用户时建账户

**Files:**
- Modify: `app.py` — `feedback_high_risk_account`（`app.py:2616`）成功取到 user_id 后 upsert 账户置 `awaiting_posts`
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `upsert_account`、`crawler_account_user_id`。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_feedback_creates_awaiting_account -v`
Expected: FAIL（`get_account` 返回 None）

- [ ] **Step 3: 在 feedback 中 upsert 账户**

`app.py:2621` `if not user_id:` 守卫返回之后、`payload = {...}`（`app.py:2623`）之前插入：

```python
    try:
        upsert_account(platform, user_id, status="awaiting_posts")
    except Exception as exc:
        sys.stderr.write("[account] upsert awaiting 失败 %s/%s: %s\n" % (platform, user_id, exc))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_feedback_creates_awaiting_account -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): 上报高危用户时建 awaiting_posts 账户（阶段②衔接）"
```

---

## Task 6: HTML 证据报告生成器（account_report.py）

**Files:**
- Create: `account_report.py`
- Test: `tests/test_account_report.py`

**Interfaces:**
- Produces: `build_account_report_html(account, posts) -> str`
  - `account`: accounts 行 dict（`nickname/platform/user_id/high_post_count/post_count/max_post_score/violation_type/reviewer/review_time` 等）
  - `posts`: `list[dict]`，每项 `{"content": <content 行 dict>, "text": dict|None, "image": dict|None, "audio": dict|None, "fusion": dict|None, "evidence_images": [abs_path,...], "evidence_audio": [abs_path,...]}`
  - 返回完整自包含 HTML 文档字符串（证据图以 `data:` URI 内嵌，无任何外链）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_account_report.py
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_report.py -v`
Expected: FAIL（`account_report.py` 不存在）

- [ ] **Step 3: 实现报告生成器**

```python
# account_report.py
"""账户级证据报告：把账户 + 其二次确认批次的多模态识别结果渲染为自包含 HTML。"""
import base64
import html
import json
from pathlib import Path

_IMG_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp", ".gif": "image/gif"}
_MAX_EMBED_BYTES = 3 * 1024 * 1024  # 单个证据文件超过则跳过内嵌，保持报告体积可控


def _img_data_uri(path):
    p = Path(path)
    try:
        if not p.is_file() or p.stat().st_size > _MAX_EMBED_BYTES:
            return ""
        mime = _IMG_MIME.get(p.suffix.lower())
        if not mime:
            return ""
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _esc(value):
    return html.escape(str(value if value is not None else ""))


def _parse_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _keywords(text_result):
    if not isinstance(text_result, dict):
        return []
    out = []
    for hit in text_result.get("hit_keywords", []) or []:
        if isinstance(hit, dict):
            out.append(hit.get("word", ""))
        else:
            out.append(str(hit))
    return [w for w in out if w]


def _post_card(post):
    content = post.get("content", {}) or {}
    parts = [f'<div class="card"><h3>{_esc(content.get("title") or content.get("id"))}'
             f' <span class="score">{_esc(content.get("risk_level"))} · {_esc(content.get("risk_score"))}</span></h3>']
    url = content.get("content_url")
    if url:
        parts.append(f'<p class="meta">类型：{_esc(content.get("content_type"))}　链接：{_esc(url)}</p>')
    kws = _keywords(post.get("text"))
    if kws:
        parts.append(f'<p><b>文本命中：</b>{_esc("、".join(kws))}</p>')
    image = post.get("image") or {}
    objs = image.get("detected_objects") or []
    if objs:
        parts.append(f'<p><b>检测对象：</b>{_esc("、".join(map(str, objs)))}</p>')
    ocr = image.get("ocr_text") or []
    if ocr:
        parts.append(f'<p><b>OCR：</b>{_esc("、".join(map(str, ocr)))}</p>')
    audio = post.get("audio") or {}
    if audio.get("transcript"):
        parts.append(f'<p><b>语音转写：</b>{_esc(audio.get("transcript"))}</p>')
    imgs = [uri for uri in (_img_data_uri(p) for p in post.get("evidence_images", []) or []) if uri]
    if imgs:
        parts.append('<div class="frames">' +
                     "".join(f'<img alt="证据帧" src="{uri}">' for uri in imgs) + "</div>")
    parts.append("</div>")
    return "".join(parts)


def build_account_report_html(account, posts):
    account = account or {}
    violations = _parse_list(account.get("violation_type"))
    cards = "".join(_post_card(p) for p in (posts or []))
    hit = _esc(account.get("high_post_count"))
    total = _esc(account.get("post_count"))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>账户证据报告 {_esc(account.get("account_key"))}</title>
<style>
 body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;margin:0;background:#f5f6fa;color:#1f2430}}
 .wrap{{max-width:920px;margin:0 auto;padding:24px}}
 header{{background:#0f2a52;color:#fff;padding:20px;border-radius:8px}}
 header h1{{margin:0 0 6px;font-size:20px}}
 .verdict{{background:#fff;border-left:4px solid #c0392b;padding:16px;margin:16px 0;border-radius:6px}}
 .card{{background:#fff;border:1px solid #e2e6ee;border-radius:6px;padding:14px;margin:12px 0}}
 .card h3{{margin:0 0 8px;font-size:16px}}
 .score{{color:#c0392b;font-size:13px;font-weight:normal}}
 .meta{{color:#6b7280;font-size:13px}}
 .frames img{{max-width:220px;max-height:220px;margin:6px 6px 0 0;border:1px solid #ddd;border-radius:4px}}
 .tag{{display:inline-block;background:#eef;border-radius:4px;padding:2px 8px;margin:2px;font-size:12px}}
</style></head><body><div class="wrap">
<header>
 <h1>烟草违法售卖账户证据报告</h1>
 <div>平台：{_esc(account.get("platform"))}　账号：{_esc(account.get("nickname"))}（{_esc(account.get("user_id"))}）</div>
 <div>{_esc(account.get("description"))}</div>
</header>
<div class="verdict">
 <div><b>账户级判定：</b>近 {total} 条中 <b>{hit}/{total}</b> 条高风险，最高单帖综合分 <b>{_esc(account.get("max_post_score"))}</b></div>
 <div><b>违规类型：</b>{"".join(f'<span class="tag">{_esc(v)}</span>' for v in violations) or "—"}</div>
 <div><b>审核：</b>{_esc(account.get("reviewer"))}　{_esc(account.get("review_time"))}</div>
</div>
<h2>逐帖证据</h2>
{cards or "<p>无帖子证据</p>"}
</div></body></html>"""
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_report.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add account_report.py tests/test_account_report.py
git commit -m "feat(account): 自包含 HTML 证据报告生成器"
```

---

## Task 7: 账户端点（列表/详情/审核/报告）+ 报告落盘

**Files:**
- Modify: `app.py` — 加 `generate_account_report`、`api_accounts`、`api_account_detail`、`api_account_review`、`api_account_report`（放在账户聚合函数之后）；`import account_report`（`app.py:22` 之后）；`do_GET`（`app.py:1941` 之后）与 `do_POST`（Task 3 users 路由之后）加路由
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `build_account_report_html`（Task 6）、`get_account`、`aggregate` 产出的账户字段、`ROOT`。
- Produces: `generate_account_report(account_key) -> str|None`（相对路径）、`api_accounts(qs)`、`api_account_detail(account_key)`、`api_account_review(account_key, payload)`、`api_account_report(account_key) -> str|None`（HTML）。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "account_review" -v`
Expected: FAIL（`AttributeError: api_accounts` / `api_account_review`）

- [ ] **Step 3: import 报告模块**

`app.py:22`（import 区）之后加：

```python
import account_report
```

- [ ] **Step 4: 实现端点与报告落盘**

在聚合函数（`maybe_finalize_confirm_batch`）之后插入：

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
    safe_key = account_key.replace(":", "_").replace("/", "_")
    report_dir = ROOT / "storage" / "reports" / safe_key
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{batch_id or 'latest'}.html"
    report_path.write_text(html_str, encoding="utf-8")
    rel = str(report_path.relative_to(ROOT))
    with db() as conn:
        conn.execute("UPDATE accounts SET report_path=?, updated_at=? WHERE account_key=?", (rel, now(), account_key))
    return rel


def api_accounts(qs):
    where, args = [], []
    if qs.get("confirm_status"):
        where.append("confirm_status=?"); args.append(qs["confirm_status"])
    if qs.get("platform"):
        where.append("platform=?"); args.append(qs["platform"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    with db() as conn:
        rows = rows_to_list(conn.execute(
            "SELECT * FROM accounts" + clause + " ORDER BY account_risk_score DESC, updated_at DESC", args).fetchall())
    return {"items": rows, "total": len(rows)}


def api_account_detail(account_key):
    with db() as conn:
        account = row_to_dict(conn.execute("SELECT * FROM accounts WHERE account_key=?", (account_key,)).fetchone())
        if not account:
            return None
        account["posts"] = rows_to_list(conn.execute(
            "SELECT id, title, content_type, content_url, risk_score, risk_level, recognize_status "
            "FROM content_items WHERE confirm_batch_id=? ORDER BY risk_score DESC", (account["confirm_batch_id"],)).fetchall())
    account["violation_type_parsed"] = json_loads(account.get("violation_type"), [])
    return account


def api_account_review(account_key, payload):
    status = payload.get("review_status", "confirmed")
    if status not in ("confirmed", "dismissed"):
        return {"error": "review_status 必须为 confirmed 或 dismissed"}
    with db() as conn:
        account = row_to_dict(conn.execute("SELECT account_key FROM accounts WHERE account_key=?", (account_key,)).fetchone())
        if not account:
            return {"error": "not found"}
        conn.execute("UPDATE accounts SET confirm_status=?, reviewer=?, review_opinion=?, review_time=?, updated_at=? "
                     "WHERE account_key=?",
                     (status, first_text(payload.get("reviewer"), "审核员"),
                      first_text(payload.get("review_opinion")), now(), now(), account_key))
    report_rel = None
    if status == "confirmed":
        try:
            report_rel = generate_account_report(account_key)
        except Exception as exc:
            sys.stderr.write("[account-report] %s 生成失败: %s\n" % (account_key, exc))
    return {"success": True, "account_key": account_key, "confirm_status": status, "report_path": report_rel}


def api_account_report(account_key):
    account = get_account(account_key)
    if not account:
        return None
    rel = account.get("report_path") or generate_account_report(account_key)
    if not rel:
        return None
    path = ROOT / rel
    return path.read_text(encoding="utf-8") if path.exists() else None
```

- [ ] **Step 5: 加 GET 路由**

`do_GET` 中 `app.py:1941` 的 `/api/push` 分支之后插入（report 路由须在通用 `<key>` 之前）：

```python
            if m := re.match(r"^/api/accounts/([^/]+)/report$", path):
                html_str = api_account_report(unquote(m.group(1)))
                return self.send_text(html_str, 200, "text/html; charset=utf-8") if html_str else self.send_json({"error": "not found"}, 404)
            if path == "/api/accounts":
                return self.send_json(api_accounts(qs))
            if m := re.match(r"^/api/accounts/([^/]+)$", path):
                detail = api_account_detail(unquote(m.group(1)))
                return self.send_json(detail or {"error": "not found"}, 200 if detail else 404)
```

- [ ] **Step 6: 加 POST 路由**

`do_POST` 中 Task 3 的 `/api/users/...` 路由之后插入：

```python
            if m := re.match(r"^/api/accounts/([^/]+)/review$", path):
                return self.send_json(api_account_review(unquote(m.group(1)), payload))
```

- [ ] **Step 7: 运行测试确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "account_review" -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(account): 账户列表/详情/审核/报告端点 + 报告落盘"
```

---

## Task 8: 前端「账户二次确认」视图

**Files:**
- Modify: `static/app.js`、`static/index.html`
- Verification: 手动冒烟（本仓库前端无单测）

- [ ] **Step 1: 读现有前端模式**

Read `static/index.html` 与 `static/app.js`，定位：hash 路由分发处、导航菜单结构、其它列表视图（如 `#reviews`）的渲染函数与 `fetch` 调用写法。新视图必须复用同样的路由注册、渲染、样式类。

- [ ] **Step 2: 加导航项**

`static/index.html` 菜单中「审核管理」附近加入口，`href="#accounts"`，文案「账户二次确认」。

- [ ] **Step 3: 加视图渲染（沿用现有 fetch/渲染风格）**

在 `static/app.js` 路由分发中注册 `#accounts`，实现列表 + 详情 + 审核。核心 API 调用（按现有 helper 风格改写）：

```javascript
// 列表：默认展示待账户审核
async function renderAccounts() {
  const data = await fetchJSON('/api/accounts?confirm_status=pending_review');
  // 渲染 data.items：account_key/nickname/platform/high_post_count/post_count/max_post_score/confirm_status
  // 每行「查看」→ location.hash = '#account/' + encodeURIComponent(account_key)
}

// 详情
async function renderAccountDetail(accountKey) {
  const acc = await fetchJSON('/api/accounts/' + encodeURIComponent(accountKey));
  // 渲染 acc.posts（逐帖 risk_level/risk_score）、acc.violation_type_parsed
  // 「确认违法」按钮：
  //   await postJSON('/api/accounts/' + encodeURIComponent(accountKey) + '/review',
  //                  {review_status:'confirmed', reviewer:'审核员'});
  // 「误报」按钮：review_status:'dismissed'
  // 报告链接：<a target="_blank" href="/api/accounts/{enc}/report">查看证据报告</a>
}
```

- [ ] **Step 4: 手动冒烟验证**

```bash
python3 app.py 8000 &
curl -s -X POST 'http://127.0.0.1:8000/api/users/小红书/seller' \
  -H 'Content-Type: application/json' \
  -d '{"platform":"小红书","type":"note","user":{"id":"seller","nickname":"城南优选"},"timeTook":1,"data":[{"id":"p1","title":"刚到一批","author":{"id":"seller","nickname":"城南优选"},"content":"刚到一批，老客户私信","imageList":[],"comments":[]}]}'
```
浏览器打开 `http://127.0.0.1:8000/#accounts`：确认列表能显示账户、详情能审核、审核确认后「查看证据报告」能打开 HTML。停服 `kill %1`。

- [ ] **Step 5: 提交**

```bash
git add static/app.js static/index.html
git commit -m "feat(account): 前端账户二次确认视图（列表/详情/审核/报告）"
```

---

## Task 9: 配置文档 + 端到端集成测试

**Files:**
- Modify: `.env.example`
- Test: `tests/test_account_confirmation.py`

- [ ] **Step 1: 写端到端失败测试**

```python
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
    res = m.api_receive_user_posts("小红书", "seller", payload)
    assert res["success"] and res["accepted"] == 3
    m.drain_pending_recognition()                       # 同步处理识别队列 → 触发聚合
    acc = m.get_account("小红书:seller")
    assert acc["confirm_status"] == "pending_review"
    assert acc["high_post_count"] == 3
    review = m.api_account_review("小红书:seller", {"review_status": "confirmed", "reviewer": "张三"})
    assert review["report_path"]
    assert (m.ROOT / review["report_path"]).exists()
```

- [ ] **Step 2: 运行测试确认失败或通过**

Run: `python3 -m pytest tests/test_account_confirmation.py::test_end_to_end_receive_recognize_confirm_report -v`
Expected: 若前面任务均已实现，应 PASS；若失败，按报错回到相应任务修复（这条是全链路回归）。

- [ ] **Step 3: 补 .env.example**

在 `.env.example` 里 `AUTO_FEEDBACK_ON_RECOGNIZE` 附近追加：

```bash
# 账户二次确认：批次中高风险帖子数达此值即判账户命中
SECONDARY_HIGH_POST_COUNT=${SECONDARY_HIGH_POST_COUNT:-2}
# 账户二次确认：批次最高单帖综合分达此值即判账户命中
SECONDARY_MAX_SCORE_THRESHOLD=${SECONDARY_MAX_SCORE_THRESHOLD:-0.85}
# 账户二次确认：期望回推帖子数，仅用于展示，不强校验
SECONDARY_EXPECTED_POSTS=${SECONDARY_EXPECTED_POSTS:-10}
```

- [ ] **Step 4: 全量回归**

Run: `python3 -m pytest -v`
Expected: 全绿（含既有 70 项与本次新增）

- [ ] **Step 5: 提交**

```bash
git add .env.example tests/test_account_confirmation.py
git commit -m "test(account): 二次确认闭环端到端集成测试 + .env.example 配置"
```

---

## Self-Review（作者自查，已执行）

**Spec coverage：** 阶段③接收(T3)、④聚合(T4)、⑤账户审核+推送入口(T7)、⑥HTML报告(T6/T7)、②衔接(T5)、accounts表+列(T1)、ReturnDataUser契约(T2)、排除内容审核队列(T3)、前端(T8)、配置+e2e(T9) —— spec 各节均有对应任务。监管推送沿用现有 mock（spec 非目标），未单列任务。

**Placeholder scan：** 无 TBD/TODO；每个改动步骤含完整代码与确切行号锚点。

**Type consistency：** `account_key_of`/`upsert_account`/`get_account`/`aggregate_account_confirmation`/`maybe_finalize_confirm_batch`/`generate_account_report`/`build_account_report_html(account, posts)` 在定义(T2/T4/T6/T7)与调用(T3/T7/T9)处签名一致；`confirm_status` 取值集合 `awaiting_posts/recognizing/pending_review/confirmed/dismissed` 全程一致；`content_items.confirm_batch_id`/`account_key` 列名一致。
