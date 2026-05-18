# AI烟草违法监测系统：视觉识别模块项目开发说明

> 用途：将本文档直接提供给 Codex / AI 编程助手，生成一个可运行的视觉识别项目原型。  
> 项目重点：面向短视频、直播截图、商品图、聊天截图中的烟盒、条盒、香烟、交易场景和画面文字，输出结构化视觉风险结果。  
> 约束：本项目用于监管合规场景的违法烟草交易监测，不用于广告投放、售卖引流或规避监管。

---

## 1. 项目名称

`tobacco-vision-risk-service`

---

## 2. 项目目标

开发一个基于 Python 的视觉识别服务，支持上传图片或视频，自动完成以下任务：

1. 检测画面中的烟草相关目标：
   - 烟盒 / 单包烟
   - 条盒 / 整条烟
   - 单支香烟
   - 吸烟人员
   - 快递包裹 / 打包场景
   - 价格牌 / 商品展示文字区域

2. 对检测到的烟盒区域进行二次分析：
   - 裁剪烟盒 ROI
   - OCR 识别包装文字、价格、联系方式、交易引导语
   - 品牌词匹配
   - 场景标签判断

3. 输出视觉风险评分：
   - `visual_score`
   - `risk_level`
   - `detected_objects`
   - `brand_results`
   - `ocr_text`
   - `scene_tags`
   - `evidence_frames`

4. 提供 HTTP API：
   - 图片识别接口
   - 视频识别接口
   - 健康检查接口
   - 模型信息接口

5. 生成可供后续多模态系统使用的 JSON 结果。

---

## 3. 技术栈要求

### 3.1 后端

- Python 3.10+
- FastAPI
- Uvicorn
- Pydantic
- OpenCV
- NumPy
- Pillow
- Ultralytics YOLO
- PaddleOCR 或 RapidOCR
- SQLite，后续可替换为 PostgreSQL / Oracle
- 本地文件系统保存证据帧，后续可替换为对象存储

### 3.2 模型

项目必须支持以下两种模型模式：

#### 模式 A：无权重 Mock 模式

当本地不存在 YOLO 权重文件时，系统仍可启动。

- 返回 Mock 检测结果
- 用于前后端联调
- 方便在没有 GPU 和模型文件的环境中运行

#### 模式 B：真实推理模式

当配置了 YOLO 权重文件时：

- 使用 Ultralytics YOLO 加载权重
- 支持图片推理
- 支持视频抽帧推理
- 支持置信度阈值配置
- 支持类别名映射

---

## 4. 推荐目录结构

请按如下结构生成项目：

```text
tobacco-vision-risk-service/
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
│   │   ├── detector.py
│   │   ├── ocr.py
│   │   ├── video.py
│   │   ├── scoring.py
│   │   ├── evidence.py
│   │   └── brand_matcher.py
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── image_io.py
│   │   ├── file_utils.py
│   │   └── logging.py
│   └── data/
│       ├── brand_keywords.json
│       ├── risk_keywords.json
│       └── class_mapping.json
├── storage/
│   ├── uploads/
│   ├── evidence/
│   └── results/
├── weights/
│   └── .gitkeep
├── tests/
│   ├── test_health.py
│   ├── test_scoring.py
│   └── test_brand_matcher.py
└── scripts/
    ├── run_dev.sh
    ├── infer_image.py
    └── infer_video.py
```

---

## 5. 配置文件要求

创建 `.env.example`：

```env
APP_NAME=tobacco-vision-risk-service
APP_ENV=dev
HOST=0.0.0.0
PORT=8000

# YOLO
YOLO_WEIGHTS=weights/best.pt
YOLO_CONF=0.35
YOLO_IOU=0.45
YOLO_IMG_SIZE=960
USE_MOCK_MODEL=true

# OCR
ENABLE_OCR=true
OCR_ENGINE=paddleocr

# Video
VIDEO_SAMPLE_FPS=1
MAX_VIDEO_SECONDS=180
MAX_EVIDENCE_FRAMES=10

# Storage
UPLOAD_DIR=storage/uploads
EVIDENCE_DIR=storage/evidence
RESULT_DIR=storage/results

# Risk threshold
RISK_HIGH=0.85
RISK_MEDIUM=0.70
RISK_LOW=0.50
```

