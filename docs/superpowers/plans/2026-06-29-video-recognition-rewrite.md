# 视频识别模块重写 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重写视觉服务的视频识别模块，使其更快、识别质量更高、代码结构更清晰，同时保持 API 契约不变。

**Architecture:** 把单体方法 `VisionPipeline.infer_video()` 拆为三个可独立测试的单元——`FrameSampler`（seek 采样）、`FrameAnalyzer`（批量检测 + 每帧 OCR）、`VideoAggregator`（跨帧去重 + 覆盖度评分 + 组装结果）。检测器新增 `predict_batch` 批量推理。复用现有 YOLO 图像模型、`score_visual` 评分器与 `VideoVisualResult` schema。

**Tech Stack:** Python, FastAPI（视觉服务 `app/`）, ultralytics YOLO, OpenCV(cv2), pytest。

## Global Constraints

- **不改 API 契约**：`POST /infer/video` 端点、form 参数（`file`、`content_id`、`sample_fps`、`max_seconds`、`conf`、`model_id`）、响应结构 `VideoVisualResult` 全部保持不变。
- **不改 `score_visual()` 的签名**：`score_visual(detections, brand_results, ocr_texts, scene_tags, frequency_score=0.30)`。覆盖度作为 `frequency_score` 传入。
- **不引入真实跟踪器**（ByteTrack/DeepSORT）；去重用 IoU 贪心聚合。
- **不改** 多模态融合、文本/音频服务、前端、`VideoVisualResult` schema 字段。
- **测试约定**：从仓库根目录运行 `python -m pytest`；测试直接 `from app.services...` 导入；用 monkeypatch 设 `settings.use_mock_model = True` 触发 mock 检测器（见 `app/services/detector.py:62`）。
- **配置约定**：新配置加到 `app/config.py` 的 `Settings`（用 `env_float/env_int/env_bool`）+ `.env.example`（中文注释）。
- 保留现有 `VIDEO_OPEN_FAILED` 错误行为（无法打开视频时 `raise ValueError("VIDEO_OPEN_FAILED")`）。

---

## File Structure

- `app/config.py` — **修改**：新增 `video_track_iou`、`video_detect_batch`、`video_ocr_every_frame`。
- `.env.example` — **修改**：新增对应环境变量与注释。
- `app/services/detector.py` — **修改**：新增 `predict_batch`，`predict_image` 改为复用之，抽出 `_mock_detections`/`_results_to_detections` 助手。
- `app/services/video.py` — **重写**：新增 `FrameSampler` 类（seek 采样 + 顺序回退），保留 `VideoFrame`、`format_timestamp`，保留 `sample_video` 为薄包装。
- `app/services/video_analyzer.py` — **新增**：`FrameAnalysis` dataclass、`FrameAnalyzer`、`VideoAggregator`、纯函数 `iou`/`dedup_tracks`。
- `app/services/pipeline.py` — **修改**：`infer_video()` 改为接线三个单元。
- `tests/test_detector_batch.py`、`tests/test_frame_sampler.py`、`tests/test_video_analyzer.py`、`tests/test_video_pipeline.py`、`tests/test_video_config.py` — **新增**测试。

---

### Task 1: 新增视频配置项

**Files:**
- Modify: `app/config.py:46-49`（`Settings` 内 video 配置块）
- Modify: `.env.example`
- Test: `tests/test_video_config.py`

**Interfaces:**
- Produces: `settings.video_track_iou: float`（默认 0.5）、`settings.video_detect_batch: int`（默认 8）、`settings.video_ocr_every_frame: bool`（默认 True）。

- [ ] **Step 1: Write the failing test**

`tests/test_video_config.py`:
```python
from app.config import settings


def test_video_config_defaults():
    assert settings.video_track_iou == 0.5
    assert settings.video_detect_batch == 8
    assert settings.video_ocr_every_frame is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'video_track_iou'`

- [ ] **Step 3: Add config attributes**

