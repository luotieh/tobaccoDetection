# AI烟草违法监测系统：文本 + 语音识别落地实现方案

> 用途：将本文档直接交给 Codex / AI 编程助手，按照阶段生成可运行项目。  
> 基础文档：`tobacco_text_codex_spec.md` 与 `tobacco_audio_codex_spec.md`。  
> 实现目标：先落地可运行的 Mock + 规则版本，再逐步接入真实文本分类模型与 ASR 模型。  
> 适用场景：违法烟草交易监测中的标题、正文、评论、OCR 文本、ASR 转写文本、短视频口播、直播录屏音轨分析。

---

## 1. 总体落地原则

### 1.1 先跑通，再增强

第一版不要直接追求完整大模型能力，而是按以下顺序实现：

```text
规则词库 + Mock 模型
  ↓
文本风险服务 MVP
  ↓
语音 ASR Mock 服务
  ↓
音频/视频上传、FFmpeg 抽音频
  ↓
ASR 转写结果接入文本风险服务
  ↓
接入真实文本分类模型
  ↓
接入真实 ASR 模型
  ↓
批量任务、异步队列、模型管理、生产部署
```

### 1.2 两个服务，一个共享核心

推荐采用 monorepo 方式实现，包含两个服务和一个共享包：

```text
tobacco-ai-services/
├── README.md
├── docker-compose.yml
├── .env.example
├── common/
│   ├── __init__.py
│   ├── schemas/
│   ├── dictionaries/
│   ├── scoring/
│   ├── masking/
│   └── utils/
├── services/
│   ├── text-risk-service/
│   └── audio-risk-service/
├── storage/
│   ├── uploads/
│   ├── audio/
│   ├── evidence/
│   └── results/
├── models/
│   ├── text/
│   └── asr/
└── tests/
    ├── common/
    ├── text/
    └── audio/
```

其中：

- `text-risk-service` 负责文本风险识别。
- `audio-risk-service` 负责音频抽取、ASR 转写和语音风险识别。
- `common` 负责共享词库、实体抽取、脱敏、评分工具和通用响应结构。

### 1.3 Mock 优先

两个服务都必须支持 Mock 模式：

- 没有模型文件时服务也能启动。
- 没有 GPU 时服务也能启动。
- 没有 ASR 模型时音频服务也能跑通。
- 所有接口均返回结构化 JSON。
- Mock 模式不默认制造高风险结果，除非请求中明确传入测试文本。

---

## 2. 第一阶段：公共基础模块

### 2.1 目标

先实现 `common` 包，供文本服务和语音服务复用。

### 2.2 目录结构

```text
common/
├── __init__.py
├── config.py
├── schemas/
│   ├── __init__.py
│   ├── base.py
│   ├── text.py
│   └── audio.py
├── dictionaries/
│   ├── __init__.py
│   ├── loader.py
│   ├── brand_keywords.json
│   ├── risk_keywords.json
│   ├── slang_keywords.json
│   └── whitelist_keywords.json
├── scoring/
│   ├── __init__.py
│   ├── text_scoring.py
│   └── audio_scoring.py
├── masking/
│   ├── __init__.py
│   └── contact_masker.py
└── utils/
    ├── __init__.py
    ├── text_normalizer.py
    ├── time_utils.py
    ├── file_utils.py
    └── logging.py
```

### 2.3 必须实现的公共能力

#### 2.3.1 文本归一化

实现 `TextNormalizer`：

```python
class TextNormalizer:
    def normalize(self, text: str) -> str:
        ...
```

要求：

1. `None` 或空字符串返回空字符串。
2. 繁体转简体。
3. 全角转半角。
4. 英文转小写。
5. 去除不可见字符。
6. 压缩连续空白。
7. 保留原始文本和归一化文本，便于证据展示。

#### 2.3.2 词库加载

实现 `DictionaryLoader`：

```python
class DictionaryLoader:
    def load_all(self) -> dict:
        ...

    def reload(self) -> dict:
        ...
```

要求：

1. 加载品牌词、风险词、黑话词、白名单词。
2. 词库 JSON 不存在时抛出明确错误。
3. 支持热重载。
4. 支持返回词库版本号，可简单使用文件更新时间。

#### 2.3.3 关键词匹配

实现 `KeywordMatcher`：

