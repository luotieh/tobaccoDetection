import json
import os
import time
import urllib.error
import urllib.request

from text_service.config import settings
from text_service.schemas import KeywordHit, SemanticResult, TextEntity


ALLOWED_LABELS = {
    "normal_discussion",
    "sale_intent",
    "trade_lead",
    "brand_mention",
    "slang_mention",
    "contact_lead",
    "price_quantity",
    "whitelist_context",
}


class LlmRiskClassifier:
    mock = False
    engine = "llm"

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.fallback = None
        self.error = None
        self.provider = (settings.llm_provider or "local").lower()
        self.model_dir = settings.resolve(settings.llm_model_dir)
        if self.provider != "local":
            if settings.use_mock_model:
                from text_service.services.semantic_classifier import MockSemanticClassifier

                self.fallback = MockSemanticClassifier()
            return
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir), trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(str(self.model_dir), trust_remote_code=True)
            if hasattr(self.model, "eval"):
                self.model.eval()
        except Exception as exc:
            self.error = str(exc)
            if not settings.use_mock_model:
                raise RuntimeError(f"LLM text risk model load failed: {exc}") from exc
            from text_service.services.semantic_classifier import MockSemanticClassifier

            self.mock = True
            self.fallback = MockSemanticClassifier()

    def classify_text(self, text: str, hits: list[KeywordHit], contacts: list[TextEntity]) -> list[SemanticResult]:
        if self.provider == "local" and (self.fallback is not None or self.model is None or self.tokenizer is None):
            return self.fallback.classify(hits, contacts) if self.fallback else self._normal_result()
        try:
            prompt = self.build_prompt(text, hits, contacts)
            output = self.generate(prompt)
            results = self.parse_output(output)
            return results or self._normal_result()
        except Exception:
            if self.fallback is not None:
                return self.fallback.classify(hits, contacts)
            return self._normal_result()

    def build_prompt(self, text: str, hits: list[KeywordHit], contacts: list[TextEntity]) -> str:
        hit_items = [
            {
                "word": hit.normalized_word or hit.word,
                "dictionary": hit.dictionary,
                "category": hit.category,
            }
            for hit in hits[:40]
        ]
        contact_items = [{"type": item.type, "masked": item.masked or item.text} for item in contacts[:20]]
        labels = ", ".join(sorted(ALLOWED_LABELS))
        return (
            "你是烟草违法交易文本风险语义分类器。只能输出一个 JSON 对象，不要输出解释性前后缀。\n"
            "任务：根据文本、规则命中和联系方式实体判断语义标签。不要直接给最终风险分。\n"
            "注意：单独出现烟草词不等于高风险；控烟宣传、新闻报道、公益科普应判为 whitelist_context 或 normal_discussion。\n"
            "重点识别隐晦售烟、交易引流、联系方式暗示、价格数量、品牌提及、黑话表达。\n"
            f"允许标签：{labels}\n"
            "输出格式：{\"labels\":[{\"label\":\"sale_intent\",\"score\":0.82}],\"reason\":\"一句话原因\",\"confidence\":0.76}\n"
            f"文本：{text[:settings.max_text_length]}\n"
            f"规则命中：{json.dumps(hit_items, ensure_ascii=False)}\n"
            f"联系方式实体：{json.dumps(contact_items, ensure_ascii=False)}\n"
        )

    def generate(self, prompt: str) -> str:
        if self.provider != "local":
            return self.generate_from_api(prompt)
        start = time.monotonic()
        inputs = self.tokenizer(prompt, return_tensors="pt")
        generate_kwargs = {
            "max_new_tokens": settings.llm_max_new_tokens,
            "do_sample": settings.llm_temperature > 0,
        }
        if settings.llm_temperature > 0:
            generate_kwargs["temperature"] = settings.llm_temperature
        output_ids = self.model.generate(**inputs, **generate_kwargs)
        if time.monotonic() - start > settings.llm_timeout_seconds:
            return ""
        prompt_len = inputs["input_ids"].shape[-1]
        generated = output_ids[0][prompt_len:]
        return self.tokenizer.decode(generated, skip_special_tokens=True)

    def generate_from_api(self, prompt: str) -> str:
        if not settings.llm_api_base_url:
            raise RuntimeError("TEXT_LLM_API_BASE_URL is required for third-party LLM API")
        if not settings.llm_api_model:
            raise RuntimeError("TEXT_LLM_API_MODEL is required for third-party LLM API")
        api_key = os.environ.get(settings.llm_api_key_env, "")
        if not api_key and not settings.use_mock_model:
            raise RuntimeError(f"{settings.llm_api_key_env} is required for third-party LLM API")
        body = {
            "model": settings.llm_api_model,
            "messages": [
                {"role": "system", "content": "你是烟草违法交易文本风险语义分类器。只能输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_new_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            self.chat_completions_url(settings.llm_api_base_url),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Third-party LLM API request failed: {exc}") from exc
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(choices[0].get("text") or "")

    @staticmethod
    def chat_completions_url(base_url: str) -> str:
        url = (base_url or "").strip().rstrip("/")
        if url.endswith("/chat/completions"):
            return url
        return f"{url}/chat/completions"

    @classmethod
    def parse_output(cls, output: str) -> list[SemanticResult]:
        payload = cls.extract_json_object(output or "")
        if not payload:
            return cls._normal_result()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return cls._normal_result()
        results = []
        labels = data.get("labels") if isinstance(data, dict) else None
        if not isinstance(labels, list):
            return cls._normal_result()
        for item in labels:
            if not isinstance(item, dict):
                continue
            label = item.get("label")
            if label not in ALLOWED_LABELS:
                continue
            try:
                score = float(item.get("score"))
            except (TypeError, ValueError):
                continue
            results.append(SemanticResult(label=label, score=round(max(0.0, min(score, 1.0)), 4)))
        return results or cls._normal_result()

    @staticmethod
    def extract_json_object(output: str) -> str:
        decoder = json.JSONDecoder()
        for idx, char in enumerate(output):
            if char != "{":
                continue
            try:
                _, end = decoder.raw_decode(output[idx:])
                return output[idx : idx + end]
            except json.JSONDecodeError:
                continue
        return ""

    @staticmethod
    def _normal_result() -> list[SemanticResult]:
        return [SemanticResult(label="normal_discussion", score=0.5)]