`app/config.py` 需要读取环境变量，并提供默认值。

---

## 6. 视觉类别设计

系统需要支持以下目标类别。即使模型类别不完全一致，也要通过 `class_mapping.json` 映射为统一类别。

### 6.1 统一类别

```json
{
  "cigarette_pack": "烟盒/单包烟",
  "cigarette_carton": "条盒/整条烟",
  "cigarette": "单支香烟",
  "smoking_person": "吸烟人员",
  "lighter": "打火机",
  "ashtray": "烟灰缸",
  "parcel": "快递包裹",
  "price_tag": "价格牌/价格文字区域",
  "unknown": "未知"
}
```

### 6.2 场景标签

```json
{
  "bulk_display": "批量展示",
  "delivery_scene": "快递/打包场景",
  "live_selling_scene": "直播售卖场景",
  "price_display": "价格展示",
  "advertising_scene": "商品宣传图",
  "smoking_scene": "普通吸烟场景",
  "anti_smoking_scene": "控烟宣传/新闻场景",
  "unknown_scene": "未知场景"
}
```

---

## 7. 关键词词库

创建 `app/data/brand_keywords.json`：

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

创建 `app/data/risk_keywords.json`：

```json
{
  "trade": ["现货", "到货", "私聊", "私信", "可发", "包邮", "秒发", "一条", "整条", "拿货", "出货"],
  "contact": ["微信", "vx", "v信", "QQ", "电话", "手机号", "加我", "主页有"],
  "price": ["元", "包", "条", "价格", "报价", "低价"],
  "whitelist": ["控烟", "禁烟", "新闻", "普法", "危害", "宣传", "戒烟"]
}
```

---

## 8. API 设计

### 8.1 健康检查

`GET /health`

返回：

```json
{
  "status": "ok",
  "app": "tobacco-vision-risk-service",
  "version": "0.1.0"
}
```

### 8.2 模型信息

`GET /models/info`

返回：

```json
{
  "detector": {
    "type": "yolo",
    "weights": "weights/best.pt",
    "mock": true,
    "classes": ["cigarette_pack", "cigarette_carton", "cigarette"]
  },
  "ocr": {
    "enabled": true,
    "engine": "paddleocr"
  }
}
```

### 8.3 图片识别

`POST /infer/image`

请求：

- `multipart/form-data`
- 字段名：`file`
- 支持：jpg、jpeg、png、webp

可选参数：

- `content_id`
- `save_evidence`
- `conf`

返回：

```json
{
  "content_id": "img_202605180001",
  "media_type": "image",
  "visual_score": 0.88,
  "risk_level": "high",
  "detected_objects": [
    {
      "class_name": "cigarette_carton",
      "label_zh": "条盒/整条烟",
      "bbox": [120, 88, 420, 260],
      "confidence": 0.91,
      "timestamp": null
    }
  ],
  "brand_results": [
    {
      "brand": "中华",
      "confidence": 0.86,
      "source": "ocr_keyword"
    }
  ],
  "ocr_text": [
    {
      "text": "现货 私聊",
      "confidence": 0.92,
      "bbox": [430, 120, 620, 170]
    }
  ],
  "scene_tags": ["bulk_display", "price_display"],
  "evidence_frames": [
    {
      "timestamp": null,
      "image_path": "storage/evidence/img_202605180001/evidence_001.jpg",
      "description": "画面中出现条盒/整条烟，并伴随交易引导文字"
    }
  ],
  "model_version": "vision-tobacco-v0.1.0"
}
```

### 8.4 视频识别

`POST /infer/video`

请求：

- `multipart/form-data`
- 字段名：`file`
- 支持：mp4、mov、avi、mkv

可选参数：

- `content_id`
- `sample_fps`
- `max_seconds`
- `conf`

返回：