```python
class KeywordMatcher:
    def match(self, text: str) -> list[KeywordHit]:
        ...
```

返回结构：

```python
class KeywordHit(BaseModel):
    word: str
    normalized_word: str | None = None
    category: str
    dictionary: str
    start: int | None = None
    end: int | None = None
```

要求：

1. 支持品牌词、交易词、黑话词、联系方式词、白名单词。
2. 支持大小写不敏感。
3. 支持去重。
4. 命中结果按位置排序。
5. 允许一个词命中多个类别，但要保留 dictionary 来源。

#### 2.3.4 联系方式脱敏

实现 `ContactMasker`：

```python
class ContactMasker:
    def mask_phone(self, text: str) -> str:
        ...

    def mask_contact_entities(self, entities: list[ContactEntity]) -> list[ContactEntity]:
        ...
```

脱敏规则：

```text
手机号：13812345678 -> 138****5678
QQ号：123456789 -> 123****789
微信号：保留前2位和后2位，中间用 ****
```

#### 2.3.5 时间工具

实现 `time_utils.py`：

```python
def seconds_to_timestamp(seconds: float) -> str:
    ...

def validate_time_range(start: float, end: float) -> bool:
    ...
```

时间格式：

```text
HH:MM:SS.mmm
```

---

## 3. 第二阶段：文本风险服务 MVP

### 3.1 目标

完成可启动、可测试、可调用的文本服务。

### 3.2 服务目录

```text
services/text-risk-service/
├── README.md
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── health.py
│   │   ├── inference.py
│   │   ├── dictionaries.py
│   │   └── models.py
│   └── services/
│       ├── text_pipeline.py
│       ├── semantic_classifier.py
│       ├── entity_extractor.py
│       └── explanation.py
└── tests/
    ├── test_health.py
    ├── test_infer_text.py
    └── test_infer_content.py
```

### 3.3 API 列表

#### 3.3.1 健康检查

```http
GET /health
```

返回：

```json
{
  "status": "ok",
  "service": "text-risk-service",
  "version": "0.1.0"
}
```

#### 3.3.2 单条文本识别

```http
POST /infer/text
```

请求：

```json
{
  "content_id": "txt_demo_001",
  "source": "comment",
  "text": "刚到一批，懂的私聊，主页有方式"
}
```

返回字段必须包含：

```json
{
  "content_id": "txt_demo_001",
  "source": "comment",
  "text_score": 0.88,
  "risk_level": "high",
  "risk_types": ["sale_intent", "trade_lead", "contact_lead"],
  "hit_keywords": [],
  "brand_entities": [],
  "contact_entities": [],
  "evidence_text": [],
  "explanation": "文本中出现交易引导词和联系方式暗示，存在交易引流风险。",
  "model_version": "text-risk-v0.1.0"
}
```

#### 3.3.3 多字段内容识别

```http
POST /infer/content
```

请求：

```json
{
  "content_id": "video_demo_001",
  "platform": "douyin",
  "title": "懂的来",
  "description": "主页有方式",
  "account_name": "好物分享",
  "account_bio": "同城可安排",
  "comments": ["什么价", "还有货吗", "私聊"],
  "ocr_texts": ["现货 包邮"],
  "asr_texts": ["需要的看主页"]
}
```

#### 3.3.4 批量文本识别

```http
POST /infer/batch
```

请求：

```json
{
  "items": [
    {
      "content_id": "c1",
      "source": "comment",
      "text": "还有货吗"
    },
    {
      "content_id": "c2",
      "source": "title",
      "text": "控烟宣传活动"
    }
  ]
}
```

### 3.4 文本处理流水线

实现 `TextRiskPipeline`：

```python
class TextRiskPipeline:
    def analyze_text(self, request: TextAnalyzeRequest) -> TextRiskResponse:
        ...

    def analyze_content(self, request: ContentAnalyzeRequest) -> ContentRiskResponse:
        ...
```

处理流程：

```text
输入文本
  ↓
文本归一化
  ↓
关键词匹配
  ↓
实体抽取
  ↓
Mock/真实语义分类
  ↓
风险评分
  ↓
解释生成
  ↓
结构化响应
```

### 3.5 实体抽取

实现 `EntityExtractor`。

识别：

