import os

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "env": settings.app_env,
        "profile": os.environ.get("TOBACCO_PROFILE", settings.app_env),
        "model_id": settings.yolo_model_id,
        "mock_model": settings.use_mock_model,
    }
