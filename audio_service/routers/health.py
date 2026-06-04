import os

from fastapi import APIRouter

from audio_service.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "profile": os.environ.get("TOBACCO_PROFILE", "dev"),
        "asr_engine": settings.asr_engine,
        "allow_asr_fallback": settings.allow_asr_fallback,
        "mock_transcript_enabled": settings.use_mock_transcript,
    }