在 `app/config.py` 的 `Settings` 类，紧跟现有 `max_upload_mb` 行（约第 49 行）之后加入：
```python
    video_track_iou: float = env_float("VIDEO_TRACK_IOU", 0.5)
    video_detect_batch: int = env_int("VIDEO_DETECT_BATCH", 8)
    video_ocr_every_frame: bool = env_bool("VIDEO_OCR_EVERY_FRAME", True)
```

在 `.env.example` 的视频相关段落追加：
```bash
# 跨帧去重的 bbox IoU 阈值（同类目标 IoU≥该值视为同一目标）
VIDEO_TRACK_IOU=0.5
# 每批送入检测器的帧数（批量推理）
VIDEO_DETECT_BATCH=8
# 是否对每个采样帧都跑 OCR（false 时仅对有检测框的帧跑 OCR）
VIDEO_OCR_EVERY_FRAME=true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py .env.example tests/test_video_config.py
git commit -m "feat(vision): 新增视频识别配置项 track_iou/detect_batch/ocr_every_frame"
```

---

### Task 2: 检测器批量推理 `predict_batch`

**Files:**
- Modify: `app/services/detector.py:112-152`（重构 `predict_image`，新增 `predict_batch` 与两个助手）
- Test: `tests/test_detector_batch.py`

**Interfaces:**
- Produces: `TobaccoDetector.predict_batch(images: list[np.ndarray], conf: float | None = None, timestamps: list[str | None] | None = None) -> list[list[Detection]]`——返回与 `images` 等长的列表，第 i 项是第 i 张图的检测，且每个 `Detection.timestamp` 取 `timestamps[i]`。
- Produces: `TobaccoDetector.predict_image(image, conf=None, timestamp=None) -> list[Detection]`（签名不变，内部改为 `self.predict_batch([image], conf, [timestamp])[0]`）。

- [ ] **Step 1: Write the failing test**

`tests/test_detector_batch.py`:
```python
import numpy as np

from app.config import settings
from app.services.detector import TobaccoDetector


def test_predict_batch_mock_maps_timestamps(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_model", True)
    detector = TobaccoDetector()
    images = [np.zeros((40, 60, 3), dtype=np.uint8) for _ in range(3)]
    timestamps = ["00:00:00.000", "00:00:01.000", "00:00:02.000"]
    batch = detector.predict_batch(images, timestamps=timestamps)
    assert len(batch) == 3
    assert all(len(frame_dets) == 1 for frame_dets in batch)
    assert [dets[0].timestamp for dets in batch] == timestamps


def test_predict_image_uses_batch(monkeypatch):
    monkeypatch.setattr(settings, "use_mock_model", True)
    detector = TobaccoDetector()
    dets = detector.predict_image(np.zeros((40, 60, 3), dtype=np.uint8), timestamp="00:00:05.000")
    assert len(dets) == 1
    assert dets[0].timestamp == "00:00:05.000"
    assert dets[0].class_name == "cigarette_pack"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_detector_batch.py -v`
Expected: FAIL with `AttributeError: 'TobaccoDetector' object has no attribute 'predict_batch'`

- [ ] **Step 3: Refactor detector to add batch path**

把 `app/services/detector.py` 现有 `predict_image`（112-152 行）整体替换为下面四个方法（保持 `import numpy as np` 等已有导入；`self.mock`、`self.model`、`self.infer_params`、`self.class_mapping`、`self.normalize_class` 均为已有成员）：

