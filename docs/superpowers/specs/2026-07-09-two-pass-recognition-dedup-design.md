# 两阶段识别分流 + 账户去重 + 详情多模态 — 设计文档

日期：2026-07-09
分支：feature/two-pass-recognition
状态：已确认设计，待实现

## 背景

现有 `recognize_content` 对所有内容都跑全多模态（文本 + 图像/视频 + 语音 + 融合），与原始业务分工不符：

- 阶段②（初次识别/粗筛）应只用 **LLM 文本识别**（便宜、快），从可疑内容里筛出高危账户；
- 阶段④（二次确认）才对高危账户回推的 10 条帖子跑**多模态**（贵，只对高危账户做）。

另外：同一高危账户的多条高危帖在首次识别时会各上报一次爬虫（重复）；账户详情页只展示帖子摘要，未展示多模态识别结果。

## 目标与约束

- 识别分流：首次内容（无 `confirm_batch_id`）只跑文本；二次确认批次（有 `confirm_batch_id`）跑全多模态。
- 账户级去重：同一高危账户只上报爬虫一次。
- 账户详情页展示每条批次帖子的多模态识别结果。
- 复用现有 text/vision/audio 服务与 `recognition_results`；不新增第三方依赖；不改多模态识别算法与融合权重。
- 评论打分（`score_content_comments`，文本类）**两阶段都保留**（评论区买家也是高危账户线索）。

## 设计

### 1. 识别分流（`recognize_content`）

按 `content["confirm_batch_id"]` 是否为空分流：

- **空（首次识别）**：只调 `text_service_analyze_content`（帖子文本 + 作者简介 + 评论，现有）；`image_result = audio_result = None`，`image_score = audio_score = 0`，**不调** `analyze_image_with_vision` / `audio_service_analyze_media`。内容 `risk_score`/`risk_level` 由 `analyze_fusion` 的单模态（`text_available=True, image_available=False, audio_available=False`）路径给出，等价于文本风险。
- **非空（二次确认批次）**：维持现有全多模态（文本 + 图像/视频 + 语音 + 融合）。

`recognition_results` 落库沿用现有"跳过 None 结果"的写入循环——首次自然只写 `text` + `fusion`，二次写 `text` + `image` + `audio` + `fusion`，无需额外分支。

### 2. 批次重识别（`api_receive_user_posts`）

入库打批次标记时补 `recognize_status='pending'`：同一帖若首次已按文本识别过（同 `content_id`，`api_crawler_push` upsert 复用行、状态已 `completed`），二次回推必须**重新按多模态识别**。当前只 `SET account_key, confirm_batch_id, updated_at`，需加 `recognize_status='pending'`。

### 3. 账户级去重（feedback 上报）

`feedback_high_risk_account` 与 `feedback_high_risk_comment_users` 在向爬虫 `post_crawler_user_risk` 之前：

- 读该 `account_key` 现有 `confirm_status`；若 ∈ `{awaiting_posts, recognizing, pending_review, confirmed}` → **跳过上报**（该账户已在确认流程中）。
- 否则（账户不存在，或此前 `dismissed`）→ 上报一次，并 `upsert_account(status="awaiting_posts")`（现有阶段②衔接）。

效果：某账户多条高危帖只上报一次；爬虫重复回推复用同一账户行（`upsert_account` 已按 `account_key` 去重）；待审核队列（`api_accounts`）天然每账户一行。

新增可复用判定 `account_already_in_pipeline(account_key) -> bool`，供两个 feedback 函数共用。

### 4. 账户详情页多模态展示

- 抽共享函数 `assemble_account_posts(account) -> list[dict]`：从 `generate_account_report` 里现有的 posts 组装逻辑（读该批次 `content_items` + `recognition_results` 按 `model_type` 分组 text/image/audio/fusion + 证据文件路径）抽出，供 `api_account_detail` 与 `generate_account_report` 共用（DRY）。
- `api_account_detail`：`posts` 每项由 `assemble_account_posts` 提供多模态结果——标题/链接、单帖综合分/等级、文本命中词与意图、检测对象、OCR、视频证据帧路径、语音转写与关键词。
- 前端 `renderAccountDetail`（`static/app.js`）：逐帖渲染多模态卡片（类似证据报告的逐帖证据）；证据图用现有 `/storage/evidence/<content_id>/*.jpg` 静态路由。用户输入统一 `escapeHtml`，`account_key` 入 URL 用现有 `routeKey`。

## 测试

- **分流**：monkeypatch `analyze_image_with_vision` / `audio_service_analyze_media` 计数；首次内容（无 batch，含图片 media）识别后二者**不被调用**、`recognition_results` 只有 `text`+`fusion`；二次批次识别后二者**被调用**、含 `image`/`audio` 结果。
- **去重**：同账户 3 条高危首次内容识别 → `post_crawler_user_risk` 只被调用一次（monkeypatch 计数）；账户已 `awaiting_posts`/`recognizing`/`confirmed` 时再来高危帖不重复上报；`dismissed` 账户再高危可再次上报。
- **批次重识别**：一条已 `completed` 的首次内容被 `api_receive_user_posts` 回推后 `recognize_status` 重置为 `pending`。
- **详情**：`api_account_detail` 返回的 `posts` 每项含多模态字段（text/image/audio/fusion）；`assemble_account_posts` 与 `generate_account_report` 产出一致（报告不回归）。

## 非目标（YAGNI）

- 不改多模态识别算法、融合权重、`analyze_fusion` 逻辑。
- 不做帖子级去重（`content_id` upsert 已天然一帖一行）。
- 不改证据报告**产出内容**（仅把 posts 组装抽成共享函数，报告输出不变）。
- 不改前端"首次识别内容列表"页——它继续展示内容，只是详情里图像/语音结果对首次内容为空（符合分流意图）。
