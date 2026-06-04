from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.services.pipeline import pipeline
from app.utils.file_utils import ensure_dir, new_storage_name, safe_ext
from app.utils.image_io import bytes_to_bgr_image

router = APIRouter()


def error(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.post("/infer/image")
async def infer_image(
    file: UploadFile = File(...),
    content_id: str | None = Form(None),
    save_evidence: bool = Form(True),
    conf: float | None = Form(None),
    model_id: str | None = Form(None),
):
    try:
        ext = safe_ext(file.filename or "", {"jpg", "jpeg", "png", "webp"})
    except ValueError:
        raise error("INVALID_FILE_TYPE", "仅支持 jpg、jpeg、png、webp")
    content_id = content_id or f"img_{Path(new_storage_name('upload', ext)).stem}"
    upload_dir = ensure_dir(settings.resolve(settings.upload_dir))
    raw = await file.read()
    upload_path = upload_dir / new_storage_name(content_id, ext)
    upload_path.write_bytes(raw)
    try:
        image = bytes_to_bgr_image(raw)
        return pipeline.infer_image(image, content_id=content_id, conf=conf, save_evidence=save_evidence, model_id=model_id)
    except Exception as exc:
        raise error("INFERENCE_FAILED", str(exc), 500)


@router.post("/infer/video")
async def infer_video(
    file: UploadFile = File(...),
    content_id: str | None = Form(None),
    sample_fps: float | None = Form(None),
    max_seconds: int | None = Form(None),
    conf: float | None = Form(None),
    model_id: str | None = Form(None),
):
    try:
        ext = safe_ext(file.filename or "", {"mp4", "mov", "avi", "mkv"})
    except ValueError:
        raise error("INVALID_FILE_TYPE", "仅支持 mp4、mov、avi、mkv")
    content_id = content_id or f"video_{Path(new_storage_name('upload', ext)).stem}"
    upload_dir = ensure_dir(settings.resolve(settings.upload_dir))
    raw = await file.read()
    upload_path = upload_dir / new_storage_name(content_id, ext)
    upload_path.write_bytes(raw)
    try:
        return pipeline.infer_video(upload_path, content_id=content_id, sample_fps=sample_fps, max_seconds=max_seconds, conf=conf, model_id=model_id)
    except ValueError as exc:
        if str(exc) == "VIDEO_OPEN_FAILED":
            raise error("VIDEO_OPEN_FAILED", "视频无法打开或格式不受支持")
        raise error("INFERENCE_FAILED", str(exc), 500)
    except Exception as exc:
        raise error("INFERENCE_FAILED", str(exc), 500)
