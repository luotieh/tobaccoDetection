from fastapi import APIRouter

from audio_service.services.pipeline import pipeline

router = APIRouter()


@router.get("/models/info")
async def model_info():
    return pipeline.info()
