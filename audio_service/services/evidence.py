from audio_service.config import settings
from audio_service.schemas import ASRSegment, AudioKeywordHit, EvidenceSegment
from audio_service.utils.file_utils import ensure_dir


def build_evidence(content_id: str, segments: list[ASRSegment], hits: list[AudioKeywordHit]) -> list[EvidenceSegment]:
    risky = [segment for segment in segments if any(hit.segment_text == segment.text for hit in hits[:20])]
    output = []
    evidence_dir = ensure_dir(settings.resolve(settings.evidence_dir) / content_id)
    for idx, segment in enumerate(risky[:5], 1):
        path = evidence_dir / f"segment_{idx:03d}.wav"
        path.write_bytes(b"")
        output.append(EvidenceSegment(start=segment.start, end=segment.end, audio_path=str(path.relative_to(settings.resolve(__import__("pathlib").Path(".")))), text=segment.text, description=describe(segment.text, hits)))
    return output


def describe(text: str, hits: list[AudioKeywordHit]) -> str:
    categories = {hit.category for hit in hits if hit.segment_text == text}
    if "trade" in categories and "contact" in categories:
        return "语音片段中出现交易词和联系方式暗示。"
    if "trade" in categories:
        return "语音片段中出现到货、私聊或拿货等交易表达。"
    if categories & {"anti_smoking", "news", "education"}:
        return "语音片段疑似新闻、控烟或公益语境。"
    return "语音片段命中风险关键词。"
