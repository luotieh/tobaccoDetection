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
