# Codex 任务计划书：为 tobaccoDetection 文本识别模块引入轻量化 LLM 风险评分

## 1. 背景

当前项目已经包含独立文本识别服务 `text_service`，核心接口包括：

- `POST /infer/text`
- `POST /infer/content`
- `POST /infer/batch`

现有文本识别链路为：

```text
文本归一化
  -> 关键词词库匹配
  -> 联系方式/品牌实体抽取
  -> SemanticClassifier 语义分类
  -> score_text 综合评分
  -> explanation 解释生成
```

目前 `SemanticClassifier` 支持 Mock 分类器和 Transformers 文本分类器。现有评分函数 `score_text()` 已经把 `semantic_score` 纳入最终风险评分，语义分权重为 0.35，因此轻量化 LLM 应作为新的语义分类器接入，而不是替换整个评分系统。

相关文件：

```text
text_service/main.py
text_service/routers/inference.py
text_service/services/pipeline.py
text_service/services/semantic_classifier.py
text_service/services/scoring.py
common/scoring/text_scoring.py
text_service/config.py
text_service/schemas.py
.env.example
```

## 2. 总目标

在不破坏现有 API 的前提下，为文本识别模块新增一个轻量化 LLM 风险分类器，用于识别隐晦售烟、交易引流、联系方式暗示、价格数量、品牌提及、黑话表达和白名单语境。

新增能力应满足：

1. 保留现有规则词库、实体抽取、联系方式脱敏和综合评分逻辑。
2. 新增 `TEXT_SEMANTIC_ENGINE=llm` 模式。
3. LLM 输出必须映射为现有 `SemanticResult(label, score)`。
4. `/infer/text`、`/infer/content`、`/infer/batch` 接口返回结构不破坏兼容性。
5. 模型加载失败时，在 Mock 模式下可自动回退到现有 Mock 分类器。
6. LLM 输出必须强制解析为 JSON，解析失败时安全降级。
7. 增加基础单元测试和接口测试。

## 3. 设计原则

### 3.1 不替换现有规则系统

LLM 只负责增强语义判断，尤其是：

- “懂的来”
- “主页有方式”
- “私聊安排”
- “到货”
- “同城可安排”
- “需要的看主页”
- “价格私”
- “老客户懂”

规则系统继续负责：

- 关键词召回
- 品牌词识别
- 黑话词识别
- 联系方式识别
- 白名单词识别
- 最终可解释证据

### 3.2 LLM 不直接输出最终风险分

LLM 输出语义标签和分数，最终 `text_score` 仍由 `score_text()` 融合计算。

允许标签沿用当前系统标签：

```text
normal_discussion
sale_intent
trade_lead
brand_mention
slang_mention
contact_lead
price_quantity
whitelist_context
```

## 4. 具体开发任务

## 任务一：扩展配置

修改文件：

```text
text_service/config.py
.env.example
```

### 4.1 在 `text_service/config.py` 中新增配置

新增字段：

```python
semantic_engine = os.environ.get("TEXT_SEMANTIC_ENGINE", "mock")
llm_model_dir = Path(os.environ.get("TEXT_LLM_MODEL_DIR", "text_models/qwen2.5-0.5b-instruct"))
llm_max_new_tokens = env_int("TEXT_LLM_MAX_NEW_TOKENS", 256)
llm_temperature = env_float("TEXT_LLM_TEMPERATURE", 0.0)
llm_timeout_seconds = env_int("TEXT_LLM_TIMEOUT_SECONDS", 10)
```

注意：

- `TEXT_SEMANTIC_ENGINE` 支持 `mock`、`transformers`、`llm`。
- 默认值应保持安全，不能导致没有模型时服务启动失败。
- 保留现有 `TEXT_USE_MOCK_MODEL` 回退逻辑。

### 4.2 更新 `.env.example`

新增：

```bash
# Text semantic engine: mock, transformers, or llm
TEXT_SEMANTIC_ENGINE=mock

# Local lightweight LLM
TEXT_LLM_MODEL_DIR=text_models/qwen2.5-0.5b-instruct
TEXT_LLM_MAX_NEW_TOKENS=256
TEXT_LLM_TEMPERATURE=0.0
TEXT_LLM_TIMEOUT_SECONDS=10
```