```json
{
  "content_id": "video_202605180001",
  "media_type": "video",
  "duration_seconds": 32.5,
  "sampled_frames": 33,
  "visual_score": 0.91,
  "risk_level": "high",
  "detected_objects": [
    {
      "class_name": "cigarette_pack",
      "label_zh": "烟盒/单包烟",
      "bbox": [122, 90, 410, 250],
      "confidence": 0.89,
      "timestamp": "00:00:13.000"
    }
  ],
  "brand_results": [
    {
      "brand": "利群",
      "confidence": 0.80,
      "source": "ocr_keyword"
    }
  ],
  "ocr_text": [
    {
      "text": "到货 私聊",
      "confidence": 0.88,
      "bbox": [430, 120, 620, 170]
    }
  ],
  "scene_tags": ["bulk_display", "delivery_scene"],
  "evidence_frames": [
    {
      "timestamp": "00:00:13.000",
      "image_path": "storage/evidence/video_202605180001/frame_013.jpg",
      "description": "视频关键帧中出现烟盒及疑似交易文字"
    }
  ],
  "model_version": "vision-tobacco-v0.1.0"
}
```

---

## 9. 核心模块实现要求

### 9.1 `detector.py`

实现 `TobaccoDetector` 类。

功能：

1. 初始化时读取 YOLO 权重路径。
2. 如果 `USE_MOCK_MODEL=true` 或权重不存在，进入 Mock 模式。
3. 真实模式下使用 `ultralytics.YOLO` 加载模型。
4. 提供 `predict_image(image: np.ndarray, conf: float | None) -> list[Detection]`。
5. 返回统一结构，不要暴露底层 YOLO 原始对象。

统一检测结构：

```python
class Detection(BaseModel):
    class_name: str
    label_zh: str
    bbox: list[float]
    confidence: float
    timestamp: str | None = None
```

Mock 模式规则：

- 如果图片宽高有效，返回 1 个 `cigarette_pack` 示例框。
- 置信度 0.76。
- bbox 位于图片中心区域。
- 仅用于联调，不要写死为高风险，仍交给评分模块处理。

### 9.2 `ocr.py`

实现 `OCRService` 类。

功能：

1. 如果 `ENABLE_OCR=false`，返回空列表。
2. 优先使用 PaddleOCR。
3. 如果 PaddleOCR 未安装或初始化失败，自动降级为 Mock OCR。
4. 提供 `recognize(image: np.ndarray) -> list[OCRText]`。
5. 支持对整图 OCR，也支持对烟盒 ROI OCR。

统一 OCR 结构：

```python
class OCRText(BaseModel):
    text: str
    confidence: float
    bbox: list[float] | None = None
```

Mock OCR：

- 返回空列表。
- 不要默认返回交易词，避免误导评分。

### 9.3 `brand_matcher.py`

实现 `BrandMatcher` 类。

功能：

1. 加载 `brand_keywords.json`。
2. 从 OCR 文本中匹配品牌关键词。
3. 返回品牌名和置信度。
4. 支持大小写不敏感匹配。
5. 支持中文繁简的简单兼容。

返回结构：

```python
class BrandResult(BaseModel):
    brand: str
    confidence: float
    source: str = "ocr_keyword"
```

### 9.4 `scoring.py`

实现视觉风险评分。

评分公式：

```text
visual_score =
  0.35 × tobacco_object_score
+ 0.20 × brand_score
+ 0.15 × scene_score
+ 0.15 × ocr_risk_score
+ 0.10 × frequency_score
+ 0.05 × history_score
```

一期项目中 `history_score` 固定为 0。

#### 评分细则

`tobacco_object_score`：

- 存在 `cigarette_carton`：0.95
- 存在 `cigarette_pack`：0.85
- 存在 `cigarette`：0.60
- 存在 `smoking_person`：0.50
- 无烟草目标：0.00

`brand_score`：

- 匹配到品牌：取品牌置信度，最高 1.0
- 未匹配：0.00

`scene_score`：

- 多个烟盒/条盒：0.85
- 烟盒 + 快递包裹：0.80
- 烟盒 + 价格牌：0.85
- 仅单个烟盒：0.40
- 仅吸烟：0.20

`ocr_risk_score`：

- 命中交易词：0.80
- 命中联系方式词：0.85
- 命中价格词：0.65
- 命中白名单词：需要降低风险，建议最终总分减 0.20
- 未命中：0.00

`frequency_score`：

