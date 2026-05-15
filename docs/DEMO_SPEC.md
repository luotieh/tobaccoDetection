# 烟草违法售卖监测综合管理平台 Demo 需求说明

## 1. Demo目标

创建一个用于演示的“烟草违法售卖监测综合管理平台”Demo。

本Demo重点展示以下能力：

1. 管理待识别内容列表；
2. 配置文本、图像、语音三个模型服务；
3. 配置多模态融合规则；
4. 维护关键词、黑话、品牌词、白名单等识别规则；
5. 展示三模态识别结果；
6. 展示综合风险评分；
7. 支持人工复核；
8. 支持生成线索并模拟推送监管平台。

本Demo不需要真实接入抖音、快手、小红书等平台，也不需要真实AI模型。  
模型识别结果可使用 Mock API 或本地规则模拟。

---

## 2. 技术落地

### 前端

当前 Demo 采用后端直接托管的静态单页管理后台，未引入前端构建链，便于快速演示和本地部署。

| 项 | 实际实现 |
|---|---|
| 页面文件 | `static/index.html` |
| 交互逻辑 | `static/app.js`，原生 JavaScript |
| 样式 | `static/styles.css` |
| 路由 | Hash 路由，如 `#dashboard`、`#contents`、`#detail/C001` |
| 网络请求 | 浏览器原生 `fetch` |
| 图表展示 | CSS 条形图模拟平台分布、风险分布、模态命中、7日趋势 |
| UI风格 | 政务管理后台风格，深蓝主色，表格和标签为主 |

说明：原建议的 React、TypeScript、Vite、Ant Design、Axios、ECharts 未在当前 Demo 中使用。当前实现优先保证“一条命令启动、无第三方依赖、完整业务闭环可演示”。

### 后端

当前 Demo 后端使用 Python 标准库实现，没有使用 FastAPI 或 Node.js。

| 项 | 实际实现 |
|---|---|
| 入口文件 | `app.py` |
| HTTP 服务 | `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler` |
| API 格式 | REST 风格 JSON API |
| Mock 模型 | `app.py` 内本地规则函数：文本、图像、语音、多模态融合 |
| 并发模型 | Python 标准库线程 HTTP Server，满足 Demo 演示 |
| 运行方式 | `python3 app.py`，默认监听 `http://127.0.0.1:8000` |

### 数据存储

当前 Demo 使用 SQLite 持久化数据。

| 项 | 实际实现 |
|---|---|
| 数据库文件 | `data/demo.db` |
| 初始化方式 | 首次启动自动建表并写入样例数据 |
| 重置方式 | 删除 `data/demo.db` 后重新启动 |
| 数据访问 | Python 标准库 `sqlite3` |

### 代码结构

```text
tobaccoDetection
├── app.py                 # 后端 API、SQLite 初始化、Mock 模型、静态文件托管
├── requirements.txt       # 无第三方依赖说明
├── static
│   ├── index.html         # 管理后台入口
│   ├── app.js             # 前端页面、路由、API 调用和交互
│   └── styles.css         # 政务后台样式
├── data
│   └── demo.db            # 运行后自动生成的 SQLite 数据库
└── docs
    └── DEMO_SPEC.md       # Demo 说明与落地文档
```

### 本地运行

```bash
python3 app.py
```

默认访问地址：

```text
http://127.0.0.1:8000
```

指定端口：

```bash
python3 app.py 8080
```

---

## 3. 系统模块

| 一级模块 | 二级功能 | 说明 |
|---|---|---|
| 工作台 | 数据概览 | 展示今日识别量、高风险线索、待审核数量、推送成功数量 |
| 内容管理 | 识别内容列表 | 管理待识别的视频、图片、文本、评论、账号信息 |
| 内容管理 | 内容详情 | 查看原始内容、三模态结果、综合评分、审核状态 |
| 模型管理 | 文本模型配置 | 配置文本模型接口、版本、阈值、启停状态 |
| 模型管理 | 图像模型配置 | 配置图像模型接口、版本、阈值、启停状态 |
| 模型管理 | 语音模型配置 | 配置语音模型接口、版本、阈值、启停状态 |
| 模型管理 | 多模态融合配置 | 配置文本、图像、语音权重和风险等级阈值 |
| 规则管理 | 关键词词库 | 管理违法关键词、交易词、引流词 |
| 规则管理 | 黑话词库 | 管理烟草相关黑话、谐音、变体 |
| 规则管理 | 品牌词库 | 管理烟草品牌名称、别称 |
| 规则管理 | 白名单词库 | 管理容易误判但不应触发风险的词 |
| 审核管理 | 待审核线索 | 审核AI识别出的中高风险内容 |
| 审核管理 | 审核记录 | 查看已确认、误报、忽略的线索 |
| 推送管理 | 推送队列 | 管理待推送监管平台的线索 |
| 推送管理 | 推送日志 | 展示模拟推送结果、失败原因、重试次数 |
| 系统管理 | 用户角色 | Demo中可简单展示角色，不要求完整权限体系 |