1. 手机号
2. QQ 号
3. 微信号暗示
4. 价格
5. 数量
6. 品牌
7. 发货/快递词

示例结构：

```python
class Entity(BaseModel):
    type: str
    text: str
    masked: str | None = None
    start: int | None = None
    end: int | None = None
```

### 3.6 Mock 语义分类器

实现 `SemanticClassifier`：

```python
class SemanticClassifier:
    def predict(self, text: str, hits: list[KeywordHit]) -> list[SemanticResult]:
        ...
```

Mock 规则：

| 条件 | 输出 |
|---|---|
| 交易词 + 联系方式词 | `sale_intent=0.85`, `trade_lead=0.90`, `contact_lead=0.85` |
| 品牌词 + 价格词 | `sale_intent=0.80`, `brand_mention=0.90` |
| 黑话词 + 交易词 | `slang_mention=0.85`, `trade_lead=0.80` |
| 白名单词且无交易词 | `whitelist_context=0.90`, `normal_discussion=0.70` |
| 无命中 | `normal_discussion=0.80` |

### 3.7 文本评分

实现 `text_scoring.py`：

```text
text_score =
  0.30 × keyword_score
+ 0.35 × semantic_score
+ 0.15 × brand_entity_score
+ 0.10 × contact_score
+ 0.10 × context_score
- whitelist_penalty
```

风险等级：

```python
if score >= 0.85:
    risk_level = "high"
elif score >= 0.70:
    risk_level = "medium"
elif score >= 0.50:
    risk_level = "low"
else:
    risk_level = "none"
```

### 3.8 阶段验收

必须通过：

```bash
pytest services/text-risk-service/tests
```

必须能启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

必须能调用：

```bash
curl -X POST "http://localhost:8010/infer/text" \
  -H "Content-Type: application/json" \
  -d '{"content_id":"demo_text_001","source":"comment","text":"刚到一批，懂的私聊"}'
```

---

## 4. 第三阶段：语音风险服务 MVP

### 4.1 目标

完成音频/视频上传、FFmpeg 音频抽取、Mock ASR、关键词识别、语音风险评分和证据片段输出。

### 4.2 服务目录

```text
services/audio-risk-service/
├── README.md
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── health.py
│   │   ├── inference.py
│   │   └── models.py
│   └── services/
│       ├── media_service.py
│       ├── audio_preprocess.py
│       ├── asr_base.py
│       ├── asr_mock.py
│       ├── asr_whisper.py
│       ├── asr_funasr.py
│       ├── audio_pipeline.py
│       ├── evidence.py
│       └── explanation.py
└── tests/
    ├── test_health.py
    ├── test_time_utils.py
    ├── test_keyword_matcher.py
    └── test_audio_scoring.py
```

### 4.3 API 列表

#### 4.3.1 健康检查

```http
GET /health
```

#### 4.3.2 音频识别

```http
POST /infer/audio
```

请求：

- `multipart/form-data`
- 字段名：`file`
- 支持：`wav`、`mp3`、`m4a`、`aac`、`flac`

可选参数：

- `content_id`
- `save_evidence`

#### 4.3.3 视频音轨识别

```http
POST /infer/video-audio
```

请求：

- `multipart/form-data`
- 字段名：`file`
- 支持：`mp4`、`mov`、`avi`、`mkv`

返回示例：

```json
{
  "content_id": "audio_demo_001",
  "media_type": "audio",
  "duration_seconds": 25.6,
  "audio_score": 0.87,
  "risk_level": "high",
  "transcript": "刚到一批，需要的看主页，私聊安排。",
  "segments": [
    {
      "start": 3.2,
      "end": 8.5,
      "text": "刚到一批，需要的看主页",
      "confidence": 0.9
    }
  ],
  "hit_keywords": [],
  "brand_entities": [],
  "evidence_segments": [],
  "explanation": "语音转写文本中出现交易引导词和联系方式暗示。",
  "model_version": "audio-risk-v0.1.0"
}
```

### 4.4 媒体处理

实现 `MediaService`：

```python
class MediaService:
    def save_upload_file(self, file: UploadFile, content_id: str) -> str:
        ...

    def get_duration(self, media_path: str) -> float:
        ...

    def extract_audio_from_video(self, video_path: str, content_id: str) -> str:
        ...
```

