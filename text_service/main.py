from fastapi import FastAPI

from text_service.config import settings
from text_service.routers import dictionaries, health, inference, models

app = FastAPI(title=settings.app_name, version=settings.version)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(dictionaries.router)
app.include_router(inference.router)