## 任务二：新增 LLM 风险分类器

新增文件：

```text
text_service/services/llm_risk_classifier.py
```

### 5.1 实现类 `LlmRiskClassifier`

要求：

```python
class LlmRiskClassifier:
    mock = False

    def __init__(self):
        ...

    def classify_text(self, text: str, hits: list[KeywordHit], contacts: list[TextEntity]) -> list[SemanticResult]:
        ...
```

### 5.2 模型加载要求

使用本地 Transformers 模型：

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
```

加载路径来自：

```python
settings.resolve(settings.llm_model_dir)
```

模型加载失败时：

- 如果 `settings.use_mock_model == True`，回退到 `MockSemanticClassifier`。
- 如果 `settings.use_mock_model == False`，抛出明确异常。

### 5.3 Prompt 要求

Prompt 必须要求模型只输出 JSON。

Prompt 内容应包含：

- 原始/归一化文本
- 规则命中的关键词
- 命中的词库类型
- 联系方式实体类型
- 允许输出的标签
- 白名单语境判断规则
- 不要因为单独出现烟草词就直接高风险
- 控烟宣传、新闻报道、公益科普应降低风险

输出格式：

```json
{
  "labels": [
    {
      "label": "sale_intent",
      "score": 0.82
    }
  ],
  "reason": "一句话原因",
  "confidence": 0.76
}
```

### 5.4 JSON 解析要求

LLM 输出可能包含多余文本，需要实现安全解析：

1. 用正则提取第一个 JSON 对象。
2. `json.loads()` 失败时回退。
3. label 不在白名单中时忽略。
4. score 必须裁剪到 `[0.0, 1.0]`。
5. 如果没有有效标签，返回：

```python
SemanticResult(label="normal_discussion", score=0.5)
```

### 5.5 安全降级要求

以下情况必须返回低风险或 Mock 结果，不得抛出未处理异常：

- 模型未加载
- 输出为空
- JSON 解析失败
- 标签不合法
- score 类型错误
- 推理异常

## 任务三：改造 `SemanticClassifier`

修改文件：

```text
text_service/services/semantic_classifier.py
```

### 6.1 支持三种引擎

将当前 `SemanticClassifier` 改造为统一入口：

```text
TEXT_SEMANTIC_ENGINE=mock
TEXT_SEMANTIC_ENGINE=transformers
TEXT_SEMANTIC_ENGINE=llm
```

逻辑：

```python
engine = settings.semantic_engine.lower()

if engine == "llm":
    self.impl = LlmRiskClassifier()
elif engine == "transformers":
    self.impl = TransformersSemanticClassifier()
else:
    self.impl = MockSemanticClassifier()
```

同时兼容现有逻辑：

- 如果 `TEXT_USE_MOCK_MODEL=true`，默认仍可使用 Mock。
- 如果没有指定 `TEXT_SEMANTIC_ENGINE`，不得破坏现有行为。

### 6.2 统一 classify 接口

新增兼容完整文本的接口：

```python
def classify(self, text, hits=None, contacts=None):
    ...