要求：

1. 使用安全文件名，不直接使用原始文件名。
2. 限制文件类型。
3. 限制最大时长。
4. 视频抽取音频使用 FFmpeg。
5. 输出统一音频格式：`wav`, `16kHz`, `mono`。

FFmpeg 命令示例：

```bash
ffmpeg -y -i input.mp4 -vn -ac 1 -ar 16000 output.wav
```

### 4.5 ASR 统一接口

实现 `BaseASR`：

```python
class ASRSegment(BaseModel):
    start: float
    end: float
    text: str
    confidence: float | None = None

class ASRResult(BaseModel):
    transcript: str
    segments: list[ASRSegment]
    language: str | None = "zh"

class BaseASR:
    def transcribe(self, audio_path: str) -> ASRResult:
        raise NotImplementedError
```

### 4.6 Mock ASR

实现 `MockASR`：

规则：

1. 默认返回空转写。
2. 如果环境变量存在 `MOCK_TRANSCRIPT`，则返回该文本。
3. 时间戳为 `0` 到音频时长。
4. 不默认返回高风险文本。

`.env.example` 增加：

```env
ASR_ENGINE=mock
MOCK_TRANSCRIPT=
```

### 4.7 本地 ASR 适配器预留

需要提供两个适配器，但可以先实现为可选导入：

```text
asr_whisper.py
asr_funasr.py
```

要求：

1. 如果依赖未安装，不能导致服务启动失败。
2. 当 `ASR_ENGINE=whisper` 时尝试加载 faster-whisper。
3. 当 `ASR_ENGINE=funasr` 时尝试加载 FunASR。
4. 加载失败时返回明确错误，或在 `ALLOW_ASR_FALLBACK=true` 时回退 MockASR。

### 4.8 语音风险分析

语音风险分析不要重新写一套规则，应该复用文本模块公共能力：

```text
ASRResult.transcript / segments
  ↓
KeywordMatcher
  ↓
EntityExtractor
  ↓
audio_scoring
  ↓
EvidenceSegment
  ↓
AudioRiskResponse
```

### 4.9 语音评分

实现 `audio_scoring.py`：

```text
audio_score =
  0.30 × keyword_score
+ 0.30 × intent_score
+ 0.15 × brand_score
+ 0.15 × contact_score
+ 0.10 × repetition_score
- whitelist_penalty
```

风险等级同文本服务。

### 4.10 证据片段

实现 `EvidenceService`：

```python
class EvidenceService:
    def export_audio_segment(
        self,
        audio_path: str,
        content_id: str,
        start: float,
        end: float,
        index: int
    ) -> str:
        ...
```

FFmpeg 裁剪命令示例：

```bash
ffmpeg -y -i input.wav -ss 3.20 -to 10.20 -c copy segment_001.wav
```

如果 `-c copy` 失败，回退：

```bash
ffmpeg -y -i input.wav -ss 3.20 -to 10.20 -ac 1 -ar 16000 segment_001.wav
```

### 4.11 阶段验收

必须通过：

```bash
pytest services/audio-risk-service/tests
```

必须能启动：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

必须能调用：

```bash
curl -X POST "http://localhost:8020/infer/audio" \
  -F "file=@demo.wav" \
  -F "content_id=demo_audio_001"
```

---

## 5. 第四阶段：文本 + 语音联动

### 5.1 目标

语音服务的 ASR 结果要能直接进入文本风险服务，保证语音和文本风险判断口径一致。

### 5.2 推荐方式

第一版采用本地函数复用，不做服务间 HTTP 调用：

```text
audio-risk-service
  ├── ASR 转写
  ├── 调用 common KeywordMatcher
  ├── 调用 common scoring
  └── 输出 audio_score
```

第二版再支持 HTTP 调用文本服务：

```text
audio-risk-service
  ↓
POST /infer/content 到 text-risk-service
  ↓
复用文本风险结果
  ↓
叠加语音时间戳证据
```

### 5.3 统一输出字段

文本与语音输出都要包含：

```json
{
  "content_id": "string",
  "risk_level": "high|medium|low|none",
  "risk_types": ["sale_intent", "trade_lead"],
  "hit_keywords": [],
  "brand_entities": [],
  "contact_entities": [],
  "explanation": "string",
  "model_version": "string"
}
```

