# 两阶段两表 UI 重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 UI 重构成两张表——表1(首次推送·文本粗筛,只读监控)与表2(二次确认·多模态,人工确认一键存档+推送监管);内容级审核导航退役;工作台改两阶段漏斗。

**Architecture:** 改 `app.py`(`api_contents` 加 `pass` 过滤、`api_account_review` confirmed 一键推送)与 `static/app.js`(导航、表1、表2、工作台)。复用现有 push 三件套与识别分流。

**Tech Stack:** Python 3 标准库、pytest、原生 JS。无新增第三方依赖。

## Global Constraints

- 不新增第三方依赖（纯标准库 / 原生 JS）；不改多模态识别/融合算法/识别分流。
- `api_contents` 的 `pass`：`first` → `AND (confirm_batch_id IS NULL OR confirm_batch_id='')`；`second` → `AND confirm_batch_id<>''`；缺省不加（向后兼容）。
- `api_account_review` 的 `confirmed`：生成证据报告后，`api_create_push(account_key)` + `api_send_push(push["id"])` 一键推送监管，返回体加 `push`。
- 导航从 `menus` 移除 `["reviews","审核管理"]`（`reviews` 路由与 `renderReviews` 代码**保留不删**）；`contents`→「表1 · 首次推送」、`accounts`→「表2 · 二次确认」。
- 前端无单测 → `node --check` + 起服务 live 冒烟；用户可控文本进 DOM 前 `escapeHtml`。
- 沿用现有 helper：`escapeHtml`/`riskTag`/`statusTag`/`routeKey`/`api`/`bars`/`api_create_push`/`api_send_push`。
- 每个 `git commit` 结尾 trailer：`Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`。

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `app.py` | 修改 | `api_contents` 加 `pass` 过滤；`api_account_review` confirmed 一键推送 |
| `static/app.js` | 修改 | `menus` 导航；表1(`renderContents`/`contentsQuery`/`contentsTable`)；表2(`renderAccounts`/`saveAccountReview`)；工作台(`renderDashboard`)漏斗 |
| `tests/test_account_confirmation.py` | 修改 | `pass` 过滤 + 一键推送测试 |

---

## Task 1: 后端 —— api_contents pass 过滤 + api_account_review 一键推送

**Files:**
- Modify: `app.py` — `api_contents`（keyword 过滤块之后加 `pass`）、`api_account_review`（confirmed 分支加一键推送）
- Test: `tests/test_account_confirmation.py`

**Interfaces:**
- Consumes: `api_create_push(content_id)`、`api_send_push(push_id)`（现有）、`generate_account_report`。
- Produces: `api_contents(qs)` 支持 `qs["pass"]∈{first,second}`；`api_account_review(...)` 返回体新增 `push`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_account_confirmation.py` 末尾追加：

```python
def test_api_contents_pass_filter(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()  # init_db 播种首次内容(confirm_batch_id='')
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,recognize_status,"
                     "confirm_batch_id,created_at,updated_at,collect_time) "
                     "VALUES ('SP1','小红书','图片','t','a','completed','B1',?,?,?)", (m.now(), m.now(), m.now()))
    first = m.api_contents({"pass": "first", "page_size": "500"})
    second = m.api_contents({"pass": "second", "page_size": "500"})
    first_ids = {r["id"] for r in first["items"]}
    second_ids = {r["id"] for r in second["items"]}
    assert "SP1" in second_ids and "SP1" not in first_ids
    assert first_ids and all(not r.get("confirm_batch_id") for r in first["items"])


def test_account_review_confirm_one_click_push(tmp_path):
    m = load_app()
    m.DB_PATH = tmp_path / "demo.db"; m.init_db()
    m.upsert_account("小红书", "seller", status="pending_review", batch_id="B1")
    with m.db() as conn:
        conn.execute("INSERT INTO content_items (id,platform,content_type,title,account_name,risk_score,risk_level,"
                     "recognize_status,account_key,confirm_batch_id,created_at,updated_at) "
                     "VALUES ('B1_0','小红书','文本','t','城南优选',0.9,'高风险','completed','小红书:seller','B1',?,?)", (m.now(), m.now()))
    res = m.api_account_review("小红书:seller", {"review_status": "confirmed", "reviewer": "张三"})
    assert res["success"] and res["report_path"]
    assert res["push"] is not None                       # 一键推送返回了推送结果
    with m.db() as conn:
        pushes = m.rows_to_list(conn.execute("SELECT * FROM push_logs WHERE content_id=?", ("小红书:seller",)).fetchall())
    assert len(pushes) == 1                              # push_logs 落了一条(不论 mock 成败)
