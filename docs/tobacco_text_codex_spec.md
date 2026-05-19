# AI烟草违法监测系统：文本识别模块项目开发说明

> 用途：将本文档直接提供给 Codex / AI 编程助手，生成一个可运行的文本风险识别服务原型。  
> 项目重点：面向短视频标题、正文、评论、账号简介、OCR 文本、ASR 转写文本，识别烟草违法交易相关的关键词、黑话、品牌词、交易意图、联系方式引流和白名单语境。  
> 约束：本项目用于监管合规场景的违法烟草交易监测，不用于广告投放、售卖引流或规避监管。

---

## 1. 项目名称

`tobacco-text-risk-service`

---

## 2. 项目目标

开发一个基于 Python 的文本风险识别服务，支持输入单条文本、批量文本或结构化内容，自动完成以下任务：

1. 文本清洗与归一化：
   - 繁简转换
   - 大小写归一
   - 空格、表情、特殊符号清洗
   - 变体词、谐音词、拆字词处理
   - 联系方式脱敏

2. 规则识别：
   - 烟草品牌词识别
   - 交易关键词识别
   - 黑话词识别
   - 联系方式和引流词识别
   - 价格、数量、规格识别
   - 白名单语境识别

3. 语义模型识别：
   - 违规售烟意图识别
   - 交易引流识别
   - 控烟宣传 / 新闻报道 / 普通讨论识别
   - 疑似隐晦表达识别

4. 输出文本风险评分：
   - `text_score`
   - `risk_level`
   - `risk_types`
   - `hit_keywords`
   - `brand_entities`
   - `contact_entities`
   - `evidence_text`
   - `explanation`

5. 提供 HTTP API：
   - 单条文本识别接口
   - 批量文本识别接口
   - 多字段内容识别接口
   - 词库查询接口
   - 健康检查接口
   - 模型信息接口

6. 生成可供后续多模态系统使用的 JSON 结果。

---

## 3. 技术栈要求

### 3.1 后端

- Python 3.10+
- FastAPI
- Uvicorn
- Pydantic
- NumPy
- jieba 或 pkuseg
- opencc-python-reimplemented，用于繁简转换
- regex
- SQLite，后续可替换为 PostgreSQL / Oracle
- 可选：Transformers + PyTorch
- 可选：ONNX Runtime

### 3.2 模型

项目必须支持以下两种模型模式：

#### 模式 A：规则 + Mock 模型模式

当本地不存在文本分类模型时，系统仍可启动。

- 使用规则词库完成初步识别
- 使用简单启发式逻辑生成风险分
- 返回 Mock 模型字段
- 用于前后端联调和 Demo

#### 模式 B：真实语义模型模式

当配置了文本模型目录时：

- 使用 Transformers 加载中文 RoBERTa / BERT-wwm / MacBERT 分类模型
- 支持多标签分类
- 支持模型置信度输出
- 支持 CPU 环境运行
- 支持后续导出 ONNX

---

## 4. 推荐目录结构

请按如下结构生成项目：

```text
tobacco-text-risk-service/
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
│   │   ├── dictionaries.py
│   │   └── models.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── normalizer.py
│   │   ├── dictionary_matcher.py
│   │   ├── entity_extractor.py
│   │   ├── semantic_classifier.py
│   │   ├── scoring.py
│   │   ├── explanation.py
│   │   └── masking.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── text_utils.py
│   │   ├── file_utils.py
│   │   └── logging.py
│   └── data/
│       ├── brand_keywords.json
│       ├── risk_keywords.json
│       ├── slang_keywords.json
│       ├── whitelist_keywords.json
│       └── label_mapping.json
├── storage/
│   └── results/
├── models/
│   └── .gitkeep
├── tests/
│   ├── test_health.py
│   ├── test_normalizer.py
│   ├── test_dictionary_matcher.py
│   ├── test_entity_extractor.py
│   └── test_scoring.py
└── scripts/
    ├── run_dev.sh
    ├── infer_text.py
    └── infer_batch.py
```

---

## 5. 配置文件要求

创建 `.env.example`：