语音额外包含：

```json
{
  "audio_score": 0.88,
  "transcript": "string",
  "segments": [],
  "evidence_segments": []
}
```

文本额外包含：

```json
{
  "text_score": 0.88,
  "field_results": [],
  "evidence_text": []
}
```

---

## 6. 第五阶段：接入真实文本模型

### 6.1 推荐模型

第一版真实模型建议接入：

```text
hfl/chinese-roberta-wwm-ext
```

备选：

```text
hfl/chinese-macbert-base
```

### 6.2 实现方式

在 `semantic_classifier.py` 中实现：

```python
class TransformersSemanticClassifier:
    def __init__(self, model_dir: str, device: str = "cpu"):
        ...

    def predict(self, text: str, hits: list[KeywordHit]) -> list[SemanticResult]:
        ...
```

要求：

1. 模型目录不存在时不崩溃。
2. 依赖未安装时不崩溃。
3. 输出多标签分数。
4. 支持 `MAX_TEXT_LENGTH=512`。
5. 支持 CPU。
6. 支持后续 ONNX 导出。

### 6.3 模型输出映射

模型标签统一映射到：

```json
{
  "LABEL_0": "normal_discussion",
  "LABEL_1": "sale_intent",
  "LABEL_2": "trade_lead",
  "LABEL_3": "brand_mention",
  "LABEL_4": "slang_mention",
  "LABEL_5": "contact_lead",
  "LABEL_6": "price_quantity",
  "LABEL_7": "whitelist_context"
}
```

### 6.4 训练数据格式预留

预留 `data/train/text_train.jsonl`：

```json
{"text":"刚到一批，懂的私聊","labels":["sale_intent","trade_lead"]}
{"text":"控烟宣传活动开始了","labels":["whitelist_context"]}
```

### 6.5 验收标准

1. `TEXT_MODEL_DIR` 为空时走 Mock。
2. `TEXT_MODEL_DIR` 存在时走真实模型。
3. 同一请求返回结构不变。
4. 真实模型异常时返回明确错误或按配置回退 Mock。

---

## 7. 第六阶段：接入真实 ASR

### 7.1 推荐 ASR 顺序

中文短视频优先：

```text
FunASR Paraformer-zh
  ↓
SenseVoiceSmall
  ↓
faster-whisper small / medium / large-v3
```

境外平台或多语言内容：

```text
SenseVoiceSmall
  ↓
faster-whisper large-v3
  ↓
FunASR Paraformer-zh
```

### 7.2 FunASR 适配器

实现 `FunASRASR`：

```python
class FunASRASR(BaseASR):
    def transcribe(self, audio_path: str) -> ASRResult:
        ...
```

要求：

1. 可选导入 `funasr`。
2. 支持配置模型名或模型目录。
3. 支持 VAD。
4. 支持标点恢复。
5. 输出统一时间戳结构。
6. 输出失败时提供明确错误。

配置：

```env
ASR_ENGINE=funasr
FUNASR_MODEL=paraformer-zh
FUNASR_VAD_MODEL=fsmn-vad
FUNASR_PUNC_MODEL=ct-punc
```

### 7.3 faster-whisper 适配器

实现 `WhisperASR`：

```python
class WhisperASR(BaseASR):
    def transcribe(self, audio_path: str) -> ASRResult:
        ...
```

配置：

```env
ASR_ENGINE=whisper
WHISPER_MODEL_SIZE=small
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
ASR_LANGUAGE=zh
```

要求：

1. 支持 `small`、`medium`、`large-v3`。
2. 支持 CPU int8。
3. 支持 GPU float16。
4. 输出 segments。
5. 支持 language 参数。
6. 失败时可回退 Mock。

### 7.4 验收标准

1. `ASR_ENGINE=mock` 时稳定运行。
2. `ASR_ENGINE=whisper` 且依赖存在时可转写。
3. `ASR_ENGINE=funasr` 且依赖存在时可转写。
4. ASR 输出必须统一转换为 `ASRResult`。
5. 音频服务返回结构不因 ASR 引擎改变。

---

## 8. 第七阶段：Docker 与本地联调

### 8.1 docker-compose

生成 `docker-compose.yml`：