```python
    def _mock_detections(self, image: np.ndarray, timestamp: str | None) -> list[Detection]:
        h, w = image.shape[:2]
        return [
            Detection(
                class_name="cigarette_pack",
                label_zh=self.class_mapping["cigarette_pack"],
                bbox=[round(w * 0.3, 2), round(h * 0.3, 2), round(w * 0.7, 2), round(h * 0.7, 2)],
                confidence=0.76,
                timestamp=timestamp,
            )
        ]

    def _result_to_detections(self, result, timestamp: str | None) -> list[Detection]:
        names = getattr(result, "names", {}) or getattr(self.model, "names", {}) or {}
        detections: list[Detection] = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return detections
        for box in boxes:
            cls_id = int(box.cls[0].item())
            raw_name = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id)
            class_name = self.normalize_class(raw_name)
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            detections.append(
                Detection(
                    class_name=class_name,
                    label_zh=self.class_mapping.get(class_name, self.class_mapping["unknown"]),
                    bbox=[round(v, 2) for v in xyxy],
                    confidence=round(float(box.conf[0].item()), 4),
                    timestamp=timestamp,
                )
            )
        return detections

    def predict_batch(
        self,
        images: list[np.ndarray],
        conf: float | None = None,
        timestamps: list[str | None] | None = None,
    ) -> list[list[Detection]]:
        if not images:
            return []
        timestamps = timestamps if timestamps is not None else [None] * len(images)
        if self.mock or self.model is None:
            return [self._mock_detections(img, ts) for img, ts in zip(images, timestamps)]
        if conf is None:
            conf = self.infer_params.get("conf") or settings.yolo_conf
        results = self.model.predict(
            source=list(images),
            conf=conf,
            iou=self.infer_params.get("iou", settings.yolo_iou),
            imgsz=self.infer_params.get("imgsz", settings.yolo_img_size),
            verbose=False,
        )
        return [self._result_to_detections(r, ts) for r, ts in zip(results, timestamps)]

    def predict_image(self, image: np.ndarray, conf: float | None = None, timestamp: str | None = None) -> list[Detection]:
        return self.predict_batch([image], conf=conf, timestamps=[timestamp])[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_detector_batch.py tests/test_scoring.py -v`
Expected: PASS（含原有 scoring 测试，确认 `predict_image` 行为未回归）

- [ ] **Step 5: Commit**

```bash
git add app/services/detector.py tests/test_detector_batch.py
git commit -m "feat(vision): 检测器新增 predict_batch 批量推理，predict_image 复用之"
```

---

### Task 3: `FrameSampler` seek 采样

**Files:**
- Modify: `app/services/video.py`（重写，保留 `VideoFrame`、`format_timestamp`）
- Test: `tests/test_frame_sampler.py`

**Interfaces:**
- Consumes: `settings.video_sample_fps`、`settings.max_video_seconds`。
- Produces: `VideoFrame`（dataclass，字段 `image`、`frame_no`、`timestamp`，不变）。
- Produces: `FrameSampler().sample(path: Path, sample_fps: float | None = None, max_seconds: int | None = None) -> tuple[list[VideoFrame], float]`——返回采样帧列表与视频时长（秒，保留 3 位）。无法打开视频时 `raise ValueError("VIDEO_OPEN_FAILED")`。
- Produces: `sample_video(path, sample_fps=None, max_seconds=None)` 薄包装（委托给 `FrameSampler().sample`，保留供旧调用方）。

- [ ] **Step 1: Write the failing test**

`tests/test_frame_sampler.py`:
```python
import cv2
import numpy as np
import pytest

from app.services.video import FrameSampler, VideoFrame


def _write_video(path, fps=10, frames=30, size=(64, 48)):
    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, size)
    assert writer.isOpened()
    for i in range(frames):
        img = np.full((size[1], size[0], 3), i % 256, dtype=np.uint8)
        writer.write(img)
    writer.release()


def test_sample_step_and_timestamps(tmp_path):
    video = tmp_path / "clip.avi"
    _write_video(video, fps=10, frames=30)
    frames, duration = FrameSampler().sample(video, sample_fps=1.0, max_seconds=180)
    assert all(isinstance(f, VideoFrame) for f in frames)
    # 10fps, 1fps 采样 -> step=10, 帧号 0,10,20（idx30 越界）
    assert [f.frame_no for f in frames] == [0, 10, 20]
    assert [f.timestamp for f in frames] == ["00:00:00.000", "00:00:01.000", "00:00:02.000"]
    assert duration == pytest.approx(3.0, abs=0.2)


def test_max_seconds_limits_frames(tmp_path):
    video = tmp_path / "clip.avi"
    _write_video(video, fps=10, frames=30)
    frames, _ = FrameSampler().sample(video, sample_fps=1.0, max_seconds=1)
    # limit=1s -> max_frame=10 -> 帧号 0,10
    assert [f.frame_no for f in frames] == [0, 10]


def test_open_failure_raises(tmp_path):
    with pytest.raises(ValueError, match="VIDEO_OPEN_FAILED"):
        FrameSampler().sample(tmp_path / "nope.avi")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_frame_sampler.py -v`
