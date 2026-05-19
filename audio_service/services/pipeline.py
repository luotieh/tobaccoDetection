import json
from pathlib import Path

from audio_service.config import settings
from audio_service.schemas import AudioRiskResult
from audio_service.services.asr_external import ExternalASR
from audio_service.services.asr_funasr import FunASRASR
from audio_service.services.asr_mock import MockASR
from audio_service.services.asr_whisper import WhisperASR
from audio_service.services.audio_preprocess import AudioPreprocessor
from audio_service.services.evidence import build_evidence
from audio_service.services.explanation import explain
from audio_service.services.keyword_matcher import AudioKeywordMatcher
from audio_service.services.media import MediaService
from audio_service.services.scoring import score_audio_with_types
from common.utils.entity_extractor import EntityExtractor


class AudioRiskPipeline:
    def __init__(self):
        self.media = MediaService()
        self.preprocess = AudioPreprocessor()
        self.matcher = AudioKeywordMatcher()
        self.extractor = EntityExtractor()
        if settings.asr_engine == "whisper":
            self.asr = WhisperASR()
        elif settings.asr_engine == "funasr":
            self.asr = FunASRASR()
        elif settings.asr_engine == "external":
            self.asr = ExternalASR()
        else:
            self.asr = MockASR()

    def info(self) -> dict:
        return {
            "asr": {"engine": settings.asr_engine, "model_dir": str(settings.asr_model_dir), "language": settings.asr_language, "device": settings.asr_device},
            "rules": {"enabled": True, "dictionaries": ["audio_risk_keywords", "brand_keywords", "whitelist_keywords"]},
        }

    def infer(self, media_path: Path, content_id: str, media_type: str, save_evidence: bool = True) -> AudioRiskResult:
        duration = self.media.get_duration(media_path)
        audio_path = self.media.extract_audio_from_video(media_path, content_id) if media_type == "video" else self.preprocess.to_16k_mono(media_path, content_id)
        asr_result = self.asr.transcribe(str(audio_path), duration)
        hits = self.matcher.match(asr_result.segments, asr_result.transcript)
        brands = self.matcher.match_brands(asr_result.transcript)
        contacts = self.extractor.extract_contacts(asr_result.transcript)
        score, level, risk_types = score_audio_with_types(hits, brands, contacts)
        evidence = build_evidence(content_id, asr_result.segments, hits, str(audio_path)) if save_evidence else []
        result = AudioRiskResult(
            content_id=content_id,
            media_type=media_type,
            duration_seconds=duration,
            audio_score=score,
            risk_level=level,
            risk_types=risk_types,
            transcript=asr_result.transcript,
            segments=asr_result.segments,
            hit_keywords=hits,
            brand_entities=brands,
            contact_entities=contacts,
            evidence_segments=evidence,
            explanation=explain(hits, brands),
        )
        self.save_result(result)
        return result

    def save_result(self, result: AudioRiskResult) -> None:
        result_dir = settings.resolve(settings.result_dir)
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / f"{result.content_id}.json").write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")


pipeline = AudioRiskPipeline()
