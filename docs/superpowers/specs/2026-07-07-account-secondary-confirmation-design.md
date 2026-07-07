# 账户二次确认闭环 — 设计文档

日期：2026-07-07
分支：audio
状态：已确认设计，待实现

## 背景

现有系统是**内容中心、单阶段**：爬虫把内容 `POST /api/crawler/push`（`api_crawler_push` `app.py:2296`）进来，
`recognize_content`（`app.py:1514`）做文本+图像+视频+语音多模态识别与融合评分，
高风险内容自动把风险账户回推爬虫（`post_crawler_user_risk` `app.py:2598`，由
`AUTO_FEEDBACK_ON_RECOGNIZE` `app.py:65` 门控）。

目标业务是**账户中心、两阶段**闭环，中间有一次爬虫回推：

```
② 我方 LLM 文本识别出高危用户 → 上报爬虫(现有 post_crawler_user_risk)
   爬虫自动解析该用户近 10 条帖子(多模态)
③ 爬虫主动 POST 回我方新接口 → 10 条帖子入库
④ 10 条识别完 → 账户级最终确认(聚合)
⑤ 人工审核账户 → 推送
⑥ 生成账户级证据报告(HTML)
```

本设计新增阶段 ③④⑤(账户级)⑥，其中阶段②的上报已存在，仅做一处状态衔接。

## 目标与约束

- 新增能力全部落在**管理服务 `app.py`**（Python 标准库 + SQLite），**不改**视觉/文本/语音三个 FastAPI 服务。
- 识别复用现有异步链路：`_auto_recognize_loop`（`app.py:1638`）+ `recognize_content`（`app.py:1514`）+ `analyze_fusion`（`app.py:1408`）。
- 入库复用 `crawler_item_to_content`（`app.py:2272`）。
- 账户为**一等实体**（方案 A）：新增 `accounts` 表；`content_items` 增列关联账户。
- 接收接口**异步**：只做入库 + 入识别队列，立即返回，不在 HTTP 请求内跑识别（视频识别慢）。
- 报告为**自包含 HTML**：证据图/帧/音频片段以 base64 内嵌，单文件无外链，不引入 PDF/第三方依赖。

## 术语

- **二次确认批次(confirm_batch)**：爬虫一次回推的 10 条帖子构成一个批次，`confirm_batch_id` 标识。同账户重复推送产生新批次，最新批次代表当前判定。
- **双信号判定**：`high_post_count`（批次中 `risk_level=高风险` 的帖子数）与 `max_post_score`（批次最高综合分）两个指标，任一超阈即进账户审核队列。

## 端到端流程与账户状态机

`accounts.confirm_status` 状态机：

```
awaiting_posts   ② 我方上报高危用户给爬虫时置位（等待回推）
     │  ③ 收到 POST /api/users/<platform>/<user_id>，10 条入库、入识别队列
     ▼
recognizing      10 条帖子异步识别中
     │  ④ 批次全部到终态(done/failed)后聚合双信号
     ├─ 命中(count≥N 或 max≥阈值) ──▶ pending_review  ⑤ 进账户人工审核队列
     └─ 未命中 ───────────────────────▶ dismissed
pending_review
     │  ⑤ 人工审核
     ├─ confirmed ──▶ ⑥ 生成 HTML 报告，可加入推送队列
     └─ dismissed
```

## 接口契约

### 入站契约（新增到 `docs/__init__.py`）

```python
class ReturnDataUser(TypedDict):
    platform: str                       # 平台
    user: UserData                      # 用户（复用现有 UserData: id/nickname/description/avatarUrl）
    timeTook: float                     # 耗时
    type: str                           # 返回数据类型
    data: list[VideoData | NoteData]    # 该用户近 10 条帖子（复用现有 VideoData/NoteData）
```

### 新增 HTTP 接口（`app.py` Handler，路由在 `do_GET:1900`/`do_POST:1948` 分派表）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/users/<platform>/<user_id>` | 阶段③接收：体为 `ReturnDataUser`。校验 → upsert 账户(→recognizing) → 建 `confirm_batch_id` → 10 条入库并入识别队列 → 返回 **202** `{account_key, confirm_batch_id, accepted, skipped}` |
| GET | `/api/accounts` | 账户列表，支持 `confirm_status`/`platform` 过滤，用于账户审核队列 |
| GET | `/api/accounts/<account_key>` | 账户详情：账户信息 + 聚合指标 + 该批次 10 条帖子识别摘要 |
| POST | `/api/accounts/<account_key>/review` | 账户级人工审核：`{review_status: confirmed|dismissed, review_opinion, reviewer}`；`confirmed` 时生成报告 |
| GET | `/api/accounts/<account_key>/report` | 返回该账户最新批次的 HTML 报告（`Content-Type: text/html`） |

- `account_key = f"{platform}:{user_id}"`。
- **校验**：路径 `user_id` 必须等于 body `user.id`，且 `platform` 必须一致，否则 400。`data` 为空或结构非法 → 400。