Expected: FAIL with `ImportError: cannot import name 'FrameSampler'`

- [ ] **Step 3: Rewrite `app/services/video.py`**

整体替换文件内容为：
```python
from dataclasses import dataclass
from pathlib import Path

import cv2

from app.config import settings


@dataclass
class VideoFrame:
    image: object
    frame_no: int
    timestamp: str


def format_timestamp(seconds: float) -> str:
    ms = int((seconds - int(seconds)) * 1000)
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


class FrameSampler:
    def sample(
        self,
        path: Path,
        sample_fps: float | None = None,
        max_seconds: int | None = None,
    ) -> tuple[list[VideoFrame], float]:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError("VIDEO_OPEN_FAILED")
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = frame_count / fps if fps else 0
            limit = min(duration, float(max_seconds or settings.max_video_seconds))
            step = max(1, round(fps / max(sample_fps or settings.video_sample_fps, 0.1)))
            max_frame = int(limit * fps)
            targets = list(range(0, max_frame + 1, step))
            frames = self._seek_sample(cap, targets, fps)
            if not frames and targets:
                # seek 不可靠时回退顺序读取
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                frames = self._sequential_sample(cap, step, limit, fps)
        finally:
            cap.release()
        return frames, round(duration, 3)

    def _seek_sample(self, cap, targets: list[int], fps: float) -> list[VideoFrame]:
        frames: list[VideoFrame] = []
        for idx in targets:
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, idx):
                return []
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(VideoFrame(image=frame, frame_no=idx, timestamp=format_timestamp(idx / fps)))
        return frames

    def _sequential_sample(self, cap, step: int, limit: float, fps: float) -> list[VideoFrame]:
        frames: list[VideoFrame] = []
        frame_no = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts_seconds = frame_no / fps
            if ts_seconds > limit:
                break
            if frame_no % step == 0:
                frames.append(VideoFrame(image=frame, frame_no=frame_no, timestamp=format_timestamp(ts_seconds)))
            frame_no += 1
        return frames


def sample_video(path: Path, sample_fps: float | None = None, max_seconds: int | None = None) -> tuple[list[VideoFrame], float]:
    return FrameSampler().sample(path, sample_fps=sample_fps, max_seconds=max_seconds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_frame_sampler.py -v`
Expected: PASS（3 个测试。若运行环境的 OpenCV 不支持 MJPG 写出，测试会在 `_write_video` 的 assert 处失败——届时改用 `*"mp4v"` 与 `.mp4` 后缀。）

- [ ] **Step 5: Commit**

```bash
git add app/services/video.py tests/test_frame_sampler.py
git commit -m "feat(vision): FrameSampler 改用 seek 采样并保留顺序回退"
```

---

### Task 4: `FrameAnalyzer` 批量检测 + 每帧 OCR

**Files:**
- Create: `app/services/video_analyzer.py`
- Test: `tests/test_video_analyzer.py`（本任务只加 analyzer 相关用例）

**Interfaces:**
- Consumes: `TobaccoDetector.predict_batch`（Task 2）、`OCRService.recognize(image) -> list[OCRText]`、`VideoFrame`（Task 3）、`settings.video_detect_batch`、`settings.video_ocr_every_frame`。
- Produces: `FrameAnalysis`（dataclass：`frame: VideoFrame`、`detections: list[Detection]`、`ocr: list[OCRText]`）。
- Produces: `FrameAnalyzer(detector, ocr, batch_size=None, ocr_every_frame=None)`，方法 `analyze(frames: list[VideoFrame], conf=None) -> list[FrameAnalysis]`。

- [ ] **Step 1: Write the failing test**

