import shutil
import subprocess

from audio_service.config import settings
from audio_service.schemas import ASRSegment, AudioKeywordHit, EvidenceSegment
from audio_service.utils.file_utils import ensure_dir


class EvidenceService:
    def export_audio_segment(self, audio_path: str, content_id: str, start: float, end: float, index: int) -> str:
        evidence_dir = ensure_dir(settings.resolve(settings.evidence_dir) / content_id)
        path = evidence_dir / f"segment_{index:03d}.wav"
        if shutil.which("ffmpeg") and audio_path:
            command = ["ffmpeg", "-y", "-i", audio_path, "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-c", "copy", str(path)]
            proc = subprocess.run(command, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                fallback = ["ffmpeg", "-y", "-i", audio_path, "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-ac", "1", "-ar", str(settings.audio_sample_rate), str(path)]
                proc = subprocess.run(fallback, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                return str(path.relative_to(settings.resolve(__import__("pathlib").Path("."))))
        path.write_bytes(b"")
        return str(path.relative_to(settings.resolve(__import__("pathlib").Path("."))))


def build_evidence(content_id: str, segments: list[ASRSegment], hits: list[AudioKeywordHit], audio_path: str = "") -> list[EvidenceSegment]:
    risky = [segment for segment in segments if any(hit.segment_text == segment.text for hit in hits[:20])]
    output = []
    exporter = EvidenceService()
    for idx, segment in enumerate(risky[:5], 1):
        path = exporter.export_audio_segment(audio_path, content_id, segment.start, segment.end, idx)
        output.append(EvidenceSegment(start=segment.start, end=segment.end, audio_path=path, text=segment.text, description=describe(segment.text, hits)))
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
