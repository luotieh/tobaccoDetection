# AI烟草违法监测系统：语音识别模块项目开发说明

> 用途：将本文档直接提供给 Codex / AI 编程助手，生成一个可运行的语音识别与语音风险分析服务原型。  
> 项目重点：面向短视频、直播录屏、音频片段中的口播内容，完成音频抽取、语音转文本、关键词识别、交易意图识别、时间戳证据片段生成和语音风险评分。  
> 约束：本项目用于监管合规场景的违法烟草交易监测，不用于广告投放、售卖引流或规避监管。

---

## 1. 项目名称

`tobacco-audio-risk-service`

---

## 2. 项目目标

开发一个基于 Python 的语音识别与语音风险分析服务，支持上传音频或视频，自动完成以下任务：

1. 音频预处理：
   - 从视频中提取音频
   - 音频格式转换
   - 采样率统一
   - 音量归一化
   - 静音片段过滤
   - 可选：噪声抑制

2. 语音转文本：
   - 使用 Whisper / 本地 ASR / 第三方 ASR 转写语音
   - 支持分段转写
   - 支持时间戳输出
   - 支持 Mock 模式

3. 语音文本风险分析：
   - 复用文本风险规则
   - 识别烟草品牌词、交易词、黑话、联系方式、价格和数量
   - 判断语音中的售卖、引流、交易暗示

4. 语音证据链生成：
   - 输出高风险语音片段开始时间和结束时间
   - 输出片段转写文本
   - 输出命中词
   - 输出对应音频切片路径

5. 输出语音风险评分：
   - `audio_score`
   - `risk_level`
   - `transcript`
   - `segments`
   - `hit_keywords`
   - `evidence_segments`
   - `explanation`

6. 提供 HTTP API：
   - 音频识别接口
   - 视频音轨识别接口
   - 健康检查接口
   - 模型信息接口

7. 生成可供后续多模态系统使用的 JSON 结果。

---

## 3. 技术栈要求

### 3.1 后端

- Python 3.10+
- FastAPI
- Uvicorn
- Pydantic
- FFmpeg
- OpenCV，可选，用于读取视频元信息
- librosa 或 soundfile，可选
- NumPy
- openai-whisper 或 faster-whisper，可选
- jieba 或 regex
- SQLite，后续可替换为 PostgreSQL / Oracle

### 3.2 模型

项目必须支持以下三种模式：

#### 模式 A：Mock ASR 模式

当没有安装 ASR 模型或没有模型文件时，系统仍可启动。

- 返回空转写或可配置的 Demo 转写
- 用于前后端联调
- 不默认制造高风险结果

#### 模式 B：本地 Whisper 模式

当配置本地 Whisper / faster-whisper 时：

- 使用本地模型完成转写
- 支持 CPU 或 GPU
- 支持分段时间戳
- 支持中文转写

#### 模式 C：外部 ASR 服务模式

预留第三方 ASR 接口，例如阿里云 ASR。

- 通过统一适配器调用
- 结果转换为内部统一 `Segment` 结构
- 支持超时和重试
- 支持错误降级

---

## 4. 推荐目录结构

请按如下结构生成项目：

```text
tobacco-audio-risk-service/
├── README.md
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── schemas.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   ├── inference.py
│   │   └── models.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── media.py
│   │   ├── audio_preprocess.py
│   │   ├── asr_base.py
│   │   ├── asr_mock.py
│   │   ├── asr_whisper.py
│   │   ├── asr_external.py
│   │   ├── keyword_matcher.py
│   │   ├── scoring.py
│   │   ├── evidence.py
│   │   └── explanation.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── file_utils.py
│   │   ├── time_utils.py
│   │   └── logging.py
│   └── data/
│       ├── audio_risk_keywords.json
│       ├── brand_keywords.json
│       ├── whitelist_keywords.json
│       └── label_mapping.json
├── storage/
│   ├── uploads/
│   ├── audio/
│   ├── evidence/
│   └── results/
├── models/
│   └── .gitkeep
├── tests/
│   ├── test_health.py
│   ├── test_time_utils.py
│   ├── test_keyword_matcher.py
│   └── test_scoring.py
└── scripts/
    ├── run_dev.sh
    ├── infer_audio.py
    └── infer_video_audio.py
```

---

## 5. 配置文件要求

创建 `.env.example`：