## 数据模型

### 新增 `accounts` 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `account_key` | string PK | `"{platform}:{user_id}"` |
| `platform` | string | 平台 |
| `user_id` | string | 平台内用户 ID |
| `nickname` | string | UserData 快照 |
| `description` | text | 个性签名快照 |
| `avatar_url` | string | 头像快照 |
| `account_risk_score` | float | 账户综合风险分（=`max_post_score`，便于列表排序） |
| `high_post_count` | int | 批次中高风险帖子数 |
| `max_post_score` | float | 批次最高综合分 |
| `post_count` | int | 批次帖子数（通常 10） |
| `confirm_status` | string | `awaiting_posts`/`recognizing`/`pending_review`/`confirmed`/`dismissed` |
| `confirm_batch_id` | string | 最近一次二次确认批次 ID |
| `last_confirm_at` | datetime | 最近批次收到时间 |
| `violation_type` | text(json) | 违规类型（聚合自帖子融合结果） |
| `report_path` | string | HTML 报告文件路径 |
| `reviewer` | string | 账户审核人 |
| `review_opinion` | text | 账户审核意见 |
| `review_time` | datetime | 账户审核时间 |
| `created_at` / `updated_at` | datetime | — |

建表并入 `SCHEMA` 常量（`app.py:198`）；`init_db`（`app.py:381`）首次启动自动建表。

### `content_items` 增列

沿用现有运行时加列机制 `CONTENT_ITEM_EXTRA_COLUMNS`（`app.py:174`），**不改** SCHEMA 常量里的 content_items 定义：

- `account_key`（string）— 关联 `accounts`。
- `confirm_batch_id`（string）— 标记属于哪个二次确认批次；为空表示普通一次推送内容。

### 复用表

- `recognition_results`：每条帖子的多模态识别结果，聚合时读取。
- `crawler_comments`：10 条帖子的评论仍按现有逻辑写入。
- `push_logs`：账户级推送记录（`content_id` 位存 `account_key`）。
- 账户审核**只落 `accounts` 表审核字段**（`reviewer`/`review_opinion`/`review_time`），不写 `review_records`，避免与单条内容审核记录混淆。

## 组件设计（按单元）

### 1. 接收 / 入库单元（`api_receive_user_posts`）

阶段③入口。校验 `ReturnDataUser` → upsert `accounts`（从 `user` 写快照，状态置 `recognizing`，
生成新 `confirm_batch_id`，`last_confirm_at=now`）→ 对 `data` 每条经 `crawler_item_to_content`
落 `content_items`，补写 `account_key` + `confirm_batch_id`，`recognize_status=pending`，
评论走现有 `upsert_crawler_comments`。触发现有 `trigger_auto_recognize`（`app.py:1645`）。返回 202。

畸形单条帖子跳过并计入 `skipped`，不影响其余入库。

### 2. 账户 upsert / 状态机（`upsert_account` / `set_account_status`）

集中管理 `accounts` 的写入与状态流转，供接收单元、聚合器、审核接口、阶段②衔接共用。

### 3. 聚合器（`aggregate_account_confirmation`）

**批次完成检测**：`recognize_content` 完成落库后（`app.py:1568` 之后）增加一个 hook——
若该内容带 `confirm_batch_id`，检查同批次 `content_items` 是否全部到终态（`recognize_status in {done, failed}`）。
全部到终态 → 调用聚合器。

**双信号聚合**：读取该批次帖子的 `risk_level`/`risk_score`：
- `high_post_count = count(risk_level == 高风险)`
- `max_post_score = max(risk_score)`
- 命中条件：`high_post_count >= SECONDARY_HIGH_POST_COUNT` **或** `max_post_score >= SECONDARY_MAX_SCORE_THRESHOLD`
- 命中 → `confirm_status=pending_review`；否则 `dismissed`。
- 写 `account_risk_score`（=max_post_score）、`high_post_count`、`max_post_score`、`post_count`、`violation_type`（并集自帖子融合结果）。

### 4. 账户审核 + 推送（`api_account_review`）

`pending_review` 账户进 `GET /api/accounts?confirm_status=pending_review` 队列。
`POST /api/accounts/<key>/review`：`confirmed` → 写审核字段 → 调报告生成器 → 写 `report_path`，
可加入推送队列（复用 `api_create_push`/`api_send_push`/`mock_regulatory_push` `app.py:2782/2799/2792`，账户粒度）。`dismissed` → 只写审核字段。

### 5. HTML 报告生成器（`build_account_report_html`）

纯标准库字符串模板，读账户 + 该批次 10 条 `content_items` + `recognition_results` + 现有证据产物
（`app/services/evidence.py` 截图、`audio_service/services/evidence.py` 音频片段），
证据图/帧读文件转 base64 内嵌。版式：