```yaml
services:
  text-risk-service:
    build:
      context: .
      dockerfile: services/text-risk-service/Dockerfile
    ports:
      - "8010:8010"
    env_file:
      - .env
    volumes:
      - ./storage:/app/storage
      - ./models:/app/models

  audio-risk-service:
    build:
      context: .
      dockerfile: services/audio-risk-service/Dockerfile
    ports:
      - "8020:8020"
    env_file:
      - .env
    volumes:
      - ./storage:/app/storage
      - ./models:/app/models
```

### 8.2 Dockerfile 要求

文本服务 Dockerfile：

1. Python 3.10 slim。
2. 安装 requirements。
3. 暴露 8010。
4. 默认启动 uvicorn。

语音服务 Dockerfile：

1. Python 3.10 slim。
2. 安装 FFmpeg。
3. 安装 requirements。
4. 暴露 8020。
5. 默认启动 uvicorn。

### 8.3 本地联调命令

```bash
docker compose up --build
```

验证：

```bash
curl http://localhost:8010/health
curl http://localhost:8020/health
```

---

## 9. 第八阶段：测试与质量门禁

### 9.1 单元测试

必须覆盖：

```text
common:
  - 文本归一化
  - 词库加载
  - 关键词匹配
  - 脱敏
  - 时间转换

text-risk-service:
  - health
  - infer/text
  - infer/content
  - infer/batch
  - 风险评分
  - 白名单降权

audio-risk-service:
  - health
  - 媒体类型校验
  - Mock ASR
  - 语音评分
  - 证据片段生成
```

### 9.2 集成测试

至少实现：

1. 文本高风险样例。
2. 文本白名单样例。
3. 空文本异常。
4. 音频 Mock 转写样例。
5. 视频文件类型校验。
6. ASR 空转写样例。

### 9.3 质量门禁

每次提交前必须通过：

```bash
pytest
python -m compileall common services
```

可选：

```bash
ruff check .
mypy common services
```

---

## 10. 第九阶段：多模态接口预留

虽然本文档只实现文本和语音，但需要预留多模态融合接口字段。

### 10.1 文本结果供融合使用

```json
{
  "content_id": "string",
  "text_score": 0.86,
  "risk_level": "high",
  "risk_types": [],
  "evidence_text": [],
  "model_version": "text-risk-v0.1.0"
}
```

### 10.2 语音结果供融合使用

```json
{
  "content_id": "string",
  "audio_score": 0.87,
  "risk_level": "high",
  "segments": [],
  "evidence_segments": [],
  "model_version": "audio-risk-v0.1.0"
}
```

### 10.3 后续融合公式

```text
final_score =
  0.40 × visual_score
+ 0.30 × text_score
+ 0.30 × audio_score
```

本阶段只输出 `text_score` 和 `audio_score`，不实现最终融合服务。

---

## 11. 配置汇总

根目录 `.env.example`：

```env
# Text service
TEXT_SERVICE_PORT=8010
TEXT_USE_MOCK_MODEL=true
TEXT_MODEL_DIR=models/text/text-risk-model
MAX_TEXT_LENGTH=512

# Audio service
AUDIO_SERVICE_PORT=8020
ASR_ENGINE=mock
ALLOW_ASR_FALLBACK=true
MOCK_TRANSCRIPT=
ASR_LANGUAGE=zh
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8

# FunASR
FUNASR_MODEL=paraformer-zh
FUNASR_VAD_MODEL=fsmn-vad
FUNASR_PUNC_MODEL=ct-punc

# Whisper
WHISPER_MODEL_SIZE=small

# Media
MAX_MEDIA_SECONDS=300
MAX_FILE_SIZE_MB=200
AUDIO_SAMPLE_RATE=16000

# Storage
UPLOAD_DIR=storage/uploads
AUDIO_DIR=storage/audio
EVIDENCE_DIR=storage/evidence
RESULT_DIR=storage/results

# Risk
RISK_HIGH=0.85
RISK_MEDIUM=0.70
RISK_LOW=0.50
```

---

## 12. Codex 执行提示词

可以把下面内容直接发给 Codex：

