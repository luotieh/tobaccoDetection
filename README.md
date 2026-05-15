# 烟草违法售卖监测综合管理平台 Demo

这是根据 `docs/DEMO_SPEC.md` 生成的可运行 Demo。后端使用 Python 标准库实现 HTTP API 与 SQLite 数据存储，前端为后端直接托管的管理后台单页应用。

## 功能范围

- 工作台统计：采集量、识别量、高风险线索、待审核、确认线索、推送成功数。
- 内容管理：新增、查询、删除内容，执行 Mock 识别，查看内容详情。
- 模型管理：维护文本、图像、语音、多模态融合模型配置。
- 多模态融合配置：维护文本、图像、语音、账号权重和风险阈值。
- 规则管理：维护关键词、黑话、品牌词、白名单、地域词。
- Mock 模型接口：文本、图像、语音、融合评分接口。
- 人工审核：确认违法、误报、暂存观察、忽略。
- 推送管理：线索加入推送队列，模拟推送监管平台，查看推送日志。

## 运行要求

- Python 3.10+
- 无需安装第三方依赖

## 启动

```bash
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
```

## 演示流程

1. 打开工作台查看统计。
2. 进入“识别内容列表”，对样例内容点击“识别”。
3. 进入详情页查看文本、图像、语音和融合结果。
4. 在详情页提交人工审核。
5. 将确认线索加入推送队列。
6. 进入“推送管理”模拟推送监管平台并查看日志。
