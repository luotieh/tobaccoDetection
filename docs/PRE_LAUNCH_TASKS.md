# 上线前任务优化书

> 用途：把烟草违法监测系统投入**内部试点（小范围真实用户）**前必须收口的安全、稳定、性能问题整理为可落地任务。
> 与 `docs/NEXT_OPTIMIZATION_PLAN.md` 的关系：那份是面向功能迭代的 4 阶段路线图；本书**不重复**它，只聚焦「试点上线前的阻塞项与近线项」，并在相关处交叉引用。
> 编写依据：对管理端 `app.py`、前端 `static/`、三个微服务（`app/`、`text_service/`、`audio_service/`）、部署脚本与文档的一次全量审计（2026-06-15）。

---

## 0. 当前结论

- 系统是**可运行的多模态原型**：管理端（stdlib `ThreadingHTTPServer` + SQLite + 内嵌 SPA）+ 视觉/文本/语音三个 FastAPI 服务，已具备识别、审核、推送、规则词库等页面。
- **不可直接对真实用户开放**：缺访问控制、存在前端存储型 XSS、多个列表页与工作台全量加载、上传无大小限制、默认 Mock 易冒充真实结果。
- 定级：**P0 = 试点上线阻塞**，**P1 = 上线后尽快**，**P2 = 生产化**（多数并入 `NEXT_OPTIMIZATION_PLAN` 阶段 3/4）。

---

## 1. P0 — 试点上线阻塞项

### P0-1 前端存储型 XSS 转义
- **问题**：多处表格/表单把数据库字段直接插入 HTML 而未转义，规则词、标题、错误信息等可由爬虫推送或操作员录入，构成存储型 XSS。
- **定位**（`static/app.js`）：
  - `rulesTable`（~996）：`r.word` / `r.remark` / `r.rule_type` 未转义；`openRuleForm(${JSON.stringify(r)})` 注入到 `onclick` 单引号属性。
  - `renderReviews`（~1051）：`r.title` / `r.platform` 未转义。
  - `renderPush`（~1056）：`r.title` / `r.error_message` 未转义（错误信息可能回显外部系统数据）。
  - `renderModels`（~780）：模型 `name` / `endpoint` / `description` 未转义。
  - `openRuleForm`（1008/1011）：`r.word` / `r.remark` 注入到 `value=""` / `<textarea>`。
  - `contentsTable`（402）：`r.account_name` / `r.platform` / `r.content_type` 未转义（标题已转义）。
- **复用**：`escapeHtml`（`static/app.js:529`）已存在。
- **验收**：新增 `word` 为 `<img src=x onerror=alert(1)>` 的规则，规则/审核/推送/模型页与编辑框均渲染为纯文本、不执行脚本。

### P0-2 列表分页 / 限流
- **问题**：审核、推送、规则页一次性渲染全部行；后端对应查询无 `LIMIT`。数据量上来后浏览器卡死、后端内存升高。
- **定位**：后端 `api_reviews`（`app.py:2320`）、`api_push`（`app.py:2347`）、`api_rules` 无分页；前端 `renderReviews` / `renderPush` / `renderRules` 全量渲染。
- **复用**：`api_contents` 已落地的分页范式 —— 返回 `{items,total,page,page_size}`，前端 `contentsPager()` / `loadContents()` 控件。
- **验收**：三页默认每页 20、可翻页；构造万级数据不卡死；后端返回带 `total/page/page_size`。

### P0-3 工作台聚合查询
- **问题**：`api_dashboard` 用 `SELECT * FROM content_items` 和 push_logs 全表拉进内存，再用 Python 逐条统计；趋势数据是 `random` mock。
- **定位**：`app.py:1846-1851`。
- **实施**：改为 SQL `COUNT/GROUP BY` 聚合（今日采集、各识别/审核状态数、平台/风险/模态分布）；趋势改真实统计或在前端显式标注「示意」。
- **验收**：`/api/dashboard` 数值与改造前一致，但不再全表加载。

### P0-4 上传大小限制
- **问题**：文件整体 `read()` 进内存后才处理，无前置大小校验，单 worker 服务易 OOM。
- **定位**：管理端多段解析 `app.py:1566-1613` 与图片/文件读取 `1654-1680`；audio `audio_service/routers/inference.py:16`（配置 `MAX_FILE_SIZE_MB=200` 但未生效）；vision `app/routers/inference.py`。
- **验收**：超限请求返回 413/400 且不读满全文；audio 真正按配置上限拦截。

### P0-5 最小访问控制（鉴权）— 已选方案 (a)
- **问题**：全部 `/api/*` 无任何鉴权，任何能访问到管理端的人都可增删规则、改模型配置、审核、推送。真实用户试点不可接受。
- **定位**：`do_GET/POST/PUT/DELETE`（`app.py:1706-1842`）无校验。
- **已选方案 (a) 反向代理 HTTP Basic**（nginx/Caddy 前置）：**应用零改动**，最快可用，适合内网试点。
  - 落地物：`deploy/nginx.conf`、`deploy/Caddyfile`、`scripts/gen_htpasswd.sh`、`deploy/README.md`。
  - 配套：`app.py` 新增 `MANAGEMENT_HOST` 支持，管理端与三微服务建议绑定 `127.0.0.1`，仅代理端口对外。
  - 部署步骤见 `deploy/README.md`。
