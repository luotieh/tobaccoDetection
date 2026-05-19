from text_service.schemas import BrandEntity, KeywordHit, TextEntity


def explain(hits: list[KeywordHit], brands: list[BrandEntity], contacts: list[TextEntity], risk_types: list[str]) -> str:
    if "whitelist_context" in risk_types and len(risk_types) == 1:
        return "文本命中控烟、新闻或公益语境，风险降低。"
    categories = {hit.category for hit in hits}
    if contacts and ("trade" in categories or "contact" in categories):
        return "文本中同时出现交易表达和联系方式暗示，存在交易引流风险。"
    if brands and ("price" in categories or "quantity" in categories):
        return "文本中出现烟草品牌及价格/数量表达，存在售卖意图风险。"
    if hits:
        return "文本命中烟草相关关键词或隐晦表达，需要结合上下文复核。"
    return "未发现明显烟草交易风险表达。"
