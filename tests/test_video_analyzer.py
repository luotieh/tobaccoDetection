from app.schemas import Detection, OCRText, BrandResult
from app.services.video import VideoFrame
from app.services.video_analyzer import FrameAnalyzer, iou, dedup_tracks, VideoAggregator, FrameAnalysis


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

    # Spy on score_visual to capture frequency_score argument
    captured = {}
    def spy_score_visual(detections, brand_results, ocr_texts, scene_tags, frequency_score=0.30):
        captured['frequency_score'] = frequency_score
        return (0.0, "none")

    monkeypatch.setattr(va, "score_visual", spy_score_visual)

    f0 = FrameAnalysis(frame=VideoFrame(object(), 0, "00:00:00.000"),
                       detections=[_det("cigarette_pack", [0, 0, 10, 10], 0.9)], ocr=[])
    f1 = FrameAnalysis(frame=VideoFrame(object(), 10, "00:00:01.000"), detections=[], ocr=[])
    result = VideoAggregator(FakeBrand()).build("vid_test", [f0, f1], duration=2.0, sampled_frames=2)
    assert result.media_type == "video"
    assert result.duration_seconds == 2.0
    assert result.sampled_frames == 2
    assert len(result.detected_objects) == 1  # 去重后
    assert captured['frequency_score'] == 0.5  # 1 frame with detection / 2 sampled frames
