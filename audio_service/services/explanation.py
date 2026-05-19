from audio_service.schemas import AudioKeywordHit, BrandEntity


def explain(hits: list[AudioKeywordHit], brands: list[BrandEntity]) -> str:
    categories = {hit.category for hit in hits}
    if "trade" in categories and "contact" in categories:
        return "语音转写文本中同时出现交易引导词和联系方式暗示，存在交易引流风险。"
    if brands and ("trade" in categories or "price" in categories):
        return "语音转写文本中出现烟草品牌及交易相关表达。"
    if categories & {"anti_smoking", "news", "education"}:
        return "语音转写文本命中白名单语境，风险降低。"
    if hits:
        return "语音转写文本命中烟草相关关键词，建议复核。"
    return "未获得可分析的语音转写文本；请配置真实 ASR 引擎后再判断音频内容风险。"