```

- [ ] **Step 2: 运行确认失败**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "pass_filter or one_click_push" -v`
Expected: FAIL（`pass` 未过滤 → SP1 出现在 first；`res` 无 `push` 键 / push_logs 空）

- [ ] **Step 3: api_contents 加 pass 过滤**

`app.py` `api_contents` 的 keyword 过滤块之后、`page, page_size, offset = pagination_params(qs)` 之前插入：

```python
    if qs.get("pass") == "first":
        where += " AND (confirm_batch_id IS NULL OR confirm_batch_id='')"
    elif qs.get("pass") == "second":
        where += " AND confirm_batch_id<>''"
```

- [ ] **Step 4: api_account_review 一键推送**

`app.py` `api_account_review` 的结尾这段：

```python
    report_rel = None
    if status == "confirmed":
        try:
            report_rel = generate_account_report(account_key)
        except Exception as exc:
            sys.stderr.write("[account-report] %s 生成失败: %s\n" % (account_key, exc))
    return {"success": True, "account_key": account_key, "confirm_status": status, "report_path": report_rel}
```

替换为（确认后一键：生成报告 + 推送监管）：

```python
    report_rel = None
    push_result = None
    if status == "confirmed":
        try:
            report_rel = generate_account_report(account_key)
        except Exception as exc:
            sys.stderr.write("[account-report] %s 生成失败: %s\n" % (account_key, exc))
        try:
            push = api_create_push(account_key)
            push_result = api_send_push(push["id"])
        except Exception as exc:
            sys.stderr.write("[account-push] %s 推送监管失败: %s\n" % (account_key, exc))
    return {"success": True, "account_key": account_key, "confirm_status": status,
            "report_path": report_rel, "push": push_result}
```

- [ ] **Step 5: 运行确认通过**

Run: `python3 -m pytest tests/test_account_confirmation.py -k "pass_filter or one_click_push" -v`
Expected: PASS。全量 `python3 -m pytest -q` 无回归。

- [ ] **Step 6: 提交**

```bash
git add app.py tests/test_account_confirmation.py
git commit -m "feat(ui): api_contents pass 过滤 + 账户确认一键推送监管"
```

---

## Task 2: 前端 —— 导航退役 reviews + 表1(首次推送)

**Files:**
- Modify: `static/app.js` — `menus`、`contentsQuery`、`renderContents`、`contentsTable`
- Verification: 手动冒烟（前端无单测）

- [ ] **Step 1: 导航重构（`menus`）**

`static/app.js` 顶部 `menus` 数组（3 行组）替换为：

```javascript
const menus = [
  ["核心功能", [["dashboard", "工作台"], ["image-test", "图像识别测试"], ["text-test", "文本识别测试"], ["audio-test", "语音识别测试"]]],
  ["配置管理", [["models", "模型配置"], ["text-llm", "LLM 文本配置"], ["fusion", "多模态融合配置"], ["rules", "规则词库"]]],
  ["业务闭环", [["contents", "表1 · 首次推送"], ["accounts", "表2 · 二次确认"], ["push", "推送管理"], ["users", "用户角色"]]],
];
```

（把 `contents` 从「核心功能」移到「业务闭环」并改名；`accounts` 改名；移除 `["reviews","审核管理"]`。`reviews` 路由分派与 `renderReviews` 保留不删。）

- [ ] **Step 2: contentsQuery 只取首次内容**

`static/app.js` `contentsQuery` 的 `params.set("page", ...)` 之前插入一行：

```javascript
  params.set("pass", "first");
```

- [ ] **Step 3: renderContents 加阶段说明条**