1. 账户信息头（平台、昵称、user_id、头像、签名）
2. 账户级结论（`X/10` 命中、最高分、违规类型、系统解释、审核人/时间）
3. 逐帖证据卡片（每条：标题/链接、文本命中词、检测对象、OCR、视频关键帧、音频片段+转写、单帖综合分）
4. 生成时间

存 `storage/reports/<account_key>/<confirm_batch_id>.html`（`account_key` 中的 `:` 做文件名安全替换），路径写回 `accounts.report_path`。

### 6. 阶段②衔接（修改现有出站逻辑）

在 `feedback_high_risk_account`（`app.py:2616`）成功把高危用户发给爬虫后，**同时** `upsert_account`：
若账户不存在则建，`confirm_status` 置 `awaiting_posts`（已是更后状态则不回退）。
这样爬虫回推 10 条时能对上账户、闭环有状态起点。评论区高危用户
（`feedback_high_risk_comment_users` `app.py:2720`）走同一「出站→回推」路径，同样 `upsert_account` 置 `awaiting_posts`。

### 7. 前端（`static/app.js` + `static/index.html`）

新增「账户二次确认」视图：账户队列列表（按 `confirm_status` 筛）+ 账户详情（聚合指标 + 10 条证据摘要 + 报告入口）+ 审核按钮。沿用现有政务后台风格与 hash 路由约定。

## 新增配置（`.env.example`，`${VAR:-default}` + 中文注释）

- `SECONDARY_HIGH_POST_COUNT`（默认 `2`）— 批次中高风险帖子数达此值即命中。
- `SECONDARY_MAX_SCORE_THRESHOLD`（默认 `0.85`）— 批次最高单帖综合分达此值即命中。
- `SECONDARY_EXPECTED_POSTS`（默认 `10`）— 期望帖子数，仅用于日志/展示，不强校验。

复用现有：`CRAWLER_RISK_API_BASE/PATH`（`app.py:59`）、`AUTO_RECOGNIZE`（`app.py:57`）、`AUTO_FEEDBACK_ON_RECOGNIZE`（`app.py:65`）。

## 错误处理与边界

- 接口结构非法 / 路径-body 不一致 → 400；单条帖子畸形 → 跳过 + 计入 `skipped`，其余照常入库。
- 单条识别失败 → 该帖 `recognize_status=failed`，不计入高危计数；批次内**全部到终态**（done 或 failed）即聚合，容忍部分失败。
- 爬虫重复推送同账户 → 新 `confirm_batch_id`，账户快照与判定按最新批次刷新，旧批次帖子（带旧 batch_id）保留作历史。
- 二次确认批次的 10 条帖子**不进**现有单条内容审核队列：`api_reviews`（`app.py:2572`）查询排除 `confirm_batch_id` 非空的记录，避免污染。
- 报告读取证据文件（视觉 `storage/evidence/`、语音 `audio_storage/evidence/`）依赖与识别服务**共享文件系统**（dev 同机；docker-compose 需共享卷）；单个证据文件缺失时报告降级——只展示该帖识别元数据，不中断生成。
- 报告生成失败 → 账户仍 `confirmed`，`report_path` 空，可通过再次 review 或 `GET .../report` 重试生成。
- 下游全程「尽力而为、不阻塞接收」，与现有 `feedback_high_risk_account` 的异常处理风格一致。

## 测试（`tests/`，pytest，沿用 `tests/test_crawler_push.py` 风格）

- **接收接口**：合法 `ReturnDataUser` → 建 `accounts` + 10 条 `content_items`（带 `account_key`/`confirm_batch_id`）；路径/body `user_id` 或 `platform` 不一致 → 400；畸形帖子被跳过且 `skipped` 计数正确；账户状态 → `recognizing`。
- **聚合双信号**：计数临界（`N-1` 不命中、`N` 命中）、最高分临界（阈值上下）、全低 → `dismissed`、单条爆高但计数不足 → 仍命中（max 信号）；部分帖子 `failed` 时仍能聚合。
- **状态机**：`awaiting_posts`→`recognizing`→`pending_review`/`dismissed`→`confirmed` 流转正确；重复推送刷新为新批次。
- **报告**：HTML 生成成功、**自包含**（无 `http`/外部 `src` 引用，证据为 base64）、含账户信息与逐帖证据、`report_path` 写回。
- **阶段②衔接**：`feedback_high_risk_account` 成功后账户被置 `awaiting_posts`。

## 非目标（YAGNI）

- 不改视觉/文本/语音三个 FastAPI 服务与其 schema。
- 不改多模态融合 `analyze_fusion` 的算法。
- 不做真实监管平台推送（沿用现有 mock `mock_regulatory_push`）。
- 不引入消息队列/Celery，沿用现有进程内后台线程识别循环。
- 不引入 PDF 生成库；报告为 HTML，如需 PDF 由浏览器打印。
- 不做账户画像/历史趋势/多批次对比等扩展（`accounts` 表预留字段即可，后续另开）。