- 视频中多帧连续出现烟盒/条盒：0.80
- 单帧出现：0.30
- 图片：0.30

风险等级：

```python
if visual_score >= 0.85:
    risk_level = "high"
elif visual_score >= 0.70:
    risk_level = "medium"
elif visual_score >= 0.50:
    risk_level = "low"
else:
    risk_level = "none"
```

### 9.5 `video.py`

实现视频抽帧。

功能：

1. 用 OpenCV 读取视频。
2. 按 `sample_fps` 抽帧。
3. 最大处理时长不超过 `MAX_VIDEO_SECONDS`。
4. 返回帧图像、帧编号、时间戳。
5. 支持视频打不开时返回明确错误。

时间戳格式：

```text
HH:MM:SS.mmm
```

### 9.6 `evidence.py`

实现证据帧保存。

功能：

1. 将高置信度检测结果绘制到图片上。
2. 保存到 `storage/evidence/{content_id}/`。
3. 最多保存 `MAX_EVIDENCE_FRAMES` 张。
4. 文件命名：
   - 图片：`evidence_001.jpg`
   - 视频：`frame_000013.jpg`
5. 返回证据帧路径和描述。

描述生成规则：

- 有烟盒 + OCR交易词：`画面中出现烟盒，并伴随交易引导文字`
- 有条盒 + 批量展示：`画面中出现多条烟草包装，疑似批量展示`
- 有香烟但无交易词：`画面中出现香烟或吸烟场景`
- 有白名单词：`画面中存在烟草相关内容，但疑似新闻/控烟宣传语境`

---

## 10. 图片推理流程

```text
接收图片
  ↓
保存原图
  ↓
读取为 OpenCV image
  ↓
YOLO / Mock 检测
  ↓
裁剪烟盒 / 条盒 ROI
  ↓
OCR 整图 + ROI
  ↓
品牌匹配
  ↓
场景标签判断
  ↓
风险评分
  ↓
保存证据图
  ↓
返回 JSON
```

---

## 11. 视频推理流程

```text
接收视频
  ↓
保存视频
  ↓
读取视频元信息
  ↓
按 sample_fps 抽帧
  ↓
逐帧检测
  ↓
对高风险帧 OCR
  ↓
汇总全部帧检测结果
  ↓
计算频次分和最高风险分
  ↓
选择 Top-K 证据帧
  ↓
返回视频级 JSON
```

---

## 12. 场景标签判断规则

一期先用规则实现，不需要训练场景模型。

```python
if cigarette_pack_count + cigarette_carton_count >= 3:
    add "bulk_display"

if has_parcel and has_tobacco_object:
    add "delivery_scene"

if has_price_tag or ocr_hit_price_keywords:
    add "price_display"

if has_smoking_person or has_cigarette:
    add "smoking_scene"

if ocr_hit_whitelist_keywords:
    add "anti_smoking_scene"
```

后续可扩展为 CLIP / VLM 场景分类。

---

## 13. 异常处理要求

API 必须返回清晰错误。

示例：

```json
{
  "detail": {
    "code": "INVALID_FILE_TYPE",
    "message": "仅支持 jpg、jpeg、png、webp、mp4、mov、avi、mkv"
  }
}
```

常见错误码：

```text
INVALID_FILE_TYPE
FILE_TOO_LARGE
VIDEO_OPEN_FAILED
MODEL_LOAD_FAILED
INFERENCE_FAILED
OCR_FAILED
CONFIG_ERROR
```

---

## 14. 日志要求

记录以下日志：

1. 请求开始和结束
2. 上传文件路径
3. 模型是否 Mock
4. 推理耗时
5. OCR 耗时
6. 风险分
7. 错误堆栈

日志格式建议：

```text
2026-05-18 10:00:00 | INFO | content_id=xxx | infer image done | score=0.88 | cost=320ms
```

---

## 15. 测试要求

至少实现以下测试：

### 15.1 `test_health.py`

- `/health` 返回 200
- 返回 `status=ok`

### 15.2 `test_scoring.py`

测试风险评分：

- 单个烟盒 -> 低/中风险
- 多条烟 + 交易词 -> 高风险
- 控烟宣传词 -> 风险下降
- 无目标 -> 无风险