```text
请根据本 Markdown 文档生成 tobacco-ai-services 项目。要求：

1. 使用 Python 3.10+、FastAPI、Pydantic。
2. 采用 monorepo 结构，包含 common、text-risk-service、audio-risk-service。
3. 文本服务端口 8010，语音服务端口 8020。
4. 两个服务都必须支持 Mock 模式，缺少模型文件时仍可运行。
5. 实现规则词库、关键词匹配、实体抽取、联系方式脱敏、风险评分、解释生成。
6. 语音服务必须支持音频上传、视频上传、FFmpeg 抽音频、Mock ASR、证据片段导出。
7. 真实模型适配器先做可选导入和预留，不允许因缺少依赖导致服务无法启动。
8. 生成 README、requirements.txt、.env.example、Dockerfile、docker-compose.yml。
9. 添加 pytest 测试，确保 pytest 通过。
10. 不要实现爬虫、前端、用户登录、自动执法或个人身份识别功能。
```

---

## 13. 推荐 Codex 分步执行

不要一次让 Codex 生成所有内容，建议分 8 次执行：

### 第 1 次

生成 monorepo 目录结构、公共 schemas、配置、日志工具。

### 第 2 次

实现公共词库、文本归一化、关键词匹配、联系方式脱敏。

### 第 3 次

实现文本服务 FastAPI、`/health`、`/infer/text`、`/infer/content`、`/infer/batch`。

### 第 4 次

实现文本评分、实体抽取、解释生成、测试。

### 第 5 次

实现语音服务 FastAPI、上传文件、媒体校验、FFmpeg 抽音频。

### 第 6 次

实现 Mock ASR、语音关键词匹配、语音评分、证据片段导出。

### 第 7 次

实现 Whisper / FunASR 可选适配器和模型信息接口。

### 第 8 次

补齐 README、Dockerfile、docker-compose、端到端测试和启动说明。

---

## 14. 最终交付验收清单

### 14.1 启动验收

```bash
docker compose up --build
```

访问：

```bash
curl http://localhost:8010/health
curl http://localhost:8020/health
```

### 14.2 文本接口验收

```bash
curl -X POST "http://localhost:8010/infer/text" \
  -H "Content-Type: application/json" \
  -d '{"content_id":"t1","source":"comment","text":"刚到一批，懂的私聊，主页有方式"}'
```

预期：

```text
risk_level 为 medium 或 high
risk_types 包含 trade_lead 或 sale_intent
```

### 14.3 白名单文本验收

```bash
curl -X POST "http://localhost:8010/infer/text" \
  -H "Content-Type: application/json" \
  -d '{"content_id":"t2","source":"title","text":"控烟宣传活动，未成年人禁止吸烟"}'
```

预期：

```text
risk_level 为 none 或 low
risk_types 包含 whitelist_context
```

### 14.4 语音 Mock 验收

设置：

```env
ASR_ENGINE=mock
MOCK_TRANSCRIPT=刚到一批，需要的看主页，私聊安排
```

调用：

```bash
curl -X POST "http://localhost:8020/infer/audio" \
  -F "file=@demo.wav" \
  -F "content_id=a1"
```

预期：

```text
返回 transcript
risk_level 为 medium 或 high
evidence_segments 不为空，或在 save_evidence=false 时为空但不报错
```

### 14.5 测试验收

```bash
pytest
```

预期：

```text
全部测试通过
```

---

## 15. 本期不做事项

本落地方案明确不做：

1. 爬虫采集。
2. 用户登录。
3. 前端管理后台。
4. 多模态最终融合服务。
5. 图像识别。
6. 声纹识别。
7. 人脸识别。
8. 自动处罚或自动执法。
9. 私密数据采集。
10. 售卖话术生成或规避监管建议。

---

## 16. 后续版本规划

### V0.1

- Mock + 规则版本。
- 文本服务可用。
- 语音服务可上传和 Mock 转写。
- 完成 JSON 输出。

### V0.2

- 接入 faster-whisper。
- 接入文本 Transformers 分类器。
- 完成 Docker 部署。

### V0.3

- 接入 FunASR / SenseVoice。
- 增加 VAD、标点恢复、时间戳增强。
- 增加语音证据片段裁剪。

### V0.4

- 增加异步任务队列。
- 增加结果持久化。
- 增加模型版本管理。

### V1.0

- 接入多模态融合服务。
- 接入人工审核反馈闭环。
- 接入生产级监控、告警和审计。
