from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from audio_service.config import settings
from audio_service.services.pipeline import pipeline
from audio_service.utils.file_utils import validate_ext

router = APIRouter()


def error(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def read_limited(file: UploadFile) -> bytes:
    """分块读取并在超过 max_file_size_mb 上限时拒绝，避免把超大文件读满进内存。"""
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise error("FILE_TOO_LARGE", f"文件超过上限 {settings.max_file_size_mb} MB", 413)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/infer/audio")
async def infer_audio(file: UploadFile = File(...), content_id: str | None = Form(None), save_evidence: bool = Form(True)):
    try:
        validate_ext(file.filename or "", {"wav", "mp3", "m4a", "aac", "flac"})
    except ValueError:
        raise error("INVALID_FILE_TYPE", "仅支持 wav、mp3、m4a、aac、flac")
    cid = content_id or f"audio_{Path(file.filename or 'upload').stem}"
    data = await read_limited(file)
    path = pipeline.media.save_upload(data, file.filename or "audio.wav", cid)
    return pipeline.infer(path, cid, "audio", save_evidence)


@router.post("/infer/video-audio")
async def infer_video_audio(file: UploadFile = File(...), content_id: str | None = Form(None), save_evidence: bool = Form(True)):
    try:
        validate_ext(file.filename or "", {"mp4", "mov", "avi", "mkv"})
    except ValueError:
        raise error("INVALID_FILE_TYPE", "仅支持 mp4、mov、avi、mkv")
    cid = content_id or f"video_audio_{Path(file.filename or 'upload').stem}"
    data = await read_limited(file)
    path = pipeline.media.save_upload(data, file.filename or "video.mp4", cid)
    return pipeline.infer(path, cid, "video", save_evidence)