```env
APP_NAME=tobacco-text-risk-service
APP_ENV=dev
HOST=0.0.0.0
PORT=8010

# Model
USE_MOCK_MODEL=true
TEXT_MODEL_DIR=models/text-risk-model
TEXT_MODEL_TYPE=transformers
MAX_TEXT_LENGTH=512

# Dictionary
ENABLE_RULES=true
ENABLE_TRADITIONAL_TO_SIMPLIFIED=true
ENABLE_MASKING=true

# Risk threshold
RISK_HIGH=0.85
RISK_MEDIUM=0.70
RISK_LOW=0.50

# Storage
RESULT_DIR=storage/results
```

`app/config.py` 需要读取环境变量，并提供默认值。

---

## 6. 文本输入范围

系统需要支持以下文本来源字段：

```json
{
  "title": "视频标题",
  "description": "视频正文或商品描述",
  "account_name": "账号名称",
  "account_bio": "账号简介",
  "comments": ["评论1", "评论2"],
  "ocr_texts": ["图片或视频帧 OCR 文本"],
  "asr_texts": ["语音转写文本"],
  "platform": "douyin",
  "content_url": "https://example.com/content/123"
}
```

---

## 7. 标签体系设计

### 7.1 风险类型

```json
{
  "sale_intent": "疑似售烟意图",
  "trade_lead": "交易引流",
  "brand_mention": "烟草品牌提及",
  "slang_mention": "黑话/隐晦表达",
  "contact_lead": "联系方式引流",
  "price_quantity": "价格/数量/规格表达",
  "whitelist_context": "白名单语境",
  "normal_discussion": "普通讨论"
}
```

### 7.2 风险等级

```json
{
  "high": "高风险",
  "medium": "中风险",
  "low": "低风险",
  "none": "无明显风险"
}
```

---

## 8. 词库设计

### 8.1 `brand_keywords.json`

```json
{
  "中华": ["中华", "中華", "双中支", "硬中华", "软中华"],
  "利群": ["利群", "休闲", "新版利群"],
  "黄鹤楼": ["黄鹤楼", "黃鶴樓", "1916"],
  "玉溪": ["玉溪", "软玉溪", "硬玉溪"],
  "云烟": ["云烟", "雲煙", "紫云"],
  "芙蓉王": ["芙蓉王", "硬芙蓉王"],
  "南京": ["南京", "雨花石", "九五"],
  "红塔山": ["红塔山"],
  "外烟": ["万宝路", "Marlboro", "Dunhill", "Camel", "Winston", "LM"]
}
```

### 8.2 `risk_keywords.json`

```json
{
  "trade": ["现货", "到货", "私聊", "私信", "可发", "包邮", "秒发", "一条", "整条", "拿货", "出货"],
  "contact": ["微信", "vx", "v信", "QQ", "电话", "手机号", "加我", "主页有"],
  "price": ["元", "包", "条", "价格", "报价", "低价"],
  "quantity": ["一条", "一盒", "一件", "整条", "成条", "批发"],
  "delivery": ["同城", "快递", "顺丰", "发货", "包邮", "到付"]
}
```

### 8.3 `slang_keywords.json`

```json
{
  "暗示交易": ["懂的来", "老规矩", "看主页", "有需要", "安排", "你懂的"],
  "隐晦联系方式": ["v", "薇", "卫星", "企鹅", "扣扣"],
  "隐晦商品": ["口粮", "华子", "楼子", "小目标", "条子"]
}
```