---

## 4. 页面清单

### 4.1 工作台 Dashboard

页面路径：

```text
/dashboard
```

展示卡片：

| 指标 | 示例 |
|---|---|
| 今日采集内容数 | 128 |
| 已完成识别数 | 96 |
| 高风险线索数 | 18 |
| 待人工审核数 | 12 |
| 已确认线索数 | 6 |
| 推送成功数 | 5 |

展示图表：

1. 平台来源分布；
2. 风险等级分布；
3. 三模态命中数量；
4. 近7日线索趋势。

---

### 4.2 识别内容列表

页面路径：

```text
/contents
```

列表字段：

| 字段 | 说明 |
|---|---|
| content_id | 内容编号 |
| platform | 平台，如抖音、快手、小红书、微博 |
| content_type | 内容类型：视频、图片、文本、评论、账号 |
| title | 内容标题 |
| account_name | 账号名称 |
| content_url | 原始链接 |
| collect_time | 采集时间 |
| recognize_status | 识别状态 |
| risk_score | 综合风险分 |
| risk_level | 风险等级 |
| review_status | 审核状态 |
| action | 查看、识别、审核、推送 |

筛选条件：

- 平台；
- 内容类型；
- 识别状态；
- 风险等级；
- 审核状态；
- 时间范围；
- 关键词搜索。

操作按钮：

- 新增内容；
- 批量导入；
- 执行识别；
- 查看详情；
- 删除。

---

### 4.3 内容详情页

页面路径：

```text
/contents/:id
```

详情页分区：

#### 基础信息

| 字段 | 说明 |
|---|---|
| 平台 | 抖音/快手/微博/小红书 |
| 内容类型 | 视频/图片/文本/评论 |
| 标题 | 内容标题 |
| 账号名称 | 发布账号 |
| 原始链接 | URL |
| 发布时间 | 平台发布时间 |
| 采集时间 | 系统采集时间 |

#### 原始内容区

根据内容类型展示：

- 文本内容；
- 图片预览；
- 视频封面；
- 音频转写文本；
- 原始链接按钮。

#### 文本识别结果

展示：

| 字段 | 示例 |
|---|---|
| 文本风险分 | 0.86 |
| 命中关键词 | 私聊、有货、一条 |
| 命中黑话 | 绿花、黑金刚 |
| 交易意图 | 疑似交易引流 |
| 证据文本 | 想要的私聊，有货 |
| 模型版本 | text-risk-v1.0 |

#### 图像识别结果

展示：

| 字段 | 示例 |
|---|---|
| 图像风险分 | 0.91 |
| 检测对象 | 香烟包装、条盒 |
| 疑似品牌 | 中华 |
| OCR文字 | 到货、私聊 |
| 证据截图 | 图片缩略图 |
| 模型版本 | image-risk-v1.0 |

#### 语音识别结果

展示：

| 字段 | 示例 |
|---|---|
| 语音风险分 | 0.82 |
| 转写文本 | 今天刚到一批，想要的私信我 |
| 命中关键词 | 刚到一批、私信 |
| 时间戳 | 00:12-00:18 |
| 模型版本 | audio-risk-v1.0 |

#### 多模态融合结果

展示：

| 字段 | 示例 |
|---|---|
| 综合风险分 | 0.88 |
| 风险等级 | 高风险 |
| 命中模态 | 文本、图像、语音 |
| 违规类型 | 疑似线上售烟、交易引流 |
| 系统解释 | 该内容同时出现香烟包装、交易关键词和口播引流表达 |
| 建议动作 | 建议人工复核后推送监管平台 |