```env
APP_NAME=tobacco-audio-risk-service
APP_ENV=dev
HOST=0.0.0.0
PORT=8020

# ASR
ASR_ENGINE=mock
ASR_MODEL_DIR=models/whisper-small
ASR_LANGUAGE=zh
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8

# Media
MAX_MEDIA_SECONDS=300
AUDIO_SAMPLE_RATE=16000
ENABLE_VAD=false
ENABLE_NOISE_REDUCTION=false

# Risk threshold
RISK_HIGH=0.85
RISK_MEDIUM=0.70
RISK_LOW=0.50

# Storage
UPLOAD_DIR=storage/uploads
AUDIO_DIR=storage/audio
EVIDENCE_DIR=storage/evidence
RESULT_DIR=storage/results
```

`app/config.py` 需要读取环境变量，并提供默认值。

---

## 6. 输入文件范围

系统需要支持：

```text
音频文件：wav、mp3、m4a、aac、flac
视频文件：mp4、mov、avi、mkv
```

文件处理要求：

1. 上传文件名必须重新生成，不能信任原始文件名。
2. 限制文件大小。
3. 限制最大处理时长。
4. 视频必须先抽取音频再进入 ASR。
5. 所有中间音频统一转换为：
   - wav
   - 16kHz
   - mono

---

## 7. 语音风险标签设计

```json
{
  "sale_intent": "疑似售烟意图",
  "trade_lead": "交易引流",
  "brand_mention": "烟草品牌提及",
  "slang_mention": "黑话/隐晦表达",
  "contact_lead": "联系方式引流",
  "price_quantity": "价格/数量/规格表达",
  "whitelist_context": "白名单语境",
  "normal_speech": "普通口播"
}
```

---

## 8. 关键词词库

### 8.1 `audio_risk_keywords.json`

```json
{
  "trade": ["现货", "到货", "私聊", "私信", "可发", "包邮", "秒发", "一条", "整条", "拿货", "出货"],
  "contact": ["微信", "vx", "v信", "QQ", "电话", "手机号", "加我", "主页有", "看主页"],
  "price": ["元", "包", "条", "价格", "报价", "低价"],
  "quantity": ["一条", "一盒", "一件", "整条", "成条", "批发"],
  "slang": ["懂的来", "老规矩", "看主页", "有需要", "安排", "你懂的"]
}
```

### 8.2 `brand_keywords.json`

```json
{
  "中华": ["中华", "中華", "双中支", "硬中华", "软中华", "华子"],
  "利群": ["利群", "休闲", "新版利群"],
  "黄鹤楼": ["黄鹤楼", "黃鶴樓", "1916", "楼子"],
  "玉溪": ["玉溪", "软玉溪", "硬玉溪"],
  "云烟": ["云烟", "雲煙", "紫云"],
  "芙蓉王": ["芙蓉王", "硬芙蓉王"],
  "南京": ["南京", "雨花石", "九五"],
  "外烟": ["万宝路", "Marlboro", "Dunhill", "Camel", "Winston", "LM"]
}
```

### 8.3 `whitelist_keywords.json`

```json
{
  "anti_smoking": ["控烟", "禁烟", "戒烟", "吸烟有害健康", "未成年人禁止吸烟"],
  "news": ["新闻", "通报", "查获", "案件", "执法", "处罚", "普法"],
  "education": ["宣传", "科普", "危害", "健康", "公益"]
}
```

---

## 9. API 设计

### 9.1 健康检查

`GET /health`

返回：

```json
{
  "status": "ok",
  "app": "tobacco-audio-risk-service",
  "version": "0.1.0"
}
```

### 9.2 模型信息

`GET /models/info`

返回：

```json
{
  "asr": {
    "engine": "mock",
    "model_dir": "models/whisper-small",
    "language": "zh",
    "device": "cpu"
  },
  "rules": {
    "enabled": true,
    "dictionaries": ["audio_risk_keywords", "brand_keywords", "whitelist_keywords"]
  }
}
```

### 9.3 音频识别

`POST /infer/audio`

请求：

- `multipart/form-data`
- 字段名：`file`
- 支持：wav、mp3、m4a、aac、flac

可选参数：

- `content_id`
- `save_evidence`

返回：

