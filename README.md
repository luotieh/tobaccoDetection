# 烟草违法售卖监测综合管理平台 Demo

这是根据 `docs/DEMO_SPEC.md` 生成的可运行 Demo。后端使用 Python 标准库实现 HTTP API 与 SQLite 数据存储，前端为后端直接托管的管理后台单页应用。

仓库内同时根据 `docs/tobacco_vision_codex_spec.md` 增加了 FastAPI 视觉识别服务原型 `tobacco-vision-risk-service`，用于图片/视频烟草视觉风险识别。

## 功能范围

- 工作台统计：采集量、识别量、高风险线索、待审核、确认线索、推送成功数。
- 内容管理：新增、查询、删除内容，执行 Mock 识别，查看内容详情。
- 模型管理：维护文本、图像、语音、多模态融合模型配置。
- 多模态融合配置：维护文本、图像、语音、账号权重和风险阈值。
- 规则管理：维护关键词、黑话、品牌词、白名单、地域词。
- Mock 模型接口：文本、图像、语音、融合评分接口。
- 图像识别测试：上传图片调用 Hugging Face `basant18/Smoking-detection-YOLO26s` 或 `Enos-123/smoking-detection` 的 `best.pt` 做 YOLO 目标检测，并支持前端切换模型。
- 人工审核：确认违法、误报、暂存观察、忽略。
- 推送管理：线索加入推送队列，模拟推送监管平台，查看推送日志。

## 运行要求

- Python 3.10+
- 图像识别依赖 `ultralytics`、`opencv-python`

## 启动

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
```

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