- **后续演进**：生产再升级到「用户表 + 登录 + 角色 + 审计」（方案 c / `NEXT_OPTIMIZATION_PLAN` 任务 4.1）。
- **验收**：不带凭据访问代理端口返回 401；带正确账号密码可正常使用；8000 端口不直接对外暴露。

### P0-6 关闭 Mock 误判
- **问题**：三服务默认开启 Mock fallback（`USE_MOCK_MODEL` / `ASR_ENGINE=mock`），异常时静默回退 mock，演示/试点易把「假命中」当真实结果。
- **定位**：`.env` `TOBACCO_PROFILE=dev`；fallback 见 `app.py:849-865`（视觉→本地 YOLO→mock）、`1434-1456`（文本/语音→mock）。
- **实施**：试点以 `real` 或明确标注模式启动；前端各结果页展示已有的 `service_mode` / `asr_engine` / `model_version` / `*_service_error` 字段；缺模型时**报错而非静默 mock**（对接 `NEXT_OPTIMIZATION_PLAN` 任务 1.1 / 2.3）。
- **验收**：缺模型时 `real` 模式明确报错；前端能区分「真实/演示」结果来源。

---

## 2. P1 — 上线后尽快

- **可观测性**：引入结构化日志 + 请求访问日志 + `.runtime/` 日志轮转（当前仅 `print`/`stderr`，无轮转）。
- **优雅停机**：管理端 `serve_forever` 无 SIGTERM 处理（`app.py:2382`）；`scripts/stop_all.sh` 直接 kill，无 SIGTERM→SIGKILL 过渡。
- **并发与守护**：微服务 uvicorn 各 Dockerfile 单 worker，按 CPU 加 `--workers`；用 systemd/supervisor 替代 `nohup` 裸进程（无自动重启）。
- **依赖锁定**：`requirements.txt` 全为 `>=`，重建可能拉到破坏性大版本 —— 锁定到兼容区间。
- **测试缺口**：`tests/` 现有 10 个测试均不覆盖管理端 `app.py` 的 API；补 `/api/contents|reviews|push|rules|recognize` 的 pytest（含本次分页逻辑）。
- **模型校验**：新增 `scripts/check_models.sh` 启动期校验 YOLO/Whisper/FFmpeg（对接 NEXT 任务 2.3）。
- **识别异步化**：识别由同步按钮升级为可追踪任务 + 失败重试（对接 NEXT 任务 3.1 / 4.2）。

---

## 3. P2 — 生产化（并入 NEXT_OPTIMIZATION_PLAN 阶段 3/4）

- 完整 RBAC + 操作审计日志（NEXT 4.1）。
- SQLite → PostgreSQL、媒体 → 对象存储的迁移设计（NEXT 4.3）。
- 推送载荷规范化与状态机、监管平台真实对接（NEXT 3.3 / 风险约束 7）。
- 前端可访问性（ARIA、loading 态）、API 错误提示细化、CORS 与安全响应头评估。
- 管理端从 stdlib `ThreadingHTTPServer` 评估迁移到 FastAPI/正式后端（NEXT 风险约束 5）。

---

## 4. 误报澄清（审计中已核验为非问题，避免重复排查）

1. **`data/demo.db` / `.env` 未入仓**：`git ls-files data/ .env` 为空，仅 `.env.example` 跟踪；不存在「数据库或密钥提交入仓」问题。
2. **后台自动识别非忙等**：`_auto_recognize_loop` 用 `_auto_recognize_event.wait()` 阻塞（`app.py:1525-1529`），不是 100% CPU 自旋。
3. **「SQL 注入」位点为误报**：`app.py:77`（PRAGMA）、`350/354`（ALTER）、`1878`（字段名）均为**硬编码或白名单标识符 + 参数化取值**，无用户可控注入面，仅 f-string 风格问题。

---

## 5. 上线前验收总清单（Go/No-Go）

- [ ] P0-1 全部动态字段转义，构造 XSS 载荷不执行。
- [ ] P0-2 审核/推送/规则页分页可用，大数据不卡死。
- [ ] P0-3 工作台改聚合查询，数值一致且不全表加载。
- [ ] P0-4 上传超限被拦截，服务不 OOM。
- [ ] P0-5 访问控制就位（方案 a：反向代理 HTTP Basic，见 `deploy/`），未授权返回 401。
- [ ] P0-6 试点运行模式明确，Mock 不冒充真实，缺模型报错。
- [ ] 四服务 `scripts/status_all.sh` 全 healthy；`pytest -q` 全绿。
