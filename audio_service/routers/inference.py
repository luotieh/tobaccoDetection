from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from audio_service.services.pipeline import pipeline
from audio_service.utils.file_utils import validate_ext

router = APIRouter()


def error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


@router.post("/infer/audio")
async def infer_audio(file: UploadFile = File(...), content_id: str | None = Form(None), save_evidence: bool = Form(True)):
    try:
        validate_ext(file.filename or "", {"wav", "mp3", "m4a", "aac", "flac"})
    except ValueError:
        raise error("INVALID_FILE_TYPE", "仅支持 wav、mp3、m4a、aac、flac")
    cid = content_id or f"audio_{Path(file.filename or 'upload').stem}"
    data = await file.read()
    path = pipeline.media.save_upload(data, file.filename or "audio.wav", cid)
    return pipeline.infer(path, cid, "audio", save_evidence)


@router.post("/infer/video-audio")
async def infer_video_audio(file: UploadFile = File(...), content_id: str | None = Form(None), save_evidence: bool = Form(True)):
    try:
        validate_ext(file.filename or "", {"mp4", "mov", "avi", "mkv"})
    except ValueError:
        raise error("INVALID_FILE_TYPE", "仅支持 mp4、mov、avi、mkv")
    cid = content_id or f"video_audio_{Path(file.filename or 'upload').stem}"
    data = await file.read()
    path = pipeline.media.save_upload(data, file.filename or "video.mp4", cid)
    return pipeline.infer(path, cid, "video", save_evidence)