#### 人工审核区

审核动作：

- 确认为违法线索；
- 标记为误报；
- 暂存观察；
- 忽略；
- 加入重点账号；
- 加入白名单。

审核字段：

| 字段 | 说明 |
|---|---|
| review_status | 审核状态 |
| review_opinion | 审核意见 |
| reviewer | 审核人 |
| review_time | 审核时间 |

---

## 5. 模型配置管理

页面路径：

```text
/models
```

### 5.1 模型配置字段

| 字段 | 说明 |
|---|---|
| model_id | 模型编号 |
| model_name | 模型名称 |
| model_type | text / image / audio / fusion |
| model_version | 模型版本 |
| endpoint | 模型接口地址 |
| threshold | 风险阈值 |
| timeout | 超时时间 |
| enabled | 是否启用 |
| description | 说明 |

### 5.2 示例数据

```json
[
  {
    "model_id": "m_text_001",
    "model_name": "文本交易意图识别模型",
    "model_type": "text",
    "model_version": "v1.0.0",
    "endpoint": "http://localhost:8000/mock/text/analyze",
    "threshold": 0.7,
    "timeout": 30,
    "enabled": true,
    "description": "用于识别标题、评论、账号简介中的违法售烟关键词和交易意图"
  },
  {
    "model_id": "m_image_001",
    "model_name": "图像香烟包装识别模型",
    "model_type": "image",
    "model_version": "v1.0.0",
    "endpoint": "http://localhost:8000/mock/image/analyze",
    "threshold": 0.75,
    "timeout": 30,
    "enabled": true,
    "description": "用于识别图片和视频帧中的香烟包装、品牌和OCR文字"
  },
  {
    "model_id": "m_audio_001",
    "model_name": "语音交易话术识别模型",
    "model_type": "audio",
    "model_version": "v1.0.0",
    "endpoint": "http://localhost:8000/mock/audio/analyze",
    "threshold": 0.7,
    "timeout": 60,
    "enabled": true,
    "description": "用于短视频口播转写和交易话术识别"
  },
  {
    "model_id": "m_fusion_001",
    "model_name": "多模态融合评分模型",
    "model_type": "fusion",
    "model_version": "v1.0.0",
    "endpoint": "http://localhost:8000/mock/fusion/analyze",
    "threshold": 0.8,
    "timeout": 30,
    "enabled": true,
    "description": "综合文本、图像、语音结果输出最终风险评分"
  }
]
```

---

## 6. 多模态融合配置

页面路径：

```text
/fusion-config
```

配置字段：

| 字段 | 默认值 | 说明 |
|---|---:|---|
| text_weight | 0.30 | 文本风险权重 |
| image_weight | 0.35 | 图像风险权重 |
| audio_weight | 0.25 | 语音风险权重 |
| account_weight | 0.10 | 账号行为权重 |
| high_risk_threshold | 0.85 | 高风险阈值 |
| medium_risk_threshold | 0.65 | 中风险阈值 |
| low_risk_threshold | 0.40 | 低风险阈值 |

融合公式：

```text
综合风险分 =
文本风险分 × 0.30
+ 图像风险分 × 0.35
+ 语音风险分 × 0.25
+ 账号行为分 × 0.10
```

风险等级：

| 等级 | 分数范围 |
|---|---:|
| 高风险 | >= 0.85 |
| 中风险 | >= 0.65 且 < 0.85 |
| 低风险 | >= 0.40 且 < 0.65 |
| 无风险 | < 0.40 |

---

## 7. 规则与词库管理

页面路径：

```text
/rules
```

### 7.1 词库类型

| 类型 | 说明 | 示例 |
|---|---|---|
| keyword | 违法关键词 | 私聊、有货、到货、一条、面交 |
| blackword | 黑话词库 | 绿花、黑金刚、懂的来 |
| brand | 品牌词库 | 中华、玉溪、黄鹤楼 |
| whitelist | 白名单词库 | 科普、新闻、禁烟宣传 |
| region | 地域词库 | 本地城市、区县、商圈 |

### 7.2 词库字段

