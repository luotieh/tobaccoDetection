from text_service.schemas import BrandEntity, KeywordHit, TextEntity


def explain(hits: list[KeywordHit], brands: list[BrandEntity], contacts: list[TextEntity], risk_types: list[str]) -> str:
    risk_type_set = set(risk_types)
    transaction_types = {"sale_intent", "trade_lead", "contact_lead", "price_quantity", "slang_mention"}
    if {"sale_intent", "trade_lead", "contact_lead"} <= risk_type_set:
        return "文本存在交易意图、引流暗示和联系方式线索，疑似违法烟草交易。"
    if "whitelist_context" in risk_type_set and not (risk_type_set & transaction_types):
        return "文本命中控烟、新闻或公益语境，风险降低。"
    categories = {hit.category for hit in hits}
    if contacts and ("trade" in categories or "contact" in categories):
        return "文本中同时出现交易表达和联系方式暗示，存在交易引流风险。"
    if brands and ("price" in categories or "quantity" in categories):
        return "文本中出现烟草品牌及价格/数量表达，存在售卖意图风险。"
    if hits:
        return "文本命中烟草相关关键词或隐晦表达，需要结合上下文复核。"
    return "未发现明显烟草交易风险表达。"
