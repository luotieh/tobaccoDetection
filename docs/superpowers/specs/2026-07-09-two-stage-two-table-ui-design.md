# 两阶段两表 UI 重构 — 设计文档

日期：2026-07-09
分支：feature/two-stage-ui
状态：已确认设计，待实现

## 背景

后端两阶段识别闭环已建成（首次 LLM 文本粗筛 / 二次多模态确认 + 账户级去重 + 账户详情逐帖多模态）。但前端仍是通用「识别内容列表」混合展示，未体现两阶段分工。本次把 UI 重构成**两张表**，让两阶段流程成为主叙事。

## 目标与约束

- **表1「首次推送·文本粗筛」**：只展示爬虫首次推送内容（`confirm_batch_id` 空），文本结果 + 已上报爬虫状态；阶段①全自动，只读监控。
- **表2「二次确认·多模态」**：爬虫回推的高危账户队列 + 逐帖多模态（已实现）+ 人工「确认违法」**一键**（生成证据报告存档 + 推送监管平台）。
- 内容级审核 `#reviews` 退役：**从导航移除，视图/路由代码保留不删**（最小破坏）。
- 复用现有后端与视图；不改多模态识别/融合算法；不新增第三方依赖；推送监管沿用现有 mock。

## 设计

### 1. 导航 / IA（`static/app.js` `menus`）

「业务闭环」组重构为：
```
业务闭环
├── contents  「表1 · 首次推送（文本粗筛）」   ← 现「识别内容列表」重构
├── accounts  「表2 · 二次确认（多模态）」      ← 现「账户二次确认」重构
└── push      「推送管理」                       ← 保留
```
- 从 `menus` 移除 `["reviews", "审核管理"]` 入口。`reviews` 路由分派与 `renderReviews`/`reviewsTable` 代码**保留不删**（仅不在导航；直达 `#reviews` 仍可用）。
- 保留 `#contents`、`#accounts` 路由，仅重构其视图文案与内容。

### 2. 表1（`renderContents` 重构）

- **后端**：`api_contents(qs)` 新增可选 `pass` 过滤：`pass=first` → 追加 `WHERE (confirm_batch_id IS NULL OR confirm_batch_id='')`；`pass=second` → `confirm_batch_id<>''`；缺省不加（向后兼容）。
- **前端**：`renderContents` 请求 `/api/contents?pass=first`；顶部说明条「阶段①全自动：仅 LLM 文本粗筛；识别为高风险的账户已自动上报爬虫做二次取证」。
- 列：平台 | 账号 | 标题/摘要 | 文本风险分 | 风险等级 | 命中词或意图 | 识别状态 | 已上报爬虫 | 发布时间 | 查看。
  - 「已上报爬虫」：内容 `risk_level=='高风险'` → 显示「已上报」（高风险内容的账户由 `AUTO_FEEDBACK_ON_RECOGNIZE` 自动上报爬虫），否则「—」。纯前端从 `risk_level` 推导，不需后端 join。
  - 「查看」→ 现有 `renderDetail`（首次内容详情只有文本结果，符合分流）。

### 3. 表2（`renderAccounts` 重构 + 一键推送）

- **前端**：`renderAccounts` 文案改为「表2 · 二次确认」；队列列：平台 | 账号 | 命中高危帖(X/总) | 最高分 | 违规类型 | 状态 | 查看。
- `renderAccountDetail`（已含逐帖多模态证据）：确认按钮流程改为一键；确认成功后提示「已存档·已推送监管」并显示证据报告与推送状态。
- **后端** `api_account_review` 的 `confirmed` 分支：生成证据报告后，**自动推送监管**——写 `push_logs`（`content_id` 位存 `account_key`、`report_id` 存报告相对路径）+ 调 `mock_regulatory_push`；返回 `{success, confirm_status, report_path, push:{status, report_id}}`。`dismissed` 分支不变。

### 4. 工作台（`renderDashboard` 调整）

改为两阶段漏斗展示：首次推送量 → 文本高危账户数（账户 `awaiting_posts`/`recognizing` 及以后）→ 二次确认待审（`pending_review`）→ 已确认已推送（`confirmed`）。数据用现有 `/api/dashboard` + `/api/accounts`（按 `confirm_status` 计数）；如现有接口不足，`/api/dashboard` 补账户阶段计数字段。保留原有平台/风险分布图。

## 测试

- `api_contents` `pass=first` 只返回首次内容（排除 `confirm_batch_id` 非空的批次帖）；`pass=second` 只返回批次帖；缺省返回全部（兼容）。
- `api_account_review` `confirmed` 一键：`report_path` 有值 **且** `push_logs` 有该 `account_key` 记录 **且** 返回含 `push` 结果。
- 前端 `node --check` + 表1（`pass=first`）/表2 live 冒烟。

## 非目标（YAGNI）

- 不改多模态识别、融合权重、`analyze_fusion`。
- 不删 `#reviews` 代码（仅导航退役）。
- 不做批量推送（单账户一键）。
- 不把推送监管改成真实接口（沿用 `mock_regulatory_push`）。
- 不改后端识别分流逻辑（上一特性已实现）。