`tests/test_video_analyzer.py`:
```python
from app.schemas import Detection, OCRText
from app.services.video import VideoFrame
from app.services.video_analyzer import FrameAnalyzer


class FakeDetector:
    def __init__(self):
        self.batch_sizes = []

    def predict_batch(self, images, conf=None, timestamps=None):
        self.batch_sizes.append(len(images))
        timestamps = timestamps or [None] * len(images)
        return [[Detection(class_name="cigarette", label_zh="香烟", bbox=[0, 0, 10, 10], confidence=0.9, timestamp=ts)] for ts in timestamps]


class FakeOCR:
    def __init__(self):
        self.calls = 0

    def recognize(self, image):
        self.calls += 1
        return [OCRText(text="中华", confidence=0.9)]


def _frames(n):
    return [VideoFrame(image=object(), frame_no=i, timestamp=f"00:00:0{i}.000") for i in range(n)]


def test_analyze_batches_by_size():
    detector = FakeDetector()
    analyzer = FrameAnalyzer(detector, FakeOCR(), batch_size=2)
    analyses = analyzer.analyze(_frames(5))
    assert len(analyses) == 5
    assert detector.batch_sizes == [2, 2, 1]
    assert analyses[0].detections[0].timestamp == "00:00:00.000"


def test_ocr_every_frame_true_runs_on_all():
    ocr = FakeOCR()
    FrameAnalyzer(FakeDetector(), ocr, ocr_every_frame=True).analyze(_frames(3))
    assert ocr.calls == 3


def test_ocr_every_frame_false_only_detected():
    class NoDetDetector(FakeDetector):
        def predict_batch(self, images, conf=None, timestamps=None):
            return [[] for _ in images]

    ocr = FakeOCR()
    FrameAnalyzer(NoDetDetector(), ocr, ocr_every_frame=False).analyze(_frames(3))
    assert ocr.calls == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_analyzer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.video_analyzer'`

- [ ] **Step 3: Create `app/services/video_analyzer.py` (analyzer 部分)**

```python
from dataclasses import dataclass, field

from app.config import settings
from app.schemas import Detection, OCRText
from app.services.video import VideoFrame


@dataclass
class FrameAnalysis:
    frame: VideoFrame
    detections: list[Detection] = field(default_factory=list)
    ocr: list[OCRText] = field(default_factory=list)


class FrameAnalyzer:
    def __init__(self, detector, ocr, batch_size: int | None = None, ocr_every_frame: bool | None = None):
        self.detector = detector
        self.ocr = ocr
        self.batch_size = batch_size or settings.video_detect_batch
        self.ocr_every_frame = settings.video_ocr_every_frame if ocr_every_frame is None else ocr_every_frame

    def analyze(self, frames: list[VideoFrame], conf: float | None = None) -> list[FrameAnalysis]:
        analyses: list[FrameAnalysis] = []
        for start in range(0, len(frames), self.batch_size):
            batch = frames[start:start + self.batch_size]
            dets = self.detector.predict_batch(
                [f.image for f in batch],
                conf=conf,
                timestamps=[f.timestamp for f in batch],
            )
            for frame, frame_dets in zip(batch, dets):
                frame_ocr = self.ocr.recognize(frame.image) if (self.ocr_every_frame or frame_dets) else []
                analyses.append(FrameAnalysis(frame=frame, detections=frame_dets, ocr=frame_ocr))
        return analyses
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_analyzer.py -v`
Expected: PASS（3 个 analyzer 用例）

- [ ] **Step 5: Commit**

```bash
git add app/services/video_analyzer.py tests/test_video_analyzer.py
git commit -m "feat(vision): 新增 FrameAnalyzer 批量检测+每帧OCR"
```

---

### Task 5: `VideoAggregator` 跨帧去重 + 覆盖度评分

**Files:**
- Modify: `app/services/video_analyzer.py`（追加 `iou`、`dedup_tracks`、`VideoAggregator`）
- Test: `tests/test_video_analyzer.py`（追加去重/覆盖度用例）

