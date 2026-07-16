# 二次批次远程媒体按需下载 — 设计文档

日期：2026-07-16
分支：feature/batch-media-download
状态：已确认设计，待实现

## 背景

识别分流后，二次确认批次帖应跑多模态，但管理端只认本地媒体文件：`resolve_media_path`（app.py:558）对 http/https URL 直接返回 None，图像/视频静默退化为 `analyze_image` 规则 mock（app.py:542，按 content_id/URL 里的演示魔法词打分），语音则整个跳过（app.py:1568 `if is_audio_media and media_path:`）。生产库现有 621 条 image 结果均为 mock 产物，真实多模态识别与证据落盘从未对 URL 媒体发生。

**爬虫端已改造**：回推批次的 `media_url` 现在是爬虫缓存媒体后自行构造的文件链接（非平台带签名的时效 URL），从管理端主机裸 GET 可达。本特性在识别阶段把该链接按需下载为本地临时文件，让真实多模态识别与证据落盘发生。

曾评估过"接收即预取队列 + 暂存区"方案（为对抗平台签名 URL 小时级过期而设计），因爬虫缓存化改造而废弃——识别在接收后秒级触发（`trigger_auto_recognize`），爬虫缓存存活期由对接方保障，懒加载已足够。

## 目标与约束

- 二次批次帖（`confirm_batch_id<>''`）且 `media_url` 为 http/https 时：识别阶段下载到本地临时文件 → 视觉/语音服务收到本地路径（证据帧 JPG / 风险片段 WAV 照常落盘）→ `finally` 删除临时文件。
- 下载失败不阻断识别：沿用现有 fallback 形态退化 mock，但把 `download_error` 写入 fusion 结果（该行必然写库），若视觉通道走过也同时写入 image 结果——退化**可见**、不再静默。
- 纯标准库（`urllib.request`）；不改两个识别服务；不改识别分流/融合；不改写 `media_url` 字段（原链接留库，详情页原片预览热链爬虫缓存）。
- 下载守卫：仅 http/https；单文件上限 200MB（对齐 `max_upload_mb`/`max_file_size_mb` 默认，env `MEDIA_DOWNLOAD_MAX_MB` 可覆盖）；总时长上限 120s（`urlopen(timeout=30)` 管连接/单次读阻塞 + 分块读循环内按墙钟累计强制，防慢速滴流）；跟随重定向（urllib 默认行为）。
- 首轮内容（文本粗筛）不碰媒体，完全不受影响。

## 设计

### 1. 下载函数（app.py 新增，唯一新单元）

`download_media_to_temp(media_url, content_type) -> tuple[Path | None, str | None]`

- `urllib.request.Request` 带通用浏览器 UA → `urlopen(timeout=...)` → 分块读入 `tempfile.NamedTemporaryFile(delete=False)`；累计超上限即中止、删除半成品、返回 `(None, "超过大小上限")`。
- 临时文件后缀决定下游路由（视觉服务按后缀收文件、`media_ext` 判定视觉/音频通道），推断顺序：URL path 后缀 ∈ 白名单（jpg/jpeg/png/bmp/webp/mp4/mov/avi/mkv/wav/mp3/m4a/aac/flac）→ 响应 Content-Type 映射 → 按 `content_type` 字段兜底（图片→.jpg、视频→.mp4、音频→.mp3）。
- 返回 `(临时文件 Path, None)` 或 `(None, 错误描述)`；不抛异常。

### 2. 识别侧接入（`recognize_content` 二次批次分支，app.py:1566 附近）

- 现有 `media_path = resolve_media_path(content["media_url"])` 之后：若 `media_path` 为 None 且 URL 为 http/https → 调下载函数，成功则 `media_path` 指向临时文件并记 `downloaded_tmp`，失败则记 `download_error`。
- `is_visual_media`/`is_audio_media` 判定沿用（下载后 `media_ext` 可从临时文件后缀取得）。
- 视觉调用把 `image_url` 传 `str(media_path)`（原为 `content["media_url"]`）——`resolve_media_path` 对绝对路径直接命中、`local_media_allowed` 白名单本含 `/tmp`（app.py:163-169），`analyze_image_with_vision` 内部机制零改动。语音分支本就直接消费 `media_path`。
- **evidence_frame 回指原链接**：下载场景中 `analyze_image_with_vision` 会把 `evidence_frame` 设为临时路径（app.py:925），识别后临时文件即删、该字段会悬空——拿到 `image_result` 后覆写 `image_result["evidence_frame"] = content["media_url"]`。标注证据帧本体已由视觉服务落盘 `storage/evidence/<content_id>/`，不受影响。
- 下载失败时：视觉照现状走 `analyze_image` mock，之后 `image_result["download_error"] = 错误串`；音频照现状跳过（`audio_result` 为 None，无 audio 行）；`download_error` 同时写入 fusion 结果 dict（fusion 行必然写库，覆盖音频-only 帖等无 image 行的情况）。
- `finally`：`downloaded_tmp` 非 None → `unlink(missing_ok=True)`。手动重识别批次帖走同一路径（再次下载），爬虫缓存在保留期内即可用。

### 3. 落盘链路（本特性后的完整图景）

- 结构化：`recognition_results` 逐模态 `result_json`（真实检测框/OCR/ASR 取代 mock）+ `content_items` 融合分 —— 机制已有，本特性让数据变真。
- 非结构化：`storage/evidence/<id>/*.jpg`（视觉标注帧）、`audio_storage/evidence/<id>/segment_*.wav`（风险语音段）、两服务 `uploads/` 副本 —— 均由服务侧既有逻辑落盘，本特性只是把字节送到位。
- 管理端临时文件不留存；原始媒体的权威副本在爬虫缓存。

## 测试

pytest 内起 stdlib `ThreadingHTTPServer` 模拟爬虫缓存文件服务器：

1. **下载喂路径**：批次视频帖 `media_url=http://127.0.0.1:<port>/v.mp4` → monkeypatch 视觉/语音调用捕获入参 → 断言收到真实存在的本地文件路径、识别 `completed`、识别结束后该临时文件已删除。
2. **失败可见**：404 链接 → 识别仍 `completed`（mock 退化），`recognition_results` 的 image 行与 fusion 行 `result_json` 均含 `download_error`。
3. **首轮不下载**：非批次帖带 http `media_url` → 下载函数不被调用（monkeypatch 计数为 0）。
4. **下载函数单测**：超限中止（env 覆盖小上限）、后缀推断（URL 后缀 / Content-Type / content_type 兜底三档）。
5. 全量 `python3 -m pytest` 无回归。

## 非目标（YAGNI）

- 不做接收时预取队列、`media_staging` 暂存区、孤儿清扫器（已废弃的 v1 设计）。
- 不改写 `media_url`；不支持鉴权 headers（爬虫链接裸 GET；将来加 token 再扩展）。
- 不做内网 IP 黑名单（SSRF）：链接由受信内部爬虫构造，设计上有意接受。
- 不动首轮文本粗筛、两个识别服务、融合权重。
- 不管理两服务 `uploads/` 副本的磁盘占用（既有行为，独立运维事项）。

## 对接约定（留痕）

- 爬虫缓存保留期 ≥ 识别消化周期（建议 ≥7 天，覆盖识别积压/人工重识别场景）。
- 文件链接需从管理端主机（试点 10.20.30.58）可达且无鉴权。
