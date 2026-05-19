from fastapi import FastAPI

from audio_service.config import settings
from audio_service.routers import health, inference, models

app = FastAPI(title=settings.app_name, version=settings.version)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(inference.router)
