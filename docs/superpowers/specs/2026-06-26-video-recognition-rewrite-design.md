# 视频识别模块重写 — 设计文档

日期：2026-06-26
分支：audio
状态：已确认设计，待实现

## 背景

视觉服务（`app/`）已存在一个端到端可用的视频识别模块：`POST /infer/video`
→ `VisionPipeline.infer_video()` → `sample_video()` 帧采样 → 逐帧调用 YOLO 图像检测器
`predict_image()` → 聚合 → `score_visual()` → `VideoVisualResult`。

该实现是最小可用版本，但存在三类问题，决定**重写**（保留现有 YOLO 图像模型）：

1. **性能/速度**：`sample_video` 逐帧 `cap.read()` 解码后在 Python 里跳帧；逐帧单张推理。长视频慢。
2. **识别质量**：OCR 只在有检测框的帧上跑；`frequency` 只有 `0.80/0.30` 两档启发式；同一目标跨帧重复计数。
3. **架构/代码结构**：`infer_video()` 是一个 49 行的单体方法，难以独立测试与扩展。

## 目标与约束

- 保留现有 YOLO 图像检测器（`predict_image` 的底层模型），不换模型。
- **不改 API 契约**：同一 `POST /infer/video` 端点、同样的 form 参数
  （`file`、`content_id`、`sample_fps`、`max_seconds`、`conf`、`model_id`）、
  同样的响应结构 `VideoVisualResult`。是 drop-in 替换，`app.py`
  的 `call_vision_video_service()` 与前端无需改动。
- 不改 `score_visual()` 的签名。
- 最小可用版本：去重采用轻量 IoU 贪心聚合，**不引入** ByteTrack 等真实跟踪器。

## 架构 — 单体拆为 3 个单元

| 单元 | 文件 | 职责 | 依赖 |
|---|---|---|---|
| `FrameSampler` | `app/services/video.py`（重写） | seek 采样 → `list[VideoFrame]` + duration | cv2 |
| `FrameAnalyzer` | `app/services/video_analyzer.py`（新增） | 逐帧**批量**检测 + 每帧 OCR → `list[FrameAnalysis]` | detector, ocr |
| `VideoAggregator` | `app/services/video_analyzer.py`（新增） | 跨帧去重(轨迹)、覆盖度、场景标签、证据帧选择、调用 `score_visual` → `VideoVisualResult` | scoring, brand_matcher, evidence |

`VisionPipeline.infer_video()` 收缩为接线：
`sampler.sample() → analyzer.analyze() → aggregator.build()`。

### 中间数据结构

- `VideoFrame`（已存在，保留）：`image`、`frame_no`、`timestamp`。
- `FrameAnalysis`（新增 dataclass，仅内部使用，不进 schema）：
  `frame: VideoFrame`、`detections: list[Detection]`、`ocr: list[OCRText]`。

## 行为变更（3 质量 + 2 性能）

### 1. seek 采样（性能）
`FrameSampler` 先算目标帧索引 `[0, step, 2·step, …]`（`step = max(1, round(fps / sample_fps))`），
上限为 `min(duration, max_seconds)` 对应的帧。对每个目标索引
`cap.set(CAP_PROP_POS_FRAMES, idx)` + `cap.read()`。
若某编码 seek 不可靠（读到的帧号偏差过大或 set 返回失败），回退为顺序读取跳帧的旧逻辑。
`VIDEO_OPEN_FAILED` 行为保持不变。

### 2. 批量推理（性能）
`detector.py` 新增 `predict_batch(images: list[np.ndarray], conf, timestamps: list[str]) -> list[list[Detection]]`，
向 `model.predict(source=[...])` 传列表（ultralytics 原生批量），N 帧一次推理。
mock 分支返回每张一个确定性检测，逐张带上对应 `timestamp`。
现有 `predict_image()` 保留为单图路径（图像端点继续用它）。
`FrameAnalyzer` 按 `VIDEO_DETECT_BATCH` 大小分批调用 `predict_batch`。

