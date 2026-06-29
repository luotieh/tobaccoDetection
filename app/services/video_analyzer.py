from dataclasses import dataclass, field

from app.config import settings
from app.schemas import Detection, OCRText, VideoVisualResult
from app.services.video import VideoFrame
from app.services.brand_matcher import BrandMatcher
from app.services.evidence import save_evidence_image
from app.services.scoring import infer_scene_tags, score_visual


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
            result = save_evidence_image(
                analysis.frame.image,
                content_id,
                analysis.detections,
                analysis.ocr,
                infer_scene_tags(analysis.detections, analysis.ocr),
                filename=f"frame_{analysis.frame.frame_no:06d}.jpg",
                timestamp=analysis.frame.timestamp,
            )
            if result is not None:
                evidence.append(result)
        return evidence