`renderContents` 里 `$("#view").innerHTML = ...` 的模板，在 `<div class="toolbar">` 之前插入一个说明面板。把：

```javascript
  $("#view").innerHTML = `
    <div class="toolbar">
```

改为：

```javascript
  $("#view").innerHTML = `
    <div class="panel"><h3 class="section-title">表1 · 首次推送（文本粗筛）</h3><p class="pre">阶段①全自动：对爬虫首次推送的内容仅做 LLM 文本识别粗筛；识别为「高风险」的账户已自动上报爬虫做二次取证，回推的 10 条帖子进入「表2 · 二次确认」。</p></div>
    <div class="toolbar">
```

- [ ] **Step 4: contentsTable 重构为表1列**

`static/app.js` `contentsTable` 整体替换为：

```javascript
function contentsTable(rows) {
  return `<table>
    <thead><tr><th>平台</th><th>账号</th><th>标题/摘要</th><th>文本风险分</th><th>等级</th><th>识别状态</th><th>已上报爬虫</th><th>发布时间</th><th>操作</th></tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${escapeHtml(r.platform)}</td>
      <td>${escapeHtml(r.account_name)}</td>
      <td class="title-cell" title="${escapeHtml(r.title || "")}">${escapeHtml(r.title || "")}</td>
      <td>${Number(r.risk_score || 0).toFixed(2)}</td>
      <td>${riskTag(r.risk_level)}</td>
      <td>${statusTag(r.recognize_status)}</td>
      <td>${r.risk_level === "高风险" ? '<span class="tag" style="background:#fde8e8;color:#c0392b">已上报</span>' : "—"}</td>
      <td>${escapeHtml(r.publish_time || "-")}</td>
      <td class="actions-cell">
        <button class="secondary" onclick="setRoute('detail/${r.id}')">查看</button>
        <button onclick="recognize('${r.id}')">识别</button>
        <button class="danger" onclick="removeContent('${r.id}')">删除</button>
      </td>
    </tr>`).join("")}</tbody>
  </table>`;
}
```

（列改为表1：命中词/意图不进列表，在「查看」详情里看，避免后端 join。保留查看/识别/删除管理操作。）

- [ ] **Step 5: 手动冒烟验证**

```bash
node --check static/app.js
python3 app.py 8779 &
# 首次内容(无批次)应出现在表1，批次帖不应出现：
curl --noproxy '*' -s 'http://127.0.0.1:8779/api/contents?pass=first&page_size=3' | head -c 300
curl --noproxy '*' -s http://127.0.0.1:8779/app.js | grep -c '表1 · 首次推送'
kill %1
```
浏览器 `http://127.0.0.1:8779/#contents`：确认导航「业务闭环」下是「表1/表2/推送管理」（无审核管理），表1 有说明条与新列、只列首次内容。无法交互验证的部分如实说明。

- [ ] **Step 6: 提交**

```bash
git add static/app.js
git commit -m "feat(ui): 导航退役内容审核 + 表1首次推送(文本粗筛)重构"
```

---

## Task 3: 前端 —— 表2(二次确认)文案/一键提示 + 工作台漏斗

**Files:**
- Modify: `static/app.js` — `renderAccounts`、`saveAccountReview`、`renderDashboard`
- Verification: 手动冒烟（前端无单测）

- [ ] **Step 1: renderAccounts 文案改表2**

`static/app.js` `renderAccounts` 的模板替换为：

```javascript
async function renderAccounts() {
  const data = await api("/api/accounts?confirm_status=pending_review");
  $("#view").innerHTML = `
    <div class="panel"><h3 class="section-title">表2 · 二次确认（多模态）</h3><p class="pre">阶段②：爬虫回推的高危账户近 10 条帖子已做多模态二次分析。命中「高风险帖数量」或「单帖最高分」双信号之一进入本队列；「确认违法」将一键生成证据报告存档并推送监管平台，「误报」则排除。</p></div>
    <div class="table-wrap">${accountsTable(data.items)}</div>
  `;
}
```

- [ ] **Step 2: saveAccountReview 提示一键存档+推送**

