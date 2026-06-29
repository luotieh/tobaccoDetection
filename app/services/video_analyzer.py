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