```json
{
  "content_id": "audio_202605180001",
  "media_type": "audio",
  "duration_seconds": 25.6,
  "audio_score": 0.87,
  "risk_level": "high",
  "transcript": "刚到一批，需要的看主页，私聊安排。",
  "segments": [
    {
      "start": 3.20,
      "end": 8.50,
      "text": "刚到一批，需要的看主页",
      "confidence": 0.90
    },
    {
      "start": 8.50,
      "end": 10.20,
      "text": "私聊安排",
      "confidence": 0.88
    }
  ],
  "hit_keywords": [
    {
      "word": "刚到一批",
      "category": "trade",
      "start_time": 3.20,
      "end_time": 8.50
    },
    {
      "word": "私聊",
      "category": "trade",
      "start_time": 8.50,
      "end_time": 10.20
    }
  ],
  "brand_entities": [],
  "evidence_segments": [
    {
      "start": 3.20,
      "end": 10.20,
      "audio_path": "storage/evidence/audio_202605180001/segment_001.wav",
      "text": "刚到一批，需要的看主页，私聊安排。",
      "description": "语音片段中出现到货、私聊和联系方式暗示。"
    }
  ],
  "explanation": "语音转写文本中同时出现交易引导词和联系方式暗示，存在交易引流风险。",
  "model_version": "audio-risk-v0.1.0"
}
```

### 9.4 视频音轨识别

`POST /infer/video-audio`

请求：

- `multipart/form-data`
- 字段名：`file`
- 支持：mp4、mov、avi、mkv

可选参数：

- `content_id`
- `save_evidence`

返回结构与音频识别一致，但 `media_type` 为 `video`，并增加视频音频路径字段。

---

## 10. 核心模块实现要求

### 10.1 `media.py`

实现媒体文件处理。

功能：

1. 校验文件扩展名。
2. 保存上传文件。
3. 读取媒体时长。
4. 判断是音频还是视频。
5. 限制最大处理时长。
6. 调用 FFmpeg 从视频中提取音频。

方法示例：

```python
class MediaService:
    def save_upload_file(self, file) -> str:
        ...

    def extract_audio_from_video(self, video_path: str) -> str:
        ...

    def get_duration(self, media_path: str) -> float:
        ...
```

### 10.2 `audio_preprocess.py`

实现音频预处理。

功能：

1. 转换为 wav。
2. 转换为 16kHz。
3. 转换为 mono。
4. 可选：静音过滤。
5. 可选：噪声抑制。

输出路径：

```text
storage/audio/{content_id}/audio_16k_mono.wav
```

### 10.3 `asr_base.py`

定义统一 ASR 接口。

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

### 10.4 `asr_mock.py`

实现 Mock ASR。

规则：

1. 默认返回空转写。
2. 如果环境变量设置 `MOCK_TRANSCRIPT`，则返回该文本。
3. Mock 片段时间戳可设为 0 到音频时长。
4. 不默认返回高风险文本。

### 10.5 `asr_whisper.py`

实现本地 Whisper ASR 适配器。

功能：

1. 根据配置选择模型目录或模型名。
2. 支持 CPU / GPU。
3. 输出统一 `ASRResult`。
4. 捕获模型加载异常。
5. 支持中文语言参数。
6. 如果加载失败，回退到 Mock ASR。

### 10.6 `asr_external.py`

实现外部 ASR 预留适配器。

功能：

1. 支持通过配置启用。
2. 提供请求超时。
3. 提供重试机制。
4. 将第三方返回结果转换为统一 `ASRResult`。
5. 当前可先实现占位，返回明确错误或 Mock 结果。

### 10.7 `keyword_matcher.py`

实现语音转写文本关键词匹配。

功能：

1. 加载风险词、品牌词、白名单词。
2. 对完整 transcript 和 segment text 分别匹配。
3. 命中词需要尽量映射到 segment 时间戳。
4. 返回词、类别、所属片段时间。

结构：

```python
class AudioKeywordHit(BaseModel):
    word: str
    category: str
    start_time: float | None = None
    end_time: float | None = None
    segment_text: str | None = None
```

### 10.8 `scoring.py`

实现语音风险评分。

评分公式：

```text
audio_score =
  0.30 × keyword_score
+ 0.30 × intent_score
+ 0.15 × brand_score
+ 0.15 × contact_score
+ 0.10 × repetition_score
- whitelist_penalty
```

#### 评分细则

`keyword_score`：

- 命中交易词：0.75
- 命中黑话词：0.80
- 命中价格词：0.60
- 命中多个风险类型：最高 0.95

`intent_score`：

- 命中“到货 + 私聊 / 看主页 / 加我”等组合：0.90
- 命中“价格 + 数量”：0.75
- 仅单个交易词：0.45

