# 烟草违法售卖监测综合管理平台 Demo

这是根据 `docs/DEMO_SPEC.md` 生成的可运行 Demo。后端使用 Python 标准库实现 HTTP API 与 SQLite 数据存储，前端为后端直接托管的管理后台单页应用。

仓库内同时根据 `docs/tobacco_vision_codex_spec.md`、`docs/tobacco_text_audio_implementation_plan.md` 增加了 FastAPI 视觉、文本、语音识别服务，用于图片/视频、文本内容和音视频口播的烟草违法交易风险识别。

## 功能范围

- 工作台统计：采集量、识别量、高风险线索、待审核、确认线索、推送成功数。
- 内容管理：新增、查询、删除内容，执行 Mock 识别，查看内容详情。
- 模型管理：维护文本、图像、语音、多模态融合模型配置。
- 多模态融合配置：维护文本、图像、语音、账号权重和风险阈值。
- 规则管理：维护关键词、黑话、品牌词、白名单、地域词。
- Mock 模型接口：文本、图像、语音、融合评分接口。
- 图像识别测试：上传图片调用 Hugging Face `basant18/Smoking-detection-YOLO26s` 或 `Enos-123/smoking-detection` 的 `best.pt` 做 YOLO 目标检测，并支持前端切换模型。
- 文本识别测试：调用文本风险服务识别标题、正文、评论、OCR/ASR 转写文本。
- 语音识别测试：上传音频或视频，调用语音服务完成 ASR 转写、规则识别、评分和证据片段输出。
- 人工审核：确认违法、误报、暂存观察、忽略。
- 推送管理：线索加入推送队列，模拟推送监管平台，查看推送日志。

## 运行要求

- Python 3.10+
- 图像识别依赖 `ultralytics`、`opencv-python`
- 文本/语音服务依赖 `fastapi`、`uvicorn`、`python-multipart`；语音真实媒体处理建议安装 FFmpeg。

## 启动

推荐先复制环境变量模板：

```bash
cp .env.example .env
```

本地一键启动四个服务：

```bash
scripts/start_all.sh dev
```

可用 profile：

```text
dev  - 开发联调模式，允许 Mock，语音 Mock 默认不制造命中转写。
demo - 演示模式，显式启用视觉 Mock 和语音演示转写，适合前端闭环展示。
real - 真实推理模式，关闭模型 fallback，需要本地 YOLO 权重和 Whisper/ASR 可用。
```

查看状态和停止服务：

```bash
scripts/status_all.sh
scripts/stop_all.sh
```

管理后台 Demo：

```bash
pip install -r requirements.txt
python3 app.py
```

默认地址：

```text
http://127.0.0.1:8000
```

也可以指定端口：

```bash
python3 app.py 8080
```

视觉识别服务：

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload
```

也可以使用脚本：

```bash
HOST=0.0.0.0 PORT=9000 scripts/run_dev.sh
```

文本识别服务：

```bash
TEXT_PORT=8010 scripts/run_text_dev.sh
```

语音识别服务：

```bash
AUDIO_PORT=8020 scripts/run_audio_dev.sh
```

管理后台可以通过同源代理调用三个识别服务：

```bash
VISION_SERVICE_URL=http://127.0.0.1:9000 \
TEXT_SERVICE_URL=http://127.0.0.1:8010 \
AUDIO_SERVICE_URL=http://127.0.0.1:8020 \
python3 app.py 8000
```

Docker Compose 启动完整服务：

```bash
docker compose up --build
```

Compose 默认读取 `.env.example`，如果存在本地 `.env` 会自动覆盖同名变量。它会启动管理端、视觉服务、文本服务和语音服务。管理端地址为：

```text
http://127.0.0.1:8000
```

首次启动会自动创建 SQLite 数据库：

```text
data/demo.db
```

如需重置样例数据，停止服务后删除该文件再重新启动即可。

## 主要 API

```text
GET    /api/dashboard
GET    /api/contents
POST   /api/contents
GET    /api/contents/{id}
PUT    /api/contents/{id}
DELETE /api/contents/{id}
POST   /api/contents/{id}/recognize
POST   /api/contents/{id}/review
POST   /api/contents/{id}/push-queue
POST   /api/crawler/push

GET    /api/models
PUT    /api/models/{id}
GET    /api/fusion-config
PUT    /api/fusion-config

GET    /api/rules
POST   /api/rules
PUT    /api/rules/{id}
DELETE /api/rules/{id}

GET    /api/reviews
GET    /api/push
POST   /api/push/{id}/send