`static/app.js` `saveAccountReview` 里 `if (status === "confirmed") { ... } else { ... }` 这段替换为：

```javascript
    if (status === "confirmed") {
      if (!result.report_path) {
        toast("已确认违法（证据报告生成失败，可稍后重试）");
      } else {
        const pushed = result.push && result.push.push_status === "success";
        toast(pushed ? "已确认违法 · 证据报告已存档 · 已推送监管平台"
                     : "已确认违法 · 证据报告已存档（推送监管待重试，见推送管理）");
      }
    } else {
      toast("已标记误报");
    }
```

- [ ] **Step 3: renderDashboard 加两阶段漏斗**

`static/app.js` `renderDashboard` 整体替换为：

```javascript
async function renderDashboard() {
  const data = await api("/api/dashboard");
  let firstCount = 0, accs = { items: [] };
  try { firstCount = (await api("/api/contents?pass=first&page_size=1")).total; } catch (e) { /* 忽略 */ }
  try { accs = await api("/api/accounts"); } catch (e) { /* 忽略 */ }
  const cnt = s => (accs.items || []).filter(a => a.confirm_status === s).length;
  const funnel = {
    "① 首次推送内容": firstCount,
    "② 高危账户(待取证/识别中)": cnt("awaiting_posts") + cnt("recognizing"),
    "③ 二次确认待审": cnt("pending_review"),
    "④ 已确认已推送": cnt("confirmed"),
  };
  $("#view").innerHTML = `
    <div class="cards">
      ${Object.entries(data.cards).map(([k, v]) => `<div class="card"><div class="metric-label">${k}</div><div class="metric-value">${v}</div></div>`).join("")}
    </div>
    <div class="panel"><h3 class="section-title">两阶段处置漏斗</h3>${bars(funnel)}</div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">平台来源分布</h3>${bars(data.platforms)}</div>
      <div class="panel"><h3 class="section-title">风险等级分布</h3>${bars(data.risks)}</div>
      <div class="panel"><h3 class="section-title">三模态命中数量</h3>${bars(data.modalities)}</div>
      <div class="panel"><h3 class="section-title">近7日线索趋势</h3>${bars(data.trend)}</div>
    </div>
  `;
}
```

- [ ] **Step 4: 手动冒烟验证**

```bash
node --check static/app.js
python3 app.py 8780 &
curl --noproxy '*' -s http://127.0.0.1:8780/app.js | grep -c '两阶段处置漏斗'
curl --noproxy '*' -s http://127.0.0.1:8780/app.js | grep -c '表2 · 二次确认'
# 造 pending_review 账户 → 一键确认 → 断言返回含 push + report_path：
curl --noproxy '*' -s 'http://127.0.0.1:8780/api/accounts?confirm_status=pending_review' | head -c 200
kill %1
```
浏览器 `#dashboard` 看两阶段漏斗；`#accounts` 看表2 文案；对一个待审账户点「确认违法」看提示「已存档·已推送监管」。无法交互验证的部分如实说明。

- [ ] **Step 5: 提交**

```bash
git add static/app.js
git commit -m "feat(ui): 表2二次确认文案+一键提示 + 工作台两阶段漏斗"
```

---

## Self-Review（作者自查，已执行）

**Spec coverage：** 导航退役 reviews + contents/accounts 改名(T2/T1,T3)、表1首次内容+文本列+已上报(T2)、表2多模态+人工一键存档推送(T1 后端+T3 前端)、工作台漏斗(T3)、api_contents pass(T1)、api_account_review 一键推送(T1) —— spec 各节均有任务。表1 列做了一处简化(命中词/意图移到详情,避免 join),已在 T2 Step4 注明。

**Placeholder scan：** 无 TBD/TODO；每步含完整代码与确切替换锚点。

**Type consistency：** `api_contents` 的 `pass` 取值 `first/second` 一致；`api_account_review` 返回 `push` 字段(T1 定义、T3 saveAccountReview 消费 `result.push.push_status`)一致；`menus` 里 `contents`→表1、`accounts`→表2 与视图文案一致；`renderDashboard` 用现有 `bars`/`api`。