`brand_score`：

- 命中品牌词：0.70
- 品牌 + 交易词：0.90

`contact_score`：

- 明确联系方式：0.90
- 暗示联系方式：0.75
- 未命中：0.00

`repetition_score`：

- 多个片段重复出现交易表达：0.80
- 单个片段出现：0.30
- 未出现：0.00

`whitelist_penalty`：

- 命中新闻、控烟、普法等白名单：0.20
- 白名单强语境且无交易词：0.50

风险等级：

```python
if audio_score >= 0.85:
    risk_level = "high"
elif audio_score >= 0.70:
    risk_level = "medium"
elif audio_score >= 0.50:
    risk_level = "low"
else:
    risk_level = "none"
```

### 10.9 `evidence.py`

实现语音证据片段生成。

功能：

1. 根据高风险 segment 的开始、结束时间裁剪音频。
2. 最多保存 5 个证据片段。
3. 证据文件保存到：
   - `storage/evidence/{content_id}/segment_001.wav`
4. 输出证据片段描述。

描述生成规则：

- 命中交易词 + 联系方式：`语音片段中出现交易引导词和联系方式暗示。`
- 命中品牌 + 价格：`语音片段中出现烟草品牌和价格表达。`
- 命中白名单：`语音片段疑似控烟、新闻或普法语境。`

### 10.10 `explanation.py`

实现解释生成。

规则：

- 高风险：`语音转写文本中同时出现交易引导词、联系方式或价格表达，存在交易引流风险。`
- 中风险：`语音转写文本中出现烟草相关交易表达，但证据尚不完整。`
- 低风险：`语音转写文本中出现烟草相关表达，建议结合视觉和文本结果判断。`
- 无风险：`语音转写文本中未发现明显违法交易表达。`

---

## 11. 推理流程

### 11.1 音频文件流程

```text
接收音频
  ↓
保存原始文件
  ↓
音频格式标准化
  ↓
ASR 转写
  ↓
分段文本关键词识别
  ↓
品牌词 / 交易词 / 联系方式 / 白名单匹配
  ↓
风险评分
  ↓
证据音频片段裁剪
  ↓
解释生成
  ↓
返回结构化 JSON
```

### 11.2 视频文件流程

```text
接收视频
  ↓
保存原始视频
  ↓
FFmpeg 提取音频
  ↓
音频格式标准化
  ↓
ASR 转写
  ↓
分段文本风险分析
  ↓
根据 ASR 时间戳生成证据片段
  ↓
返回视频音轨风险 JSON
```

---

## 12. 和视觉 / 文本模块的接口约定

语音服务输出的 `segments` 必须包含时间戳，方便与视觉关键帧对齐。

多模态融合示例：

```text
final_score =
  0.40 × visual_score
+ 0.30 × text_score
+ 0.30 × audio_score
```

时间戳对齐示例：

```json
{
  "timestamp": "00:00:13.000",
  "visual": "该时刻画面出现烟盒",
  "audio": "该时段口播出现“私聊安排”"
}
```

---

## 13. 异常处理要求

示例：

```json
{
  "detail": {
    "code": "UNSUPPORTED_MEDIA_TYPE",
    "message": "仅支持 wav、mp3、m4a、aac、flac、mp4、mov、avi、mkv"
  }
}
```

常见错误码：

```text
UNSUPPORTED_MEDIA_TYPE
FILE_TOO_LARGE
MEDIA_TOO_LONG
AUDIO_EXTRACT_FAILED
AUDIO_PREPROCESS_FAILED
ASR_MODEL_LOAD_FAILED
ASR_TRANSCRIBE_FAILED
EVIDENCE_EXPORT_FAILED
CONFIG_ERROR
```

---

## 14. 日志要求

记录以下日志：

1. 请求开始和结束
2. 上传文件路径
3. 媒体时长
4. ASR 引擎
5. 是否使用 Mock
6. 转写耗时
7. 命中词数量
8. 风险分
9. 错误堆栈

日志格式示例：

```text
2026-05-18 10:00:00 | INFO | content_id=xxx | infer audio done | score=0.87 | cost=1560ms
```

---

## 15. 测试要求

至少实现以下测试：

### 15.1 `test_health.py`

- `/health` 返回 200
- 返回 `status=ok`

### 15.2 `test_time_utils.py`

- 秒数转 `HH:MM:SS.mmm`
- 开始结束时间合法性校验