POST   /api/mock/text/analyze
POST   /api/mock/image/analyze
POST   /api/mock/audio/analyze
POST   /api/mock/fusion/analyze
POST   /api/mock/regulatory-platform/push

GET    /api/image-detector/status
POST   /api/image-detector/analyze

GET    /api/text-service/status
POST   /api/text-service/infer-text
POST   /api/text-service/infer-content

GET    /api/audio-service/status
POST   /api/audio-service/infer-audio
POST   /api/audio-service/infer-video-audio
```

爬虫端可按 `docs/__init__.py` 中的 `ReturnData` 结构推送采集结果：

```bash
curl -X POST http://127.0.0.1:8000/api/crawler/push \
  -H 'Content-Type: application/json' \
  -d '{"platform":"小红书","type":"note","timeTook":1.2,"data":[]}'
```

管理端会将 `VideoData`/`NoteData` 转为内容列表记录，保留作者、媒体列表、原始 payload，并把一二级评论写入 `crawler_comments` 供文本识别使用。

## 视觉识别服务

目录结构：

```text
app/
  main.py              # FastAPI 入口
  config.py            # 环境变量配置
  schemas.py           # Pydantic 响应结构
  routers/             # health、models、inference 路由
  services/            # detector、ocr、video、scoring、evidence、brand_matcher
  data/                # 品牌词、风险词、统一类别映射
storage/
  uploads/ evidence/ results/
weights/
```

环境变量见 `.env.example`。默认优先加载 `models/best.pt`；如果 `USE_MOCK_MODEL=true` 或权重不存在，会进入 Mock 模式，仍能跑通上传和评分流程。

现有管理后台已经接入视觉服务：在“识别内容列表”执行识别时，如果内容的 `media_url` 指向本地图片文件，会优先调用 `VISION_SERVICE_URL` 的 `/infer/image`，并将返回的 `visual_score`、检测对象、OCR、品牌和证据结果写入内容详情的图像识别结果；视觉服务不可用时自动回退到管理后台内置 YOLO，再回退 Mock 结果。

```bash
VISION_SERVICE_URL=http://127.0.0.1:9000 python3 app.py
```

健康检查：

```bash
curl http://127.0.0.1:9000/health
```

模型信息：

```bash
curl http://127.0.0.1:9000/models/info
```

图片识别：

```bash
curl -X POST "http://127.0.0.1:9000/infer/image" \
  -F "file=@demo.jpg" \
  -F "content_id=demo_image_001" \
  -F "conf=0.35"
```

视频识别：

```bash
curl -X POST "http://127.0.0.1:9000/infer/video" \
  -F "file=@demo.mp4" \
  -F "content_id=demo_video_001" \
  -F "sample_fps=1"
```

返回 JSON 包含：

```json
{
  "content_id": "demo_image_001",
  "media_type": "image",
  "visual_score": 0.45,
  "risk_level": "none",
  "detected_objects": [],
  "brand_results": [],
  "ocr_text": [],
  "scene_tags": ["unknown_scene"],
  "evidence_frames": [],
  "model_version": "vision-tobacco-v0.1.0"
}
```

替换真实 YOLO 权重：

```bash
YOLO_WEIGHTS=/path/to/best.pt USE_MOCK_MODEL=false uvicorn app.main:app --port 9000
```

测试：

```bash
pytest
```

后续扩展方向：接入 CLIP/VLM 场景理解、烟盒 ROI 品牌分类、PaddleOCR 增强、ONNX/TensorRT 加速、队列异步推理和审核反馈闭环。

## 文本识别服务

`text_service` 根据落地方案提供可运行文本风险服务，默认端口 `8010`。当前实现包含公共归一化、词库加载、关键词匹配、实体抽取、联系方式脱敏、Mock/可选 Transformers/本地 LLM 语义分类器、风险评分和解释生成。

```bash
TEXT_PORT=8010 scripts/run_text_dev.sh
```

语义分类引擎通过 `TEXT_SEMANTIC_ENGINE` 选择，默认 `mock` 不需要额外模型依赖。可选值：

```text
mock          规则驱动的轻量语义分类，适合本地开发和无模型部署
transformers 读取 TEXT_MODEL_DIR 下的文本分类模型
llm           读取本地指令模型或第三方 OpenAI 兼容 API，并解析 JSON 标签输出
```

启用本地 LLM 前需自行安装可选依赖并准备模型目录，默认依赖文件不会强制安装大模型运行库：

```bash
pip install transformers accelerate sentencepiece torch
TEXT_SEMANTIC_ENGINE=llm \
TEXT_LLM_MODEL_DIR=text_models/qwen2.5-0.5b-instruct \
TEXT_USE_MOCK_MODEL=false \
TEXT_PORT=8010 scripts/run_text_dev.sh
```

接入第三方 OpenAI 兼容 API 时无需安装本地大模型依赖，API Key 通过环境变量注入：

```bash
export TEXT_LLM_API_KEY=sk-...
TEXT_SEMANTIC_ENGINE=llm \
TEXT_LLM_PROVIDER=openai_compatible \
TEXT_LLM_API_BASE_URL=https://api.example.com/v1 \
TEXT_LLM_API_MODEL=deepseek-chat \
TEXT_LLM_API_KEY_ENV=TEXT_LLM_API_KEY \
TEXT_USE_MOCK_MODEL=true \
TEXT_PORT=8010 scripts/run_text_dev.sh
```

主要接口：

```text
GET  /health
GET  /models/info
GET  /dictionaries
POST /infer/text
POST /infer/content
POST /infer/batch
```

单条文本识别示例：

```bash
curl -X POST http://127.0.0.1:8010/infer/text \
  -H "Content-Type: application/json" \
  -d '{"content_id":"demo_text_001","source":"comment","text":"刚到一批，懂的私聊，主页有方式"}'