```

兼容旧调用：

```python
classify(hits, contacts)
```

支持新调用：

```python
classify(text, hits, contacts)
```

如果底层实现有 `classify_text()`，优先调用：

```python
self.impl.classify_text(text, hits, contacts)
```

否则调用旧方法：

```python
self.impl.classify(hits, contacts)
```

## 任务四：修改文本流水线

修改文件：

```text
text_service/services/pipeline.py
```

### 7.1 将完整文本传给语义分类器

当前逻辑类似：

```python
semantics = self.classifier.classify(hits, contacts)
```

修改为：

```python
semantics = self.classifier.classify(normalized, hits, contacts)
```

要求：

- 不影响 Mock 分类器。
- 不影响 Transformers 分类器。
- LLM 能拿到完整上下文。

### 7.2 保持接口返回兼容

不得删除或重命名以下字段：

```text
content_id
source
text_score
risk_level
risk_types
hit_keywords
brand_entities
contact_entities
evidence_text
explanation
model_version
```

可以暂不新增 `llm_reason` 字段，避免破坏接口。

## 任务五：优化解释生成，可选但建议实现

修改文件：

```text
text_service/services/explanation.py
```

### 8.1 加强 LLM 语义结果解释

如果风险类型中包含：

```text
sale_intent + trade_lead + contact_lead
```

解释应倾向：

```text
文本存在交易意图、引流暗示和联系方式线索，疑似违法烟草交易。
```

如果包含：

```text
whitelist_context
```

且没有交易词、联系方式、价格数量，则解释应倾向：

```text
文本更接近控烟宣传、新闻报道或公益科普语境，风险降低。
```

## 任务六：可选增强 `score_text`

修改文件：

```text
common/scoring/text_scoring.py
```

### 9.1 白名单语义增强

如果 LLM 输出：

```text
whitelist_context >= 0.8
```

并且没有联系方式、交易词、价格词，则增加白名单惩罚。

建议逻辑：

```python
llm_whitelist = any(
    item.label == "whitelist_context" and item.score >= 0.8
    for item in semantics
)

if llm_whitelist and not contacts and keyword_score < 0.6:
    whitelist_penalty = max(whitelist_penalty, 0.4)
```

### 9.2 强交易语义增强

如果 LLM 同时输出：

```text
sale_intent >= 0.75
trade_lead >= 0.75
contact_lead >= 0.75
```

可将 `semantic_score` 提升到至少 `0.9`。

要求：

- 不得让单一 LLM 输出直接覆盖所有规则。
- 最终分数仍需经过现有加权公式。
- 分数仍需裁剪到 `[0.0, 1.0]`。

## 任务七：更新模型信息接口

检查文件：

```text
text_service/routers/models.py
text_service/services/pipeline.py
```

如果 `/models/info` 当前返回 `semantic_model` 信息，则加入：

```json
{
  "semantic_model": {
    "enabled": true,
    "engine": "llm",
    "mock": false,
    "model_dir": "text_models/qwen2.5-0.5b-instruct"
  }
}
```

要求：

- Mock 模式下显示 `mock: true`。
- LLM 模式下显示 `engine: llm`。
- 模型加载失败但回退 Mock 时，应体现当前为 fallback/mock。

## 任务八：增加依赖说明

检查项目依赖文件，例如：

```text
requirements.txt
text_service/requirements.txt
pyproject.toml
```

如项目没有独立 `text_service/requirements.txt`，则在根依赖文件或 README 中补充可选依赖：

```text
transformers
accelerate
sentencepiece
torch
```

要求：

- 标注为 LLM 可选依赖。
- 不要强制所有模式必须安装大型推理依赖。
- Mock 模式应在未安装这些依赖时仍可运行。

## 任务九：增加测试

新增或修改测试文件：

```text
tests/test_text_llm_classifier.py
tests/test_text_infer_llm_mode.py
```

如果项目已有测试目录，请按现有结构放置。

### 11.1 单元测试：JSON 解析

测试内容：

1. 正常 JSON 输出。
2. JSON 前后带多余文本。
3. 非法 JSON。
4. 非法 label。
5. score 超过 1。
6. score 小于 0。
7. score 非数字。

### 11.2 单元测试：语义标签映射

输入：

```text
刚到一批，懂的私聊，主页有方式
```

Mock LLM 输出：

```json
{
  "labels": [
    {"label": "sale_intent", "score": 0.86},
    {"label": "trade_lead", "score": 0.82},
    {"label": "contact_lead", "score": 0.78}
  ],
  "reason": "存在交易和引流暗示",
  "confidence": 0.8
}
```

断言：

```text
risk_types 包含 sale_intent / trade_lead / contact_lead
text_score > 0
risk_level 不应为 none
```

### 11.3 白名单测试

输入：

```text
控烟宣传活动，未成年人禁止吸烟
```

期望：

```text
risk_level 为 none 或 low
risk_types 包含 whitelist_context 或 normal_discussion
```

### 11.4 接口测试

测试：

```text
POST /infer/text
POST /infer/content
POST /infer/batch
GET /models/info
```

确保接口字段保持兼容。

## 任务十：更新 README

修改 README 的“文本识别服务”部分，增加轻量 LLM 模式说明。

新增示例：

```bash
TEXT_SEMANTIC_ENGINE=llm \
TEXT_USE_MOCK_MODEL=false \
TEXT_LLM_MODEL_DIR=text_models/qwen2.5-0.5b-instruct \
TEXT_PORT=8010 \
scripts/run_text_dev.sh
```

增加说明：

```text
如果未准备本地 LLM 模型，请保持 TEXT_SEMANTIC_ENGINE=mock。
LLM 模式用于增强隐晦交易话术识别，不替代规则词库和最终评分。
```

## 5. 验收标准

### 5.1 功能验收

执行以下命令：

```bash
TEXT_SEMANTIC_ENGINE=mock TEXT_PORT=8010 scripts/run_text_dev.sh
```

服务应正常启动。

执行：

```bash
curl -X POST http://127.0.0.1:8010/infer/text \
  -H "Content-Type: application/json" \
  -d '{"content_id":"t1","source":"comment","text":"刚到一批，懂的私聊，主页有方式"}'
