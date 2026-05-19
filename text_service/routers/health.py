from fastapi import APIRouter

from text_service.config import settings

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name, "version": settings.version}