### 3. 每帧 OCR（质量）
`FrameAnalyzer` 对所有采样帧跑 OCR（受 `VIDEO_OCR_EVERY_FRAME` 开关控制；
关时退回“仅有检测框的帧跑 OCR”的旧行为）。
帧数本身已被 `sample_fps`/`max_seconds` 限定，故 OCR 调用次数有上界。

### 4. 覆盖度评分替代 frequency 启发式（质量）
`coverage = frames_with_detection / max(1, sampled_frames)`，连续 0–1。
作为 `frequency_score` 传入 `score_visual(..., frequency_score=coverage)`。
**不改 `score_visual`**——它已接收该参数并以 0.10 权重计入。去掉 `0.80/0.30` 的两档断崖。

### 5. 跨帧去重 / 轨迹聚合（质量）
贪心聚类：按 `class_name` 分组；同类中，相邻（按 `frame_no` 排序）检测若
bbox IoU ≥ `VIDEO_TRACK_IOU` 则并入同一“轨迹”。
- `detected_objects` 每条轨迹输出一个代表（该轨迹中置信度最高的帧的检测）。
- 轨迹（去重后的唯一目标数）用于 `score_visual` 的 `pack_count` 等场景判断，
  使场景评分不被“同一烟盒出现 10 秒”虚高。
- `score_visual` 接收的 `detections` 为去重后的代表集合；
  `coverage` 仍基于原始“有检测的帧数 / 采样帧数”计算（覆盖度反映时间占比，与去重无关）。

### 证据帧选择
延续现有上限 `MAX_EVIDENCE_FRAMES`。优先选取含轨迹代表（高置信度）的帧，
画框写入 `storage/evidence/{content_id}/frame_{frame_no:06d}.jpg`，逻辑沿用 `save_evidence_image()`。

## 新增配置

`app/config.py`（`Settings` 类，沿用 `env_*` helper）与 `.env.example`
（`${VAR:-default}` 约定 + 中文注释）：

- `VIDEO_TRACK_IOU`（默认 `0.5`）— 去重 IoU 阈值。
- `VIDEO_DETECT_BATCH`（默认 `8`）— 每批推理帧数。
- `VIDEO_OCR_EVERY_FRAME`（默认 `true`）— 关闭时退回“仅检测帧跑 OCR”，作为 OCR 过慢时的逃生口。

复用现有：`VIDEO_SAMPLE_FPS`、`MAX_VIDEO_SECONDS`、`MAX_EVIDENCE_FRAMES`。

## 测试

`USE_MOCK_MODEL=true`（mock 检测器返回确定性烟盒）下的单元测试：

- `FrameSampler`：尊重 `step`/`limit`；目标帧数符合预期；seek 失败时回退路径可用。
- `detector.predict_batch`：N 张输入返回 N 组检测，timestamp 一一对应；mock 分支正确。
- `FrameAnalyzer`：按 `VIDEO_DETECT_BATCH` 正确分批；`VIDEO_OCR_EVERY_FRAME` 开/关行为正确。
- `VideoAggregator`：重叠框（IoU ≥ 阈值）聚为一条轨迹并只输出一个代表；`coverage` 计算正确。
- 端到端：对一段极小合成视频调用 `infer_video()`，断言响应 schema 与字段
  （`media_type="video"`、`duration_seconds`、`sampled_frames`）保持不变。

参考现有测试约定：`tests/`（如 `tests/test_fusion_scoring.py`）。

## 非目标（YAGNI）

- 不引入真实多目标跟踪器（ByteTrack/DeepSORT）。
- 不改多模态融合 `analyze_fusion`、不改文本/音频服务。
- 不改前端、不改 `VideoVisualResult` schema 字段。
- 不修复 `scripts/infer_video.py` 硬编码端口（与本次重写无关，最多顺手记录）。