**Interfaces:**
- Consumes: `FrameAnalysis`（Task 4）、`infer_scene_tags`/`score_visual`（`app/services/scoring.py`）、`save_evidence_image`（`app/services/evidence.py`）、`BrandMatcher.match(ocr) -> list[BrandResult]`、`settings.video_track_iou`、`settings.max_evidence_frames`、`VideoVisualResult`（`app/schemas.py`）。
- Produces: `iou(box_a: list[float], box_b: list[float]) -> float`。
- Produces: `dedup_tracks(detections: list[Detection], iou_threshold: float) -> list[Detection]`——同类相邻 bbox IoU≥阈值并入一条轨迹，每轨迹输出置信度最高的代表。
- Produces: `VideoAggregator(brand_matcher, iou_threshold=None)`，方法 `build(content_id: str, analyses: list[FrameAnalysis], duration: float, sampled_frames: int) -> VideoVisualResult`。覆盖度 `coverage = frames_with_detection / max(1, sampled_frames)` 传入 `score_visual` 的 `frequency_score`。

- [ ] **Step 1: Write the failing test**

在 `tests/test_video_analyzer.py` 追加：
```python
from app.schemas import BrandResult
from app.services.video_analyzer import iou, dedup_tracks, VideoAggregator, FrameAnalysis


def _det(name, bbox, conf, ts="00:00:00.000"):
    return Detection(class_name=name, label_zh=name, bbox=bbox, confidence=conf, timestamp=ts)


def test_iou_basic():
    assert iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert iou([0, 0, 10, 10], [100, 100, 110, 110]) == 0.0


def test_dedup_merges_overlapping_same_class():
    dets = [
        _det("cigarette_pack", [0, 0, 10, 10], 0.7, "00:00:00.000"),
        _det("cigarette_pack", [1, 1, 11, 11], 0.9, "00:00:01.000"),  # 与上重叠 -> 同轨迹
        _det("cigarette_pack", [500, 500, 510, 510], 0.8, "00:00:02.000"),  # 远处 -> 新轨迹
    ]
    reps = dedup_tracks(dets, 0.5)
    assert len(reps) == 2
    assert reps[0].confidence == 0.9  # 代表取最高置信度


def test_dedup_keeps_different_classes_separate():
    dets = [_det("cigarette", [0, 0, 10, 10], 0.8), _det("cigarette_pack", [0, 0, 10, 10], 0.8)]
    assert len(dedup_tracks(dets, 0.5)) == 2


def test_aggregator_coverage(monkeypatch):
    import app.services.video_analyzer as va
    monkeypatch.setattr(va, "save_evidence_image", lambda *a, **k: None)

    class FakeBrand:
        def match(self, ocr):
            return []

    f0 = FrameAnalysis(frame=VideoFrame(object(), 0, "00:00:00.000"),
                       detections=[_det("cigarette_pack", [0, 0, 10, 10], 0.9)], ocr=[])
    f1 = FrameAnalysis(frame=VideoFrame(object(), 10, "00:00:01.000"), detections=[], ocr=[])
    result = VideoAggregator(FakeBrand()).build("vid_test", [f0, f1], duration=2.0, sampled_frames=2)
    assert result.media_type == "video"
    assert result.duration_seconds == 2.0
    assert result.sampled_frames == 2
    assert len(result.detected_objects) == 1  # 去重后
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_analyzer.py -v`
Expected: FAIL with `ImportError: cannot import name 'iou'`

- [ ] **Step 3: 追加 aggregator 实现**

在 `app/services/video_analyzer.py` 顶部 import 区追加：
```python
from app.schemas import VideoVisualResult
from app.services.brand_matcher import BrandMatcher
from app.services.evidence import save_evidence_image
from app.services.scoring import infer_scene_tags, score_visual
```