| 字段 | 说明 |
|---|---|
| rule_id | 规则编号 |
| rule_type | 规则类型 |
| word | 词条 |
| risk_weight | 风险权重 |
| enabled | 是否启用 |
| remark | 备注 |
| create_time | 创建时间 |

---

## 8. 审核管理

页面路径：

```text
/reviews
```

列表字段：

| 字段 | 说明 |
|---|---|
| review_id | 审核编号 |
| content_id | 内容编号 |
| platform | 平台 |
| title | 标题 |
| risk_score | 综合风险分 |
| risk_level | 风险等级 |
| review_status | 审核状态 |
| reviewer | 审核人 |
| review_time | 审核时间 |
| action | 查看、审核 |

审核状态：

| 状态 | 说明 |
|---|---|
| pending | 待审核 |
| confirmed | 已确认违法线索 |
| false_positive | 误报 |
| ignored | 忽略 |
| observing | 暂存观察 |

---

## 9. 推送管理

页面路径：

```text
/push
```

### 9.1 推送队列

字段：

| 字段 | 说明 |
|---|---|
| push_id | 推送编号 |
| content_id | 内容编号 |
| report_id | 线索报告编号 |
| risk_level | 风险等级 |
| push_status | 推送状态 |
| push_time | 推送时间 |
| retry_count | 重试次数 |
| error_message | 错误信息 |

推送状态：

| 状态 | 说明 |
|---|---|
| waiting | 待推送 |
| success | 推送成功 |
| failed | 推送失败 |
| retrying | 重试中 |

### 9.2 模拟推送

点击“推送监管平台”后，调用 Mock 接口：

```text
POST /api/mock/regulatory-platform/push
```

成功返回：

```json
{
  "success": true,
  "message": "推送成功",
  "report_id": "R202605150001"
}
```

失败返回：

```json
{
  "success": false,
  "message": "接口超时，等待重试"
}
```

---

## 10. Mock模型接口

### 10.1 文本识别接口

```text
POST /api/mock/text/analyze
```

请求：

```json
{
  "content_id": "C001",
  "text": "想要的私聊，今天有货"
}
```

响应：

```json
{
  "text_risk_score": 0.86,
  "hit_keywords": ["私聊", "有货"],
  "hit_black_words": [],
  "intent_type": "疑似交易引流",
  "evidence_text": "想要的私聊，今天有货",
  "confidence": 0.91,
  "model_version": "text-risk-v1.0"
}
```

---

### 10.2 图像识别接口

```text
POST /api/mock/image/analyze
```

请求：

```json
{
  "content_id": "C001",
  "image_url": "/mock/images/cigarette_001.jpg"
}
```

响应：

```json
{
  "image_risk_score": 0.92,
  "detected_objects": ["香烟包装", "条盒"],
  "brand": "疑似中华",
  "ocr_text": ["私聊", "到货"],
  "confidence": 0.89,
  "evidence_frame": "/mock/images/evidence_001.jpg",
  "model_version": "image-risk-v1.0"
}
```

---

### 10.3 语音识别接口

```text
POST /api/mock/audio/analyze
```

请求：

```json
{
  "content_id": "C001",
  "audio_url": "/mock/audio/audio_001.mp3"
}
```

响应：

```json
{
  "audio_risk_score": 0.88,
  "transcript": "今天刚到一批，想要的私信我",
  "hit_keywords": ["刚到一批", "私信"],
  "intent_type": "疑似交易引流",
  "timestamp": "00:12-00:18",
  "confidence": 0.87,
  "model_version": "audio-risk-v1.0"
}
```

---

### 10.4 多模态融合接口

```text
POST /api/mock/fusion/analyze
```

请求：

```json
{
  "content_id": "C001",
  "text_risk_score": 0.86,
  "image_risk_score": 0.92,
  "audio_risk_score": 0.88,
  "account_risk_score": 0.7
}
```

响应：

```json
{
  "risk_score": 0.88,
  "risk_level": "高风险",
  "violation_type": ["图像疑似售烟", "文本交易引流", "语音交易暗示"],
  "model_explanation": "该内容同时出现香烟包装、交易关键词和口播引流表达，综合判断为高风险违法售烟线索。",
  "review_suggestion": "建议人工复核后推送监管平台。",
  "model_version": "fusion-risk-v1.0"
}
```

---

## 11. 数据库表设计

