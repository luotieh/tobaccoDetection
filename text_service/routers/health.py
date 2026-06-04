import os

from fastapi import APIRouter

from text_service.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "env": settings.app_env,
        "profile": os.environ.get("TOBACCO_PROFILE", settings.app_env),
        "mock_model": settings.use_mock_model,
        "rules_enabled": settings.enable_rules,
    }