在文件末尾追加：
```python
def iou(box_a: list[float], box_b: list[float]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def dedup_tracks(detections: list[Detection], iou_threshold: float) -> list[Detection]:
    # 每条轨迹: {"last": bbox, "rep": Detection}
    tracks: list[dict] = []
    ordered = sorted(detections, key=lambda d: (d.class_name, d.timestamp or ""))
    for det in ordered:
        match = None
        for track in tracks:
            if track["rep"].class_name == det.class_name and iou(track["last"], det.bbox) >= iou_threshold:
                match = track
                break
        if match is None:
            tracks.append({"last": det.bbox, "rep": det})
        else:
            match["last"] = det.bbox
            if det.confidence > match["rep"].confidence:
                match["rep"] = det
    return [t["rep"] for t in tracks]


class VideoAggregator:
    def __init__(self, brand_matcher: BrandMatcher, iou_threshold: float | None = None):
        self.brand_matcher = brand_matcher
        self.iou_threshold = settings.video_track_iou if iou_threshold is None else iou_threshold

    def build(self, content_id: str, analyses: list[FrameAnalysis], duration: float, sampled_frames: int) -> VideoVisualResult:
        all_detections = [d for a in analyses for d in a.detections]
        all_ocr = [o for a in analyses for o in a.ocr]
        reps = dedup_tracks(all_detections, self.iou_threshold)
        brand_results = self.brand_matcher.match(all_ocr)
        scene_tags = infer_scene_tags(reps, all_ocr)
        frames_with_det = sum(1 for a in analyses if a.detections)
        coverage = frames_with_det / max(1, sampled_frames)
        visual_score, risk_level = score_visual(reps, brand_results, all_ocr, scene_tags, frequency_score=coverage)
        evidence_frames = self._select_evidence(content_id, analyses)
        return VideoVisualResult(
            content_id=content_id,
            media_type="video",
            duration_seconds=duration,
            sampled_frames=sampled_frames,
            visual_score=visual_score,
            risk_level=risk_level,
            detected_objects=reps,
            brand_results=brand_results,
            ocr_text=all_ocr,
            scene_tags=scene_tags,
            evidence_frames=evidence_frames,
        )

    def _select_evidence(self, content_id: str, analyses: list[FrameAnalysis]) -> list:
        evidence = []
        for analysis in analyses:
            if not analysis.detections or len(evidence) >= settings.max_evidence_frames:
                continue
            evidence.append(
                save_evidence_image(
                    analysis.frame.image,
                    content_id,
                    analysis.detections,
                    analysis.ocr,
                    infer_scene_tags(analysis.detections, analysis.ocr),
                    filename=f"frame_{analysis.frame.frame_no:06d}.jpg",
                    timestamp=analysis.frame.timestamp,
                )
            )
        return evidence
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_video_analyzer.py -v`
Expected: PASS（analyzer + aggregator 全部用例）

- [ ] **Step 5: Commit**

```bash
git add app/services/video_analyzer.py tests/test_video_analyzer.py
git commit -m "feat(vision): 新增 VideoAggregator 跨帧去重+覆盖度评分"
```

---

### Task 6: 接线 `VisionPipeline.infer_video` + 端到端测试

**Files:**
- Modify: `app/services/pipeline.py:13`（import）、`pipeline.py:30-34`（`__init__`）、`pipeline.py:59-107`（`infer_video`）
- Test: `tests/test_video_pipeline.py`

**Interfaces:**
- Consumes: `FrameSampler`（Task 3）、`FrameAnalyzer`（Task 4）、`VideoAggregator`（Task 5）。
- Produces: `VisionPipeline.infer_video(video_path, content_id, sample_fps=None, max_seconds=None, conf=None, model_id=None) -> VideoVisualResult`（签名不变）。

- [ ] **Step 1: Write the failing test**

`tests/test_video_pipeline.py`:
```python
import cv2
import numpy as np

from app.config import settings
from app.services.pipeline import VisionPipeline


def _write_video(path, fps=10, frames=20, size=(64, 48)):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, size)
    assert writer.isOpened()
    for i in range(frames):
        writer.write(np.full((size[1], size[0], 3), i % 256, dtype=np.uint8))
    writer.release()


def test_infer_video_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "use_mock_model", True)
    video = tmp_path / "clip.avi"
    _write_video(video, fps=10, frames=20)
    pipeline = VisionPipeline()
    result = pipeline.infer_video(video, content_id="vid_e2e", sample_fps=1.0)
    assert result.media_type == "video"
    assert result.sampled_frames > 0
    assert result.duration_seconds > 0
    assert result.risk_level in {"high", "medium", "low", "none"}
    # mock 每帧返回相同 bbox 的烟盒 -> 去重为 1
    assert len(result.detected_objects) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_video_pipeline.py -v`