```

白名单语境示例：

```bash
curl -X POST http://127.0.0.1:8010/infer/text \
  -H "Content-Type: application/json" \
  -d '{"content_id":"demo_text_002","source":"title","text":"控烟宣传活动，未成年人禁止吸烟"}'
```

## 语音识别服务

`audio_service` 根据落地方案提供独立 FastAPI 语音风险服务，默认端口 `8020`。当前实现支持上传音频/视频、FFmpeg 抽音频与转码、Mock ASR、可选 faster-whisper/FunASR 适配、关键词识别、语音评分、联系方式脱敏和证据片段导出。

```bash
AUDIO_PORT=8020 scripts/run_audio_dev.sh
```

主要接口：

```text
GET  /health
GET  /models/info
POST /infer/audio
POST /infer/video-audio
```

Mock ASR 默认返回空转写，不会把演示文本当作上传音频的真实内容。只有显式开启 `USE_MOCK_TRANSCRIPT=true` 时，才会使用环境变量提供演示转写：

```bash
USE_MOCK_TRANSCRIPT=true MOCK_TRANSCRIPT='刚到一批，需要的看主页，私聊安排' scripts/run_audio_dev.sh
```

默认落地配置使用 `faster-whisper` 做真实 ASR：

```bash
python3 -m pip install --user --break-system-packages faster-whisper imageio-ffmpeg
ASR_ENGINE=whisper ALLOW_ASR_FALLBACK=false WHISPER_MODEL_SIZE=tiny AUDIO_PORT=8020 scripts/run_audio_dev.sh
```

首次启动或首次识别会下载 Whisper 模型。后续可将 `WHISPER_MODEL_SIZE` 调整为 `small`、`medium` 或 `large-v3` 提升识别质量。

音频识别示例：

```bash
curl -X POST http://127.0.0.1:8020/infer/audio \
  -F "file=@demo.wav" \
  -F "content_id=demo_audio_001"
```

`/api/image-detector/analyze` 使用 `multipart/form-data` 上传图片，`model_id` 可选：

```bash
curl -F "image=@/path/to/image.jpg" -F "model_id=basant-yolo26s" -F "conf=0.5" -F "imgsz=800" http://127.0.0.1:8000/api/image-detector/analyze
curl -F "image=@/path/to/image.jpg" -F "model_id=enos-yolo11m" -F "conf=0.5" -F "imgsz=800" http://127.0.0.1:8000/api/image-detector/analyze
```

默认权重路径为：

```text
models/best.pt
models/enos-smoking-detection-best.pt
```

也可以通过环境变量覆盖：

```bash
SMOKING_MODEL_PATH=/path/to/best.pt python3 app.py
ENOS_SMOKING_MODEL_PATH=/path/to/best.pt python3 app.py
SMOKING_DETECTOR_MODEL=enos-yolo11m python3 app.py
```

## 演示流程

1. 打开工作台查看统计。
2. 进入“识别内容列表”，对样例内容点击“识别”。
3. 进入详情页查看文本、图像、语音和融合结果。
4. 在详情页提交人工审核。
5. 将确认线索加入推送队列。
6. 进入“推送管理”模拟推送监管平台并查看日志。
