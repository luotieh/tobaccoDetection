from text_service.schemas import KeywordHit, TextEntity
from text_service.config import settings
from text_service.services.llm_risk_classifier import LlmRiskClassifier


def test_llm_parser_accepts_json_with_extra_text():
    output = '前缀 {"labels":[{"label":"sale_intent","score":0.92},{"label":"contact_lead","score":0.81}],"reason":"疑似交易"} 后缀'

    results = LlmRiskClassifier.parse_output(output)

    scores = {item.label: item.score for item in results}
    assert scores["sale_intent"] == 0.92
    assert scores["contact_lead"] == 0.81


def test_llm_parser_filters_invalid_labels_and_clips_scores():
    output = '{"labels":[{"label":"sale_intent","score":1.7},{"label":"bad_label","score":0.9},{"label":"trade_lead","score":-0.2},{"label":"contact_lead","score":"x"}]}'

    results = LlmRiskClassifier.parse_output(output)

    scores = {item.label: item.score for item in results}
    assert scores == {"sale_intent": 1.0, "trade_lead": 0.0}


def test_llm_parser_returns_normal_on_invalid_payload():
    results = LlmRiskClassifier.parse_output("不是 JSON")

    assert [(item.label, item.score) for item in results] == [("normal_discussion", 0.5)]


def test_llm_classifier_falls_back_to_mock_when_model_unavailable():
    classifier = LlmRiskClassifier()
    hits = [
        KeywordHit(word="刚到一批", normalized_word="刚到一批", category="trade", dictionary="risk_keywords"),
        KeywordHit(word="私聊", normalized_word="私聊", category="contact", dictionary="risk_keywords"),
    ]
    contacts = [TextEntity(type="account_hint", text="主页有方式", masked="主页有方式")]

    results = classifier.classify_text("刚到一批，懂的私聊，主页有方式", hits, contacts)

    labels = {item.label for item in results}
    assert {"sale_intent", "trade_lead", "contact_lead"} <= labels


def test_llm_chat_completions_url_accepts_base_or_full_path():
    assert LlmRiskClassifier.chat_completions_url("https://api.example.com/v1") == "https://api.example.com/v1/chat/completions"
    assert LlmRiskClassifier.chat_completions_url("https://api.example.com/v1/chat/completions") == "https://api.example.com/v1/chat/completions"


def test_llm_prompt_includes_rule_dictionary_context():
    prompt = LlmRiskClassifier().build_prompt("刚到一批，私聊", [], [])

    assert "规则词库摘要" in prompt
    assert "risk_keywords" in prompt
    assert "刚到一批" in prompt


def test_llm_classifier_reads_openai_compatible_api(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_api_base_url", "https://api.example.com/v1")
    monkeypatch.setattr(settings, "llm_api_model", "demo-chat")
    monkeypatch.setattr(settings, "llm_api_key_env", "TEXT_LLM_TEST_KEY")
    monkeypatch.setattr(settings, "llm_timeout_seconds", 3)
    monkeypatch.setenv("TEXT_LLM_TEST_KEY", "demo-key")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"choices":[{"message":{"content":"{\\"labels\\":[{\\"label\\":\\"sale_intent\\",\\"score\\":0.91}]}"}}]}'

    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.headers.get("Authorization")
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    classifier = LlmRiskClassifier()

    results = classifier.classify_text("刚到一批，私聊", [], [])

    assert seen == {
        "url": "https://api.example.com/v1/chat/completions",
        "auth": "Bearer demo-key",
        "timeout": 3,
    }
    assert [(item.label, item.score) for item in results] == [("sale_intent", 0.91)]
