from fastapi import APIRouter

from app.services.pipeline import pipeline

router = APIRouter()


@router.get("/models/info")
def model_info(model_id: str | None = None):
    return pipeline.model_info(model_id)
