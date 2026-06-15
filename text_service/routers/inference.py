import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter

from text_service.config import settings
from text_service.schemas import BatchInferRequest, BatchInferResult, ContentInferRequest, TextInferRequest
from text_service.services.pipeline import pipeline

router = APIRouter()


@router.post("/infer/text")
async def infer_text(req: TextInferRequest):
    return pipeline.infer_text(req.content_id, req.source, req.text, req.context)


@router.post("/infer/content")
async def infer_content(req: ContentInferRequest):
    return pipeline.infer_content(req)


@router.post("/infer/batch")
async def infer_batch(req: BatchInferRequest):
    items = req.items
    if not items:
        return BatchInferResult(items=[])
    # LLM 调用为 I/O 密集，用线程池并发，缩短大评论区的整体耗时；asyncio.gather 保序
    max_workers = max(1, min(settings.batch_max_workers, len(items)))
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = await asyncio.gather(*[
            loop.run_in_executor(executor, pipeline.infer_text, item.content_id, item.source, item.text, item.context)
            for item in items
        ])
    return BatchInferResult(items=list(results))
