import json
from pathlib import Path

import cv2

from app.config import ROOT_DIR, settings
from app.schemas import VisualResult, VideoVisualResult
from app.services.brand_matcher import BrandMatcher
from app.services.detector import TobaccoDetector
from app.services.evidence import save_evidence_image
from app.services.ocr import OCRService
from app.services.scoring import infer_scene_tags, score_visual
from app.services.video import sample_video


class VisionPipeline:
    def __init__(self):
        self.detectors: dict[str, TobaccoDetector] = {}
        self.detector = self.get_detector()
        self.ocr = OCRService()
        self.brand_matcher = BrandMatcher()

    def get_detector(self, model_id: str | None = None) -> TobaccoDetector:
        key = model_id or "default"
        if key not in self.detectors:
            self.detectors[key] = TobaccoDetector(model_id=model_id)
        return self.detectors[key]

    def model_info(self, model_id: str | None = None) -> dict:
        detector = self.get_detector(model_id)
        return {
            "detector": detector.info(),
            "ocr": {"enabled": self.ocr.enabled, "engine": self.ocr.engine_name, "mock": self.ocr.mock},
        }

    def infer_image(self, image, content_id: str, conf: float | None = None, save_evidence: bool = True, model_id: str | None = None) -> VisualResult:
        detections = self.get_detector(model_id).predict_image(image, conf=conf)
        ocr_texts = self.ocr.recognize(image)
        brand_results = self.brand_matcher.match(ocr_texts)
        scene_tags = infer_scene_tags(detections, ocr_texts)
        visual_score, risk_level = score_visual(detections, brand_results, ocr_texts, scene_tags, frequency_score=0.30)
        evidence_frames = []
        if save_evidence and detections:
            evidence_frames.append(save_evidence_image(image, content_id, detections, ocr_texts, scene_tags))
        result = VisualResult(
            content_id=content_id,
            media_type="image",
            visual_score=visual_score,
            risk_level=risk_level,
            detected_objects=detections,
            brand_results=brand_results,
            ocr_text=ocr_texts,
            scene_tags=scene_tags,
            evidence_frames=evidence_frames,
        )
        self.save_result(result)
        return result

    def infer_video(
        self,
        video_path: Path,
        content_id: str,
        sample_fps: float | None = None,
        max_seconds: int | None = None,
        conf: float | None = None,
        model_id: str | None = None,
    ) -> VideoVisualResult:
        frames, duration = sample_video(video_path, sample_fps=sample_fps, max_seconds=max_seconds)
        all_detections = []
        all_ocr = []
        evidence_frames = []
        for index, frame in enumerate(frames):
            detections = self.get_detector(model_id).predict_image(frame.image, conf=conf, timestamp=frame.timestamp)
            all_detections.extend(detections)
            frame_ocr = self.ocr.recognize(frame.image) if detections else []
            all_ocr.extend(frame_ocr)
            if detections and len(evidence_frames) < settings.max_evidence_frames:
                evidence_frames.append(
                    save_evidence_image(
                        frame.image,
                        content_id,
                        detections,
                        frame_ocr,
                        infer_scene_tags(detections, frame_ocr),
                        filename=f"frame_{frame.frame_no:06d}.jpg",
                        timestamp=frame.timestamp,
                    )
                )
        brand_results = self.brand_matcher.match(all_ocr)
        scene_tags = infer_scene_tags(all_detections, all_ocr)
        frequency = 0.80 if len({d.timestamp for d in all_detections if d.timestamp}) >= 2 else 0.30
        visual_score, risk_level = score_visual(all_detections, brand_results, all_ocr, scene_tags, frequency_score=frequency)
        result = VideoVisualResult(
            content_id=content_id,
            media_type="video",
            duration_seconds=duration,
            sampled_frames=len(frames),
            visual_score=visual_score,
            risk_level=risk_level,
            detected_objects=all_detections,
            brand_results=brand_results,
            ocr_text=all_ocr,
            scene_tags=scene_tags,
            evidence_frames=evidence_frames,
        )
        self.save_result(result)
        return result

    def save_result(self, result: VisualResult) -> None:
        result_dir = settings.resolve(settings.result_dir)
        result_dir.mkdir(parents=True, exist_ok=True)
        payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result.dict()
        (result_dir / f"{result.content_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


pipeline = VisionPipeline()