### 15.3 `test_brand_matcher.py`

- OCR 文本包含“中华”时匹配品牌“中华”
- OCR 文本包含“Marlboro”时匹配“外烟”
- 无品牌词时返回空列表

---

## 16. README 要求

`README.md` 必须包含：

1. 项目简介
2. 目录结构
3. 安装方式
4. 环境变量说明
5. 启动命令
6. 图片识别 curl 示例
7. 视频识别 curl 示例
8. Mock 模式说明
9. 如何替换真实 YOLO 权重
10. 返回 JSON 示例
11. 后续扩展方向

启动示例：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

图片识别示例：

```bash
curl -X POST "http://localhost:8000/infer/image" \
  -F "file=@demo.jpg" \
  -F "content_id=demo_image_001"
```

视频识别示例：

```bash
curl -X POST "http://localhost:8000/infer/video" \
  -F "file=@demo.mp4" \
  -F "content_id=demo_video_001" \
  -F "sample_fps=1"
```

---

## 17. 代码质量要求

1. 使用类型注解。
2. 使用 Pydantic 定义请求和响应结构。
3. 服务层和路由层分离。
4. 不要在路由函数里写复杂业务逻辑。
5. 不要硬编码路径，统一从配置读取。
6. 文件保存要避免路径穿越风险。
7. 上传文件名要重新生成，不能直接信任原始文件名。
8. 所有返回结果必须是可 JSON 序列化对象。
9. 即使没有真实模型权重，也必须能完整启动和跑通 Mock 流程。
10. 项目要能在 CPU 环境运行。

---

## 18. 非目标范围

以下内容本期不实现，只预留扩展接口：

1. 用户登录和权限管理
2. 前端管理后台
3. 数据库持久化完整后台
4. 多模态最终判定
5. 语音识别
6. 社交平台爬虫
7. 大规模分布式推理
8. 人脸识别或身份识别
9. 私密数据采集
10. 自动执法或自动处罚决策

---

## 19. 合规要求

1. 只处理用户主动上传或合法授权采集的数据。
2. 不提供任何售烟、引流、绕过监管相关功能。
3. 不输出个人身份识别结果。
4. 联系方式类 OCR 结果后续接入生产系统时应脱敏。
5. 视觉模型只输出“风险线索”和“证据帧”，最终结论应由人工复核或多模态审核系统确认。

---

## 20. Codex 生成顺序建议

请按以下顺序实现：

1. 创建项目目录和基础配置。
2. 实现 `schemas.py`。
3. 实现 `config.py`。
4. 实现健康检查路由。
5. 实现 Mock `TobaccoDetector`。
6. 实现图片上传和图片推理接口。
7. 实现评分模块。
8. 实现 OCR 服务和品牌匹配。
9. 实现证据图保存。
10. 实现视频抽帧和视频推理接口。
11. 添加测试。
12. 完善 README。
13. 确保 `pytest` 通过。
14. 确保 `uvicorn app.main:app --reload` 可启动。

---

## 21. 最终交付标准

生成的项目必须满足：

1. `pip install -r requirements.txt` 可安装依赖。
2. `uvicorn app.main:app --reload` 可启动。
3. 浏览器访问 `http://localhost:8000/health` 返回正常。
4. 不放置真实权重时，Mock 模式能跑通图片和视频接口。
5. 放置 YOLO 权重后，能自动切换为真实推理。
6. 上传图片能返回结构化 JSON。
7. 上传视频能抽帧并返回结构化 JSON。
8. 证据帧能保存到 `storage/evidence/`。
9. 测试用例能运行。
10. README 能指导用户完成本地运行。

---

## 22. 可扩展方向

后续版本可加入：

1. CLIP / VLM 场景理解。
2. 烟盒 ROI 品牌分类模型。
3. PaddleOCR 画面文字定位增强。
4. ONNX / TensorRT 推理加速。
5. MLflow 模型版本管理。
6. Kafka / Redis 队列异步处理。
7. Oracle / PostgreSQL 存储结果。
8. 管理后台展示证据链。
9. 人工审核反馈闭环。
10. 与文本、语音模型做多模态融合。