当前 Demo 的表结构由 `app.py` 中的 `SCHEMA` 常量维护，首次启动时自动执行建表。除业务表外，当前实现还增加了 `fusion_config` 表用于保存多模态融合权重和风险阈值。

### 11.1 content_items

识别内容表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 内容ID |
| platform | string | 平台 |
| content_type | string | 内容类型 |
| title | string | 标题 |
| account_name | string | 账号名称 |
| account_url | string | 账号主页 |
| content_url | string | 原始链接 |
| raw_text | text | 文本内容 |
| media_url | string | 图片/视频/音频地址 |
| publish_time | datetime | 发布时间 |
| collect_time | datetime | 采集时间 |
| recognize_status | string | 识别状态 |
| risk_score | float | 综合风险分 |
| risk_level | string | 风险等级 |
| review_status | string | 审核状态 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

---

### 11.2 model_configs

模型配置表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 模型ID |
| model_name | string | 模型名称 |
| model_type | string | text/image/audio/fusion |
| model_version | string | 模型版本 |
| endpoint | string | 接口地址 |
| threshold | float | 阈值 |
| timeout | int | 超时时间 |
| enabled | boolean | 是否启用 |
| description | text | 描述 |

---

### 11.3 recognition_results

识别结果表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 结果ID |
| content_id | string | 内容ID |
| model_type | string | text/image/audio/fusion |
| model_version | string | 模型版本 |
| risk_score | float | 风险分 |
| result_json | json | 识别结果 |
| created_at | datetime | 创建时间 |

---

### 11.4 rule_words

词库规则表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 规则ID |
| rule_type | string | keyword/blackword/brand/whitelist/region |
| word | string | 词条 |
| risk_weight | float | 风险权重 |
| enabled | boolean | 是否启用 |
| remark | text | 备注 |
| created_at | datetime | 创建时间 |

---

### 11.5 review_records

审核记录表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 审核ID |
| content_id | string | 内容ID |
| review_status | string | 审核状态 |
| review_opinion | text | 审核意见 |
| reviewer | string | 审核人 |
| review_time | datetime | 审核时间 |

---

### 11.6 push_logs

推送日志表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | 推送ID |
| content_id | string | 内容ID |
| report_id | string | 报告ID |
| push_status | string | 推送状态 |
| push_time | datetime | 推送时间 |
| retry_count | int | 重试次数 |
| error_message | text | 错误信息 |

---

### 11.7 fusion_config

多模态融合配置表。

| 字段 | 类型 | 说明 |
|---|---|---|
| id | int | 固定为 1 |
| text_weight | float | 文本风险权重 |
| image_weight | float | 图像风险权重 |
| audio_weight | float | 语音风险权重 |
| account_weight | float | 账号行为权重 |
| high_risk_threshold | float | 高风险阈值 |
| medium_risk_threshold | float | 中风险阈值 |
| low_risk_threshold | float | 低风险阈值 |

---

## 12. Demo样例数据

初始化至少10条内容数据：

| 平台 | 类型 | 标题 | 预期风险 |
|---|---|---|---|
| 抖音 | 视频 | 今天刚到一批，懂的来 | 高 |
| 快手 | 视频 | 老客户私聊 | 高 |
| 小红书 | 图片 | 礼盒分享，仅展示 | 中 |
| 微博 | 文本 | 禁烟宣传科普 | 无 |
| 抖音 | 评论 | 多少钱一条 | 高 |
| 小红书 | 图片 | 新包装收藏展示 | 低 |
| 快手 | 视频 | 本地现货，主页有方式 | 高 |
| 微博 | 文本 | 新闻报道：打击违法售烟 | 无 |
| 抖音 | 视频 | 老牌子到货 | 中 |
| 小红书 | 评论 | 怎么拿，私信吗 | 高 |

---

## 13. 识别流程

点击“执行识别”后，系统流程如下：

```text
1. 读取内容基础信息
2. 如果存在文本，调用文本模型Mock接口
3. 如果存在图片或视频封面，调用图像模型Mock接口
4. 如果存在音频或视频，调用语音模型Mock接口
5. 汇总三个模态的风险分
6. 调用多模态融合接口
7. 更新内容综合风险分和风险等级
8. 生成识别结果记录
9. 高风险或中风险内容进入待审核列表
```

