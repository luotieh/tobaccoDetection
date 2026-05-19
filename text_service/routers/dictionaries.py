from fastapi import APIRouter

from text_service.services.pipeline import pipeline

router = APIRouter()


@router.get("/dictionaries")
async def dictionaries():
    return pipeline.matcher.raw()