Expected: FAIL（旧 `infer_video` 仍逐帧 `predict_image`，`detected_objects` 不会被去重，断言 `== 1` 失败；或在重写前先确认红）

- [ ] **Step 3: Rewrite pipeline wiring**

把 `app/services/pipeline.py` 第 13 行 `from app.services.video import sample_video` 改为：
```python
from app.services.video import FrameSampler
from app.services.video_analyzer import FrameAnalyzer, VideoAggregator
```

在 `__init__`（约 30-34 行）的 `self.brand_matcher = BrandMatcher()` 之后追加：
```python
        self.sampler = FrameSampler()
```

把整个 `infer_video` 方法（59-107 行）替换为：
```python
    def infer_video(
        self,
        video_path: Path,
        content_id: str,
        sample_fps: float | None = None,
        max_seconds: int | None = None,
        conf: float | None = None,
        model_id: str | None = None,
    ) -> VideoVisualResult:
        frames, duration = self.sampler.sample(video_path, sample_fps=sample_fps, max_seconds=max_seconds)
        analyzer = FrameAnalyzer(self.get_detector(model_id), self.ocr)
        analyses = analyzer.analyze(frames, conf=conf)
        aggregator = VideoAggregator(self.brand_matcher)
        result = aggregator.build(content_id, analyses, duration, len(frames))
        self.save_result(result)
        return result
```

- [ ] **Step 4: Run the full vision test suite**

Run: `python -m pytest tests/test_video_pipeline.py tests/test_frame_sampler.py tests/test_video_analyzer.py tests/test_detector_batch.py tests/test_scoring.py tests/test_brand_matcher.py -v`
Expected: PASS（全部）

- [ ] **Step 5: Commit**

```bash
git add app/services/pipeline.py tests/test_video_pipeline.py
git commit -m "feat(vision): infer_video 接线 FrameSampler/FrameAnalyzer/VideoAggregator"
```

---

### Task 7: 全量回归与清理

**Files:** 无新增（验证步骤）

- [ ] **Step 1: 运行完整测试套件**

Run: `python -m pytest -q`
Expected: 全绿。若有失败，定位是否因本次改动（重点看任何 import 了 `sample_video` 的旧代码——已保留薄包装，应无影响）。

- [ ] **Step 2: 确认无遗留引用**

Run: `grep -rn "frequency = 0.80\|\.predict_image(frame" app/`
Expected: 无输出（旧逐帧逻辑已移除）。

- [ ] **Step 3: Commit（如有清理）**

```bash
git add -A
git commit -m "chore(vision): 视频识别重写收尾回归"
```

---

## Self-Review

**Spec coverage：**
- seek 采样 → Task 3 ✓
- 批量推理 → Task 2 ✓
- 每帧 OCR + 开关 → Task 4 ✓
- 覆盖度替代 frequency → Task 5（`coverage` 传 `frequency_score`）✓
- 跨帧去重/轨迹 → Task 5（`dedup_tracks`）✓
- 三单元架构 → Task 3/4/5，接线 Task 6 ✓
- 新增配置 + .env.example → Task 1 ✓
- 证据帧上限沿用 → Task 5 `_select_evidence` ✓
- API 契约不变 → Task 6 保持 `infer_video` 签名、`VideoVisualResult` 不变 ✓
- 测试矩阵（sampler/batch/analyzer/aggregator/e2e）→ 各任务 ✓

**Placeholder scan：** 无 TBD/TODO；每个代码步骤含完整代码与精确命令。

**Type consistency：** `predict_batch` 返回 `list[list[Detection]]` 在 Task 2 定义、Task 4 消费一致；`FrameAnalysis` 字段在 Task 4 定义、Task 5 消费一致；`dedup_tracks(detections, iou_threshold)`、`VideoAggregator.build(content_id, analyses, duration, sampled_frames)` 在 Task 5 定义、Task 6 调用一致；`FrameSampler().sample(path, sample_fps, max_seconds)` Task 3 定义、Task 6 调用一致。