### 8.4 `whitelist_keywords.json`

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
  "app": "tobacco-text-risk-service",
  "version": "0.1.0"
}
```

### 9.2 模型信息

`GET /models/info`

返回：

```json
{
  "semantic_model": {
    "enabled": true,
    "mock": true,
    "model_dir": "models/text-risk-model",
    "labels": ["sale_intent", "trade_lead", "brand_mention"]
  },
  "rules": {
    "enabled": true,
    "dictionaries": ["brand_keywords", "risk_keywords", "slang_keywords", "whitelist_keywords"]
  }
}
```

### 9.3 单条文本识别

`POST /infer/text`

请求：

```json
{
  "content_id": "txt_202605180001",
  "source": "comment",
  "text": "刚到一批，懂的私聊，主页有方式"
}
```

返回：

```json
{
  "content_id": "txt_202605180001",
  "source": "comment",
  "text_score": 0.88,
  "risk_level": "high",
  "risk_types": ["sale_intent", "trade_lead", "contact_lead"],
  "hit_keywords": [
    {
      "word": "刚到一批",
      "category": "trade",
      "start": 0,
      "end": 4
    },
    {
      "word": "私聊",
      "category": "trade",
      "start": 8,
      "end": 10
    }
  ],
  "brand_entities": [],
  "contact_entities": [
    {
      "type": "contact_hint",
      "text": "主页有方式",
      "masked": "主页有方式"
    }
  ],
  "evidence_text": [
    {
      "source": "comment",
      "text": "刚到一批，懂的私聊，主页有方式",
      "start": 0,
      "end": 15
    }
  ],
  "explanation": "文本中同时出现到货、私聊和联系方式暗示，存在交易引流风险。",
  "model_version": "text-risk-v0.1.0"
}
```

### 9.4 多字段内容识别

`POST /infer/content`

请求：

```json
{
  "content_id": "video_202605180001",
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

返回：

```json
{
  "content_id": "video_202605180001",
  "text_score": 0.91,
  "risk_level": "high",
  "risk_types": ["sale_intent", "trade_lead", "contact_lead"],
  "field_results": [
    {
      "field": "title",
      "score": 0.55,
      "risk_types": ["slang_mention"],
      "evidence": ["懂的来"]
    },
    {
      "field": "comments",
      "score": 0.86,
      "risk_types": ["trade_lead"],
      "evidence": ["什么价", "还有货吗", "私聊"]
    },
    {
      "field": "ocr_texts",
      "score": 0.88,
      "risk_types": ["sale_intent"],
      "evidence": ["现货 包邮"]
    }
  ],
  "hit_keywords": ["私聊", "现货", "包邮", "什么价"],
  "brand_entities": [],
  "contact_entities": ["主页有方式"],
  "explanation": "标题、简介、评论和 OCR 文本中均出现交易或引流表达，综合文本风险较高。",
  "model_version": "text-risk-v0.1.0"
}
```

### 9.5 批量文本识别

`POST /infer/batch`

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

返回：

```json
{
  "items": [
    {
      "content_id": "c1",
      "text_score": 0.62,
      "risk_level": "low",
      "risk_types": ["trade_lead"]
    },
    {
      "content_id": "c2",
      "text_score": 0.12,
      "risk_level": "none",
      "risk_types": ["whitelist_context"]
    }
  ]
}
```

---

## 10. 核心模块实现要求

### 10.1 `normalizer.py`

实现 `TextNormalizer` 类。

功能：

1. 繁体转简体。
2. 英文转小写。
3. 全角转半角。
4. 清理不可见字符。
5. 保留中文、英文、数字、常见符号。
6. 将连续空格压缩为一个空格。
7. 可选：常见谐音、拆字词归一。

方法：

```python
class TextNormalizer:
    def normalize(self, text: str) -> str:
        ...
```

### 10.2 `dictionary_matcher.py`

实现 `DictionaryMatcher` 类。

功能：

1. 加载品牌、风险、黑话、白名单词库。
2. 支持多词库匹配。
3. 返回命中词、类别、开始位置、结束位置。
4. 支持大小写不敏感匹配。
5. 支持去重和排序。

结构：

```python
class KeywordHit(BaseModel):
    word: str
    normalized_word: str | None = None
    category: str
    dictionary: str
    start: int
    end: int
```

### 10.3 `entity_extractor.py`

实现 `EntityExtractor` 类。

识别以下实体：

1. 手机号
2. 微信号暗示
3. QQ号暗示
4. 价格
5. 数量
6. 品牌
7. 快递 / 发货表达

联系方式需要脱敏。

示例：

```json
{
  "type": "phone",
  "text": "13812345678",
  "masked": "138****5678"
}
```

### 10.4 `semantic_classifier.py`

实现 `SemanticClassifier` 类。

功能：

1. 如果模型目录不存在，则进入 Mock 模式。
2. Mock 模式下根据规则命中结果生成语义分。
3. 真实模式下加载 Transformers 文本分类模型。
4. 支持多标签分类。
5. 返回每个标签的置信度。

返回：

```python
class SemanticResult(BaseModel):
    label: str
    score: float
```

Mock 分类规则：

- 命中交易词 + 联系方式词：`sale_intent=0.85`、`trade_lead=0.90`
- 命中品牌词 + 价格词：`sale_intent=0.80`
- 命中白名单词：`whitelist_context=0.90`
- 仅普通讨论：`normal_discussion=0.70`

### 10.5 `scoring.py`

实现文本风险评分。

评分公式：

```text
text_score =
  0.30 × keyword_score
+ 0.35 × semantic_score
+ 0.15 × brand_entity_score
+ 0.10 × contact_score
+ 0.10 × context_score
- whitelist_penalty
```

#### 评分细则

`keyword_score`：

- 命中交易词：0.75
- 命中黑话词：0.80
- 命中价格词：0.60
- 命中多个类型：最高 0.95

`semantic_score`：

- 取语义模型 `sale_intent`、`trade_lead`、`contact_lead` 的最高值。

`brand_entity_score`：

- 命中品牌词：0.70
- 命中品牌 + 交易词：0.90

`contact_score`：

- 明确手机号 / QQ / 微信号：0.90
- 暗示联系方式：0.75
- 未命中：0.00

`context_score`：

- 标题、简介、评论、OCR、ASR 多字段同时命中：0.90
- 单字段命中：0.40

`whitelist_penalty`：

- 命中新闻、控烟、普法等白名单：0.20
- 白名单强语境且无交易词：0.50

风险等级：

```python
if text_score >= 0.85:
    risk_level = "high"
elif text_score >= 0.70:
    risk_level = "medium"
elif text_score >= 0.50:
    risk_level = "low"
else:
    risk_level = "none"
```

### 10.6 `explanation.py`

实现解释生成。

规则：

- 命中交易词 + 联系方式：`文本中同时出现交易引导词和联系方式暗示，存在交易引流风险。`
- 命中品牌 + 价格：`文本中出现烟草品牌及价格表达，存在疑似售卖风险。`
- 命中白名单：`文本包含控烟、新闻或普法语境，已降低风险分。`
- 多字段命中：`标题、评论、OCR/ASR 文本存在多处风险表达，综合文本风险较高。`

---

## 11. 推理流程

```text
接收文本 / 多字段内容
  ↓
字段拆分
  ↓
文本清洗与归一化
  ↓
词库匹配
  ├── 品牌词
  ├── 交易词
  ├── 黑话词
  ├── 联系方式词
  └── 白名单词
  ↓
实体抽取
  ├── 品牌
  ├── 价格
  ├── 数量
  └── 联系方式
  ↓
语义模型分类 / Mock 分类
  ↓
风险评分
  ↓
解释生成
  ↓
返回结构化 JSON
```

---

## 12. 和视觉 / 语音模块的接口约定

文本服务必须能接收以下外部模块结果：

1. 视觉 OCR 文本：
   - `ocr_texts`
2. 语音 ASR 文本：
   - `asr_texts`
3. 原始平台文本：
   - `title`
   - `description`
   - `comments`
   - `account_name`
   - `account_bio`

输出的 `text_score` 将进入多模态融合：

```text
final_score =
  0.40 × visual_score
+ 0.30 × text_score
+ 0.30 × audio_score
```

---

## 13. 异常处理要求

示例：

```json
{
  "detail": {
    "code": "INVALID_TEXT",
    "message": "文本内容不能为空"
  }
}
```

常见错误码：

```text
INVALID_TEXT
INVALID_PAYLOAD
TEXT_TOO_LONG
MODEL_LOAD_FAILED
INFERENCE_FAILED
DICTIONARY_LOAD_FAILED
CONFIG_ERROR
```

---

## 14. 日志要求

记录以下日志：

1. 请求开始和结束
2. content_id
3. 文本长度
4. 命中词数量
5. 是否使用 Mock 模型
6. 推理耗时
7. 风险分
8. 错误堆栈

日志格式示例：

```text
2026-05-18 10:00:00 | INFO | content_id=xxx | infer text done | score=0.88 | cost=32ms
```

---

## 15. 测试要求

至少实现以下测试：

### 15.1 `test_health.py`

- `/health` 返回 200
- 返回 `status=ok`

### 15.2 `test_normalizer.py`

- 繁体转简体
- 英文大小写归一
- 特殊符号清洗

### 15.3 `test_dictionary_matcher.py`

- 命中“中华”
- 命中“私聊”
- 命中“控烟”
- 无关文本不命中风险词

### 15.4 `test_entity_extractor.py`

- 手机号脱敏
- 价格识别
- 数量识别
- 联系方式暗示识别

### 15.5 `test_scoring.py`

- 品牌 + 价格 -> 中高风险
- 交易词 + 联系方式 -> 高风险
- 控烟宣传 -> 无明显风险
- 普通文本 -> 无明显风险

---

## 16. README 要求

`README.md` 必须包含：

1. 项目简介
2. 目录结构
3. 安装方式
4. 环境变量说明
5. 启动命令
6. 单条文本识别 curl 示例
7. 多字段内容识别 curl 示例
8. 批量识别 curl 示例
9. Mock 模式说明
10. 如何替换真实文本模型
11. 返回 JSON 示例
12. 后续扩展方向

启动示例：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

单条文本识别示例：

```bash
curl -X POST "http://localhost:8010/infer/text" \
  -H "Content-Type: application/json" \
  -d '{"content_id":"demo_text_001","source":"comment","text":"刚到一批，懂的私聊"}'
```

多字段内容识别示例：

```bash
curl -X POST "http://localhost:8010/infer/content" \
  -H "Content-Type: application/json" \
  -d '{"content_id":"demo_content_001","title":"懂的来","comments":["还有货吗","私聊"],"ocr_texts":["现货 包邮"]}'
```

---

## 17. 代码质量要求

1. 使用类型注解。
2. 使用 Pydantic 定义请求和响应结构。
3. 服务层和路由层分离。
4. 不要在路由函数里写复杂业务逻辑。
5. 不要硬编码路径，统一从配置读取。
6. 所有返回结果必须是可 JSON 序列化对象。
7. Mock 模式必须能完整启动和跑通接口。
8. 项目要能在 CPU 环境运行。
9. 敏感联系方式必须脱敏后返回。
10. 不要自动生成或推荐售卖话术。

---

## 18. 非目标范围

以下内容本期不实现，只预留扩展接口：

1. 社交平台爬虫
2. 前端管理后台
3. 完整数据库后台
4. 语音转写
5. 图像 OCR
6. 多模态最终判定
7. 自动执法或自动处罚决策
8. 私密账号数据采集
9. 用户身份识别

---

## 19. 合规要求

1. 只处理用户主动上传或合法授权采集的数据。
2. 不输出个人身份识别结论。
3. 联系方式、账号、手机号等敏感信息必须脱敏。
4. 模型只输出风险线索和证据文本，最终结论由人工复核或多模态审核系统确认。
5. 不提供任何帮助规避监管的表达生成能力。

---

## 20. Codex 生成顺序建议

请按以下顺序实现：

1. 创建项目目录和基础配置。
2. 实现 `schemas.py`。
3. 实现 `config.py`。
4. 实现健康检查路由。
5. 实现文本清洗模块。
6. 实现词库加载和匹配模块。
7. 实现实体验取和脱敏模块。
8. 实现 Mock 语义分类器。
9. 实现风险评分模块。
10. 实现解释生成模块。
11. 实现单条文本识别接口。
12. 实现多字段内容识别接口。
13. 实现批量识别接口。
14. 添加测试。
15. 完善 README。
16. 确保 `pytest` 通过。
17. 确保 `uvicorn app.main:app --reload` 可启动。

---

## 21. 最终交付标准

生成的项目必须满足：

1. `pip install -r requirements.txt` 可安装依赖。
2. `uvicorn app.main:app --reload` 可启动。
3. 浏览器访问 `http://localhost:8010/health` 返回正常。
4. 不放置真实模型时，Mock 模式能跑通所有接口。
5. 放置文本模型后，能自动切换为真实推理。
6. 单条文本、多字段内容、批量文本均能返回结构化 JSON。
7. 风险评分、命中词、证据文本、解释字段完整。
8. 敏感联系方式脱敏。
9. 测试用例能运行。
10. README 能指导用户完成本地运行。

---

## 22. 可扩展方向

后续版本可加入：

1. RoBERTa / MacBERT 多标签分类模型微调。
2. ONNX Runtime 推理加速。
3. 黑话自动发现。
4. 语义相似检索。
5. 人工审核反馈闭环。
6. 与视觉 OCR、语音 ASR 的统一文本风险分析。
7. MLflow 模型版本管理。
8. Kafka / Redis 队列异步处理。
9. PostgreSQL / Oracle 持久化。
10. 管理后台词库维护。