### 15.3 `test_keyword_matcher.py`

- 命中“私聊”
- 命中“中华”
- 命中“控烟”
- 无关转写不命中风险词

### 15.4 `test_scoring.py`

- 交易词 + 联系方式 -> 高风险
- 品牌 + 价格 -> 中高风险
- 控烟宣传 -> 无明显风险
- 空转写 -> 无明显风险

---

## 16. README 要求

`README.md` 必须包含：

1. 项目简介
2. 目录结构
3. 安装方式
4. FFmpeg 依赖说明
5. 环境变量说明
6. 启动命令
7. 音频识别 curl 示例
8. 视频音轨识别 curl 示例
9. Mock ASR 模式说明
10. 如何启用本地 Whisper
11. 返回 JSON 示例
12. 后续扩展方向

启动示例：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

音频识别示例：

```bash
curl -X POST "http://localhost:8020/infer/audio" \
  -F "file=@demo.wav" \
  -F "content_id=demo_audio_001"
```

视频音轨识别示例：

```bash
curl -X POST "http://localhost:8020/infer/video-audio" \
  -F "file=@demo.mp4" \
  -F "content_id=demo_video_audio_001"
```

---

## 17. 代码质量要求

1. 使用类型注解。
2. 使用 Pydantic 定义请求和响应结构。
3. 服务层和路由层分离。
4. 不要在路由函数里写复杂业务逻辑。
5. 不要硬编码路径，统一从配置读取。
6. 上传文件名要重新生成，不能直接信任原始文件名。
7. 所有返回结果必须是可 JSON 序列化对象。
8. Mock 模式必须能完整启动和跑通接口。
9. 项目要能在 CPU 环境运行。
10. 证据音频片段必须来自用户上传或授权处理的文件。

---

## 18. 非目标范围

以下内容本期不实现，只预留扩展接口：

1. 社交平台爬虫
2. 前端管理后台
3. 完整数据库后台
4. 视觉识别
5. 多模态最终判定
6. 声纹识别或说话人身份识别
7. 私密音频采集
8. 自动执法或自动处罚决策

---

## 19. 合规要求

1. 只处理用户主动上传或合法授权采集的音视频。
2. 不进行声纹识别、身份识别或个人身份推断。
3. 语音转写中的联系方式、账号、手机号等敏感信息后续接入生产系统时应脱敏。
4. 模型只输出风险线索和证据片段，最终结论由人工复核或多模态审核系统确认。
5. 不提供任何帮助规避监管的语音内容生成能力。

---

## 20. Codex 生成顺序建议

请按以下顺序实现：

1. 创建项目目录和基础配置。
2. 实现 `schemas.py`。
3. 实现 `config.py`。
4. 实现健康检查路由。
5. 实现媒体文件保存和校验。
6. 实现 FFmpeg 音频提取。
7. 实现音频标准化。
8. 实现 Mock ASR。
9. 实现关键词匹配。
10. 实现风险评分。
11. 实现解释生成。
12. 实现音频识别接口。
13. 实现视频音轨识别接口。
14. 实现证据音频片段保存。
15. 添加测试。
16. 完善 README。
17. 确保 `pytest` 通过。
18. 确保 `uvicorn app.main:app --reload` 可启动。

---

## 21. 最终交付标准

生成的项目必须满足：

1. `pip install -r requirements.txt` 可安装依赖。
2. 本机安装 FFmpeg 后可正常处理音视频。
3. `uvicorn app.main:app --reload` 可启动。
4. 浏览器访问 `http://localhost:8020/health` 返回正常。
5. 不放置真实 ASR 模型时，Mock 模式能跑通接口。
6. 启用本地 Whisper 后，能自动切换为真实转写。
7. 上传音频能返回结构化 JSON。
8. 上传视频能提取音频并返回结构化 JSON。
9. 高风险片段能保存到 `storage/evidence/`。
10. 测试用例能运行。
11. README 能指导用户完成本地运行。

---

## 22. 可扩展方向

后续版本可加入：

1. faster-whisper GPU 加速。
2. VAD 语音活动检测。
3. 噪声抑制。
4. 方言适配。
5. ASR 置信度校准。
6. 与文本风险服务共享词库。
7. 与视觉关键帧做时间戳对齐。
8. Kafka / Redis 队列异步处理。
9. MLflow 模型版本管理。
10. PostgreSQL / Oracle 持久化。
