from fastapi import APIRouter

from text_service.schemas import BatchInferRequest, BatchInferResult, ContentInferRequest, TextInferRequest
from text_service.services.pipeline import pipeline

router = APIRouter()


@router.post("/infer/text")
async def infer_text(req: TextInferRequest):
    return pipeline.infer_text(req.content_id, req.source, req.text)


@router.post("/infer/content")
async def infer_content(req: ContentInferRequest):
    return pipeline.infer_content(req)


@router.post("/infer/batch")
async def infer_batch(req: BatchInferRequest):
    return BatchInferResult(items=[pipeline.infer_text(item.content_id, item.source, item.text) for item in req.items])