```

应返回：

```text
text_score
risk_level
risk_types
hit_keywords
evidence_text
explanation
model_version
```

执行：

```bash
curl -X POST http://127.0.0.1:8010/infer/text \
  -H "Content-Type: application/json" \
  -d '{"content_id":"t2","source":"title","text":"控烟宣传活动，未成年人禁止吸烟"}'
```

应返回低风险或白名单语境。

### 5.2 LLM 模式验收

准备本地模型后执行：

```bash
TEXT_SEMANTIC_ENGINE=llm \
TEXT_USE_MOCK_MODEL=false \
TEXT_LLM_MODEL_DIR=text_models/qwen2.5-0.5b-instruct \
TEXT_PORT=8010 \
scripts/run_text_dev.sh
```

要求：

- 服务正常启动。
- `/models/info` 显示 `engine=llm`。
- `/infer/text` 能返回风险评分。
- LLM 输出异常时服务不崩溃。
- JSON 解析失败时安全降级。

### 5.3 回归验收

以下模式都必须可用：

```bash
TEXT_SEMANTIC_ENGINE=mock
TEXT_SEMANTIC_ENGINE=transformers
TEXT_SEMANTIC_ENGINE=llm
```

现有管理后台通过：

```text
TEXT_SERVICE_URL=http://127.0.0.1:8010
```

调用文本服务时，不需要修改前端接口。

## 6. 非目标

本次任务不做以下事情：

1. 不训练新模型。
2. 不接入外部云端 LLM API。
3. 不改变数据库结构。
4. 不改变管理后台接口协议。
5. 不删除现有 Mock 模型。
6. 不删除现有 Transformers 分类器。
7. 不替换 `score_text()` 的整体评分框架。

## 7. 推荐提交拆分

建议分为以下 commit：

### Commit 1

```text
feat(text): add semantic engine configuration for llm classifier
```

内容：

- `text_service/config.py`
- `.env.example`

### Commit 2

```text
feat(text): add lightweight llm risk classifier
```

内容：

- 新增 `llm_risk_classifier.py`
- JSON 解析
- 标签映射
- 安全回退

### Commit 3

```text
refactor(text): route semantic classification through selectable engines
```

内容：

- 改造 `semantic_classifier.py`
- 修改 `pipeline.py`

### Commit 4

```text
test(text): cover llm classifier parsing and inference fallback
```

内容：

- 新增测试

### Commit 5

```text
docs(text): document lightweight llm semantic risk mode
```

内容：

- README
- 依赖说明

## 8. 最终交付物

完成后应包含：

```text
text_service/services/llm_risk_classifier.py
text_service/services/semantic_classifier.py
text_service/services/pipeline.py
text_service/config.py
.env.example
README.md
tests 或现有测试目录中的相关测试文件
```

最终结果应做到：

```text
规则可解释
LLM 可增强
Mock 可回退
接口不破坏
评分可复用
部署可配置
```