---

## 14. 验收标准

Demo完成后应满足：

1. 可以查看工作台统计数据；
2. 可以管理识别内容列表；
3. 可以新增、编辑、删除待识别内容；
4. 可以配置文本、图像、语音、多模态模型；
5. 可以维护关键词、黑话、品牌词、白名单；
6. 可以点击“执行识别”并生成Mock识别结果；
7. 可以在详情页查看三模态结果；
8. 可以查看综合风险评分和风险解释；
9. 可以进行人工审核；
10. 可以将确认线索加入推送队列；
11. 可以模拟推送监管平台；
12. 可以查看推送日志。

---

## 15. Demo界面风格

要求：

- 政务系统风格；
- 简洁、清晰、偏管理后台；
- 主色建议使用深蓝或科技蓝；
- 表格信息密度适中；
- 风险等级用明显标签区分。

风险等级颜色建议：

| 风险等级 | 颜色 |
|---|---|
| 高风险 | 红色 |
| 中风险 | 橙色 |
| 低风险 | 蓝色 |
| 无风险 | 灰色 |

---

## 16. 菜单结构

```text
烟草违法售卖监测平台
├── 工作台
├── 内容管理
│   ├── 识别内容列表
│   └── 内容详情
├── 模型管理
│   ├── 模型配置
│   └── 多模态融合配置
├── 规则管理
│   ├── 关键词词库
│   ├── 黑话词库
│   ├── 品牌词库
│   └── 白名单词库
├── 审核管理
│   ├── 待审核线索
│   └── 审核记录
├── 推送管理
│   ├── 推送队列
│   └── 推送日志
└── 系统管理
    └── 用户角色
```

---

## 17. 重要说明

1. 本Demo不需要接入真实AI模型；
2. 本Demo不需要真实采集互联网平台数据；
3. 本Demo不需要真实推送烟草监管平台；
4. 所有模型识别结果可通过规则或随机Mock生成；
5. 后续真实项目中，Mock模型接口可替换为真实模型服务；
6. 平台重点体现“内容管理、模型配置、规则管理、识别结果、人工复核、线索推送”的业务闭环。

---

## 18. 最终交付物

当前仓库已生成一个可运行 Demo，实际交付物如下：

| 交付项 | 实际文件/能力 | 状态 |
|---|---|---|
| 前端管理后台 | `static/index.html`、`static/app.js`、`static/styles.css` | 已实现 |
| 后端 API 服务 | `app.py` | 已实现 |
| 初始化样例数据 | `app.py:init_db()` 首次启动写入 10 条内容、模型配置、融合配置、词库规则 | 已实现 |
| Mock 模型接口 | `/api/mock/text/analyze`、`/api/mock/image/analyze`、`/api/mock/audio/analyze`、`/api/mock/fusion/analyze` | 已实现 |
| 识别流程 | `/api/contents/{id}/recognize` | 已实现 |
| 人工审核流程 | `/api/contents/{id}/review` | 已实现 |
| 推送日志流程 | `/api/contents/{id}/push-queue`、`/api/push/{id}/send` | 已实现 |
| README 运行说明 | `README.md` | 已实现 |

### 18.1 实际 API 清单

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

### 18.2 实际演示路径

```text
1. 启动服务：python3 app.py
2. 打开：http://127.0.0.1:8000
3. 进入“识别内容列表”，选择样例内容执行识别
4. 进入内容详情查看文本、图像、语音和融合结果
5. 在详情页提交人工审核
6. 将线索加入推送队列
7. 在“推送管理”模拟推送监管平台并查看推送日志
```

### 18.3 当前实现边界

1. 当前 Demo 不依赖第三方 Python 包，`requirements.txt` 仅保留说明；
2. 前端未使用 React/Vite/Ant Design/ECharts，采用原生 HTML/CSS/JavaScript；
3. 图像和语音识别不读取真实媒体文件，基于内容编号、媒体地址和本地规则生成 Mock 结果；
4. 推送监管平台为随机成功/失败的 Mock 流程，不访问外部网络；
5. 页面使用 Hash 路由，主要路径为 `#dashboard`、`#contents`、`#detail/{id}`、`#models`、`#fusion`、`#rules`、`#reviews`、`#push`、`#users`。
