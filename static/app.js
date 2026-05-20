const state = { route: "dashboard", data: null };

const menus = [
  ["核心功能", [["dashboard", "工作台"], ["contents", "识别内容列表"], ["image-test", "图像识别测试"], ["text-test", "文本识别测试"], ["audio-test", "语音识别测试"]]],
  ["配置管理", [["models", "模型配置"], ["fusion", "多模态融合配置"], ["rules", "规则词库"]]],
  ["业务闭环", [["reviews", "审核管理"], ["push", "推送管理"], ["users", "用户角色"]]],
];

const titles = {
  dashboard: ["工作台", "数据概览与线索趋势"],
  contents: ["识别内容列表", "管理待识别内容并执行 Mock 识别"],
  "image-test": ["图像识别测试", "上传图片调用 best.pt 目标检测接口"],
  "text-test": ["文本识别测试", "调用文本风险服务识别标题、正文、评论和 OCR/ASR 文本"],
  "audio-test": ["语音识别测试", "上传音频或视频调用语音风险服务"],
  detail: ["内容详情", "查看三模态识别结果、融合评分和审核动作"],
  models: ["模型配置", "配置文本、图像、语音与融合模型"],
  fusion: ["多模态融合配置", "调整权重和风险等级阈值"],
  rules: ["规则词库", "维护关键词、黑话、品牌词、白名单和地域词"],
  reviews: ["审核管理", "处理中高风险待审核线索"],
  push: ["推送管理", "生成线索并模拟推送监管平台"],
  users: ["用户角色", "演示系统角色"],
};

const $ = (sel) => document.querySelector(sel);
const api = async (url, options = {}) => {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
};

const apiForm = async (url, formData) => {
  const res = await fetch(url, { method: "POST", body: formData });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
};

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 2200);
}

function riskTag(level) {
  const map = { 高风险: "red", 中风险: "orange", 低风险: "blue", 无风险: "gray" };
  return `<span class="tag ${map[level] || "gray"}">${level || "无风险"}</span>`;
}

function statusText(status) {
  return ({
    pending: "待审核", confirmed: "已确认", false_positive: "误报", ignored: "忽略",
    observing: "暂存观察", unreviewed: "未审核", completed: "已识别", waiting: "待推送",
    success: "推送成功", failed: "推送失败", retrying: "重试中"
  })[status] || status || "-";
}

function statusTag(status) {
  const color = { confirmed: "green", pending: "orange", success: "green", failed: "red", completed: "green" }[status] || "gray";
  return `<span class="tag ${color}">${statusText(status)}</span>`;
}

function setRoute(route) {
  location.hash = route;
}

function currentRoute() {
  const raw = location.hash.replace(/^#/, "") || "dashboard";
  if (raw.startsWith("detail/")) return ["detail", raw.split("/")[1]];
  return [raw, null];
}

function renderNav() {
  $("#nav").innerHTML = menus.map(([group, items]) => `
    <div class="nav-group">${group}</div>
    ${items.map(([route, label]) => `<a class="nav-item" href="#${route}" data-route="${route}">${label}</a>`).join("")}
  `).join("");
}

function updateChrome(route) {
  const [title, sub] = titles[route] || titles.dashboard;
  $("#pageTitle").textContent = title;
  $("#pageSub").textContent = sub;
  document.querySelectorAll(".nav-item").forEach(a => a.classList.toggle("active", a.dataset.route === route));
}

function bars(rows) {
  const max = Math.max(1, ...rows.map(r => r.value));
  return rows.map(r => `
    <div class="bar-row">
      <span>${r.name}</span><div class="bar"><span style="width:${r.value / max * 100}%"></span></div><b>${r.value}</b>
    </div>
  `).join("") || `<p class="pre">暂无数据</p>`;
}

async function renderDashboard() {
  const data = await api("/api/dashboard");
  $("#view").innerHTML = `
    <div class="cards">
      ${Object.entries(data.cards).map(([k, v]) => `<div class="card"><div class="metric-label">${k}</div><div class="metric-value">${v}</div></div>`).join("")}
    </div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">平台来源分布</h3>${bars(data.platforms)}</div>
      <div class="panel"><h3 class="section-title">风险等级分布</h3>${bars(data.risks)}</div>
      <div class="panel"><h3 class="section-title">三模态命中数量</h3>${bars(data.modalities)}</div>
      <div class="panel"><h3 class="section-title">近7日线索趋势</h3>${bars(data.trend)}</div>
    </div>
  `;
}

async function renderContents() {
  const rows = await api("/api/contents");
  $("#view").innerHTML = `
    <div class="toolbar">
      <div><label><span>关键词</span><input id="kw" placeholder="标题/账号/正文" /></label></div>
      <div><label><span>平台</span><select id="platform"><option value="">全部</option><option>抖音</option><option>快手</option><option>小红书</option><option>微博</option></select></label></div>
      <div><label><span>内容类型</span><select id="ctype"><option value="">全部</option><option>视频</option><option>图片</option><option>文本</option><option>评论</option><option>账号</option></select></label></div>
      <div><label><span>风险等级</span><select id="risk"><option value="">全部</option><option>高风险</option><option>中风险</option><option>低风险</option><option>无风险</option></select></label></div>
      <div class="actions"><button onclick="filterContents()">查询</button><button class="secondary" onclick="openContentForm()">新增内容</button></div>
    </div>
    <div class="table-wrap">${contentsTable(rows)}</div>
  `;
}

async function renderImageTest() {
  const status = await api("/api/image-detector/status");
  $("#view").innerHTML = `
    <div class="panel">
      <h3 class="section-title">模型状态 <span class="tag ${status.ready ? "green" : "red"}">${status.ready ? "已就绪" : "不可用"}</span></h3>
      <div class="kv">
        <b>服务模式</b><span>${status.service_mode || "-"}</span>
        <b>服务地址</b><span>${status.service_url || "-"}</span>
        <b>服务权重</b><span>${status.model_path || "-"}</span>
        <b>权重大小</b><span>${status.model_exists ? status.model_size_mb + " MB" : "未找到"}</span>
        <b>当前模型</b><span>${status.name}｜${status.version}</span>
        <b>依赖状态</b><span>${Object.entries(status.dependencies).map(([k, v]) => `${k}: ${v}`).join("；")}</span>
        ${status.vision_service_error ? `<b>服务错误</b><span>${status.vision_service_error}</span>` : ""}
      </div>
    </div>
    <div class="panel">
      <h3 class="section-title">上传测试</h3>
      <div class="detector-grid">
        <div class="detector-form">
          <label><span>识别模型</span><select id="detectorModel">${status.models.map(m => `<option value="${m.id}">${m.name}｜${m.version}${m.model_exists ? "" : "（未下载）"}</option>`).join("")}</select></label>
          <label><span>图片文件</span><input id="detectorFile" type="file" accept="image/*" /></label>
          <div class="form-grid">
            <label><span>置信度阈值</span><input id="detectorConf" type="number" min="0.01" max="0.99" step="0.01" value="0.50" /></label>
            <label><span>推理尺寸</span><input id="detectorSize" type="number" min="320" max="1280" step="32" value="800" /></label>
          </div>
          <div class="dialog-actions"><button id="detectorBtn" onclick="runImageDetector()">开始识别</button></div>
        </div>
        <div class="detector-preview" id="detectorPreview">请选择一张图片</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">检测结果</h3><div id="detectorSummary" class="result-box pre">暂无结果</div></div>
      <div class="panel"><h3 class="section-title">检测框</h3><div id="detectorTable" class="result-box pre">暂无结果</div></div>
    </div>
  `;
  $("#detectorModel").value = status.current_model_id;
  $("#detectorModel").addEventListener("change", refreshDetectorStatus);
  $("#detectorFile").addEventListener("change", previewDetectorFile);
}

async function refreshDetectorStatus() {
  const modelId = $("#detectorModel").value;
  const status = await api(`/api/image-detector/status?model_id=${encodeURIComponent(modelId)}`);
  const state = status.ready ? "已就绪" : "不可用";
  toast(`${status.name}：${state}`);
}

function previewDetectorFile() {
  const file = $("#detectorFile").files[0];
  if (!file) {
    $("#detectorPreview").textContent = "请选择一张图片";
    return;
  }
  const url = URL.createObjectURL(file);
  $("#detectorPreview").innerHTML = `<img src="${url}" alt="待识别图片">`;
}

async function runImageDetector() {
  const file = $("#detectorFile").files[0];
  if (!file) return toast("请先选择图片");
  const btn = $("#detectorBtn");
  btn.disabled = true;
  btn.textContent = "识别中";
  try {
    const form = new FormData();
    form.append("image", file);
    form.append("model_id", $("#detectorModel").value);
    form.append("conf", $("#detectorConf").value || "0.5");
    form.append("imgsz", $("#detectorSize").value || "800");
    const result = await apiForm("/api/image-detector/analyze", form);
    if (result.annotated_image) {
      $("#detectorPreview").innerHTML = `<img src="${result.annotated_image}" alt="识别标注图">`;
    }
    $("#detectorSummary").textContent = [
      `是否检出：${result.detected ? "是" : "否"}`,
      `最高置信度：${Number(result.confidence || 0).toFixed(4)}`,
      `风险分：${Number(result.image_risk_score || 0).toFixed(4)}`,
      `目标类别：${(result.detected_objects || []).join("、") || "-"}`,
      `模型名称：${result.model_name}`,
      `模型版本：${result.model_version}`,
      `服务模式：${result.service_mode || "-"}`,
      `${result.vision_service_error ? "视觉服务错误：" + result.vision_service_error : ""}`,
    ].join("\n");
    $("#detectorTable").innerHTML = detectionsTable(result.detections || []);
    toast("图像识别完成");
  } catch (err) {
    $("#detectorSummary").textContent = err.message;
    toast("识别失败");
  } finally {
    btn.disabled = false;
    btn.textContent = "开始识别";
  }
}

function detectionsTable(rows) {
  if (!rows.length) return `<div class="pre">未检出目标</div>`;
  return `<table><thead><tr><th>类别</th><th>置信度</th><th>坐标</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.class_name}</td><td>${Number(r.confidence).toFixed(4)}</td><td>${r.box.x1}, ${r.box.y1}, ${r.box.x2}, ${r.box.y2}</td></tr>`).join("")}</tbody></table>`;
}

async function renderTextTest() {
  const status = await api("/api/text-service/status");
  const model = status.models || {};
  $("#view").innerHTML = `
    <div class="panel">
      <h3 class="section-title">服务状态 <span class="tag green">${status.health.status || "ok"}</span></h3>
      <div class="kv">
        <b>服务地址</b><span>${status.base_url}</span>
        <b>应用名称</b><span>${status.health.app || "-"}</span>
        <b>版本</b><span>${status.health.version || model.version || "-"}</span>
        <b>模型目录</b><span>${model.model_dir || "-"}</span>
      </div>
    </div>
    <div class="panel">
      <h3 class="section-title">单条文本测试</h3>
      <div class="form-grid">
        <label><span>内容编号</span><input id="textContentId" value="txt_ui_001" /></label>
        <label><span>来源</span><select id="textSource"><option value="comment">comment</option><option value="title">title</option><option value="ocr">ocr</option><option value="asr">asr</option><option value="profile">profile</option></select></label>
        <label class="full"><span>文本内容</span><textarea id="textInput">刚到一批，懂的私聊，主页有方式</textarea></label>
      </div>
      <div class="dialog-actions"><button id="textBtn" onclick="runTextTest()">开始识别</button></div>
    </div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">识别摘要</h3><div id="textSummary" class="result-box pre">暂无结果</div></div>
      <div class="panel"><h3 class="section-title">完整响应</h3><div id="textRaw" class="result-box pre">暂无结果</div></div>
    </div>
  `;
}

async function runTextTest() {
  const btn = $("#textBtn");
  btn.disabled = true;
  btn.textContent = "识别中";
  try {
    const result = await api("/api/text-service/infer-text", { method: "POST", body: {
      content_id: $("#textContentId").value || "txt_ui_001",
      source: $("#textSource").value || "comment",
      text: $("#textInput").value || "",
    }});
    $("#textSummary").textContent = [
      `内容编号：${result.content_id}`,
      `风险等级：${result.risk_level}`,
      `文本风险分：${Number(result.text_score || 0).toFixed(4)}`,
      `风险类型：${(result.risk_types || []).join("、") || "-"}`,
      `命中词：${(result.hit_keywords || []).map(x => x.word || x.text).filter(Boolean).join("、") || "-"}`,
      `解释：${result.explanation || "-"}`,
      `模型版本：${result.model_version || "-"}`,
    ].join("\n");
    $("#textRaw").textContent = JSON.stringify(result, null, 2);
    toast("文本识别完成");
  } catch (err) {
    $("#textSummary").textContent = err.message;
    toast("文本识别失败");
  } finally {
    btn.disabled = false;
    btn.textContent = "开始识别";
  }
}

async function renderAudioTest() {
  const status = await api("/api/audio-service/status");
  const model = status.models || {};
  $("#view").innerHTML = `
    <div class="panel">
      <h3 class="section-title">服务状态 <span class="tag green">${status.health.status || "ok"}</span></h3>
      <div class="kv">
        <b>服务地址</b><span>${status.base_url}</span>
        <b>应用名称</b><span>${status.health.app || "-"}</span>
        <b>版本</b><span>${status.health.version || model.version || "-"}</span>
        <b>ASR 类型</b><span>${model.asr_backend || model.asr_type || "-"}</span>
      </div>
    </div>
    <div class="panel">
      <h3 class="section-title">上传测试</h3>
      <div class="detector-grid">
        <div class="detector-form">
          <label><span>识别类型</span><select id="audioMode"><option value="audio">音频文件</option><option value="video">视频音轨</option></select></label>
          <label><span>内容编号</span><input id="audioContentId" value="audio_ui_001" /></label>
          <label><span>媒体文件</span><input id="audioFile" type="file" accept="audio/*,video/*" /></label>
          <label><span>保存证据片段</span><select id="audioEvidence"><option value="true">保存</option><option value="false">不保存</option></select></label>
          <div class="dialog-actions"><button id="audioBtn" onclick="runAudioTest()">开始识别</button></div>
        </div>
        <div class="detector-preview audio-preview" id="audioPreview">请选择音频或视频文件</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">识别摘要</h3><div id="audioSummary" class="result-box pre">暂无结果</div></div>
      <div class="panel"><h3 class="section-title">完整响应</h3><div id="audioRaw" class="result-box pre">暂无结果</div></div>
    </div>
  `;
  $("#audioFile").addEventListener("change", previewAudioFile);
}

function previewAudioFile() {
  const file = $("#audioFile").files[0];
  if (!file) {
    $("#audioPreview").textContent = "请选择音频或视频文件";
    return;
  }
  const url = URL.createObjectURL(file);
  if (file.type.startsWith("video/")) {
    $("#audioPreview").innerHTML = `<video src="${url}" controls></video>`;
  } else {
    $("#audioPreview").innerHTML = `<audio src="${url}" controls></audio><div class="pre">${file.name}</div>`;
  }
}

async function runAudioTest() {
  const file = $("#audioFile").files[0];
  if (!file) return toast("请先选择媒体文件");
  const btn = $("#audioBtn");
  btn.disabled = true;
  btn.textContent = "识别中";
  try {
    const form = new FormData();
    form.append("file", file);
    form.append("content_id", $("#audioContentId").value || "audio_ui_001");
    form.append("save_evidence", $("#audioEvidence").value || "true");
    const endpoint = $("#audioMode").value === "video" ? "/api/audio-service/infer-video-audio" : "/api/audio-service/infer-audio";
    const result = await apiForm(endpoint, form);
    $("#audioSummary").textContent = [
      `内容编号：${result.content_id}`,
      `媒体类型：${result.media_type}`,
      `ASR引擎：${result.asr_engine || "-"}`,
      `转写来源：${result.transcript_source || "-"}`,
      `风险等级：${result.risk_level}`,
      `语音风险分：${Number(result.audio_score || 0).toFixed(4)}`,
      `转写文本：${result.transcript || "-"}`,
      `命中词：${(result.hit_keywords || []).map(x => x.word).filter(Boolean).join("、") || "-"}`,
      `证据片段：${(result.evidence_segments || []).length}`,
      `解释：${result.explanation || "-"}`,
      `模型版本：${result.model_version || "-"}`,
    ].join("\n");
    $("#audioRaw").textContent = JSON.stringify(result, null, 2);
    toast("语音识别完成");
  } catch (err) {
    $("#audioSummary").textContent = err.message;
    toast("语音识别失败");
  } finally {
    btn.disabled = false;
    btn.textContent = "开始识别";
  }
}

function contentsTable(rows) {
  return `<table>
    <thead><tr><th>编号</th><th>平台</th><th>类型</th><th>标题</th><th>账号</th><th>采集时间</th><th>识别</th><th>风险</th><th>审核</th><th>操作</th></tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${r.id}</td><td>${r.platform}</td><td>${r.content_type}</td><td>${r.title}</td><td>${r.account_name}</td><td>${r.collect_time}</td>
      <td>${statusTag(r.recognize_status)}</td><td>${riskTag(r.risk_level)} ${Number(r.risk_score || 0).toFixed(2)}</td><td>${statusTag(r.review_status)}</td>
      <td class="actions-cell">
        <button class="secondary" onclick="setRoute('detail/${r.id}')">查看</button>
        <button onclick="recognize('${r.id}')">识别</button>
        <button class="danger" onclick="removeContent('${r.id}')">删除</button>
      </td>
    </tr>`).join("")}</tbody>
  </table>`;
}

async function filterContents() {
  const params = new URLSearchParams();
  if ($("#kw").value) params.set("keyword", $("#kw").value);
  if ($("#platform").value) params.set("platform", $("#platform").value);
  if ($("#ctype").value) params.set("content_type", $("#ctype").value);
  if ($("#risk").value) params.set("risk_level", $("#risk").value);
  const rows = await api(`/api/contents?${params.toString()}`);
  $(".table-wrap").innerHTML = contentsTable(rows);
}

function openModal(html) {
  $("#modal").innerHTML = `<div class="dialog">${html}</div>`;
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); }

function openContentForm() {
  openModal(`
    <h3>新增识别内容</h3>
    <div class="form-grid">
      <label><span>平台</span><select id="f_platform"><option>抖音</option><option>快手</option><option>小红书</option><option>微博</option></select></label>
      <label><span>内容类型</span><select id="f_type"><option>视频</option><option>图片</option><option>文本</option><option>评论</option><option>账号</option></select></label>
      <label class="full"><span>标题</span><input id="f_title" value="本地新货，私聊了解" /></label>
      <label><span>账号名称</span><input id="f_account" value="演示账号" /></label>
      <label><span>原始链接</span><input id="f_url" value="https://example.com/demo" /></label>
      <label class="full"><span>文本内容</span><textarea id="f_text">今天刚到一批，想要的私信我。</textarea></label>
      <label class="full"><span>媒体地址</span><input id="f_media" value="/tmp/vision-demo.jpg" placeholder="本地图片路径或静态资源路径" /></label>
    </div>
    <div class="dialog-actions"><button class="secondary" onclick="closeModal()">取消</button><button onclick="saveContent()">保存</button></div>
  `);
}

async function saveContent() {
  await api("/api/contents", { method: "POST", body: {
    platform: $("#f_platform").value, content_type: $("#f_type").value, title: $("#f_title").value,
    account_name: $("#f_account").value, content_url: $("#f_url").value, raw_text: $("#f_text").value, media_url: $("#f_media").value
  }});
  closeModal(); toast("内容已新增"); renderContents();
}

async function recognize(id) {
  await api(`/api/contents/${id}/recognize`, { method: "POST", body: {} });
  toast("识别完成");
  const [route] = currentRoute();
  route === "detail" ? renderApp() : renderContents();
}

async function removeContent(id) {
  if (!confirm("确认删除该内容？")) return;
  await api(`/api/contents/${id}`, { method: "DELETE" });
  toast("已删除"); renderContents();
}

async function renderDetail(id) {
  const detail = await api(`/api/contents/${id}`);
  const c = detail.content;
  const byType = Object.fromEntries(detail.results.map(r => [r.model_type, r.result]));
  $("#view").innerHTML = `
    <div class="detail-head">
      <button class="secondary" onclick="setRoute('contents')">返回列表</button>
      <div class="actions-cell"><button onclick="recognize('${id}')">执行识别</button><button class="secondary" onclick="openReview('${id}')">人工审核</button><button class="secondary" onclick="queuePush('${id}')">加入推送队列</button></div>
    </div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">基础信息</h3><div class="kv">
        <b>平台</b><span>${c.platform}</span><b>内容类型</b><span>${c.content_type}</span><b>标题</b><span>${c.title}</span><b>账号</b><span>${c.account_name}</span>
        <b>原始链接</b><span>${c.content_url || "-"}</span><b>发布时间</b><span>${c.publish_time}</span><b>采集时间</b><span>${c.collect_time}</span>
      </div></div>
      <div class="panel"><h3 class="section-title">多模态融合结果</h3>${resultBox(byType.fusion, "fusion")}</div>
    </div>
    <div class="panel"><h3 class="section-title">原始内容</h3><div class="pre">${c.raw_text || "暂无文本"}\n${c.media_url ? "媒体地址：" + c.media_url : ""}</div>${mediaPreview(c.media_url)}</div>
    <div class="grid-3">
      <div class="panel"><h3 class="section-title">文本识别结果</h3>${resultBox(byType.text)}</div>
      <div class="panel"><h3 class="section-title">图像识别结果</h3>${resultBox(byType.image)}</div>
      <div class="panel"><h3 class="section-title">语音识别结果</h3>${resultBox(byType.audio)}</div>
    </div>
    <div class="grid-2">
      <div class="panel"><h3 class="section-title">审核记录</h3>${simpleList(detail.reviews, r => `${statusText(r.review_status)}｜${r.reviewer}｜${r.review_time}<br>${r.review_opinion || ""}`)}</div>
      <div class="panel"><h3 class="section-title">推送日志</h3>${simpleList(detail.push_logs, r => `${statusText(r.push_status)}｜${r.report_id || "-"}｜重试 ${r.retry_count}<br>${r.error_message || r.push_time || ""}`)}</div>
    </div>
  `;
}

function mediaPreview(mediaUrl) {
  if (!mediaUrl) return "";
  if (/^https?:\/\//.test(mediaUrl) || /\.(jpg|jpeg|png|webp|bmp)$/i.test(mediaUrl)) {
    return `<div class="media-preview"><img src="${mediaUrl}" alt="媒体预览" onerror="this.parentElement.style.display='none'"></div>`;
  }
  return "";
}

function resultBox(obj, type) {
  if (!obj) return `<div class="result-box pre">暂无结果，请先执行识别。</div>`;
  if (type === "fusion") {
    return `<div class="result-box pre">综合风险分：${obj.risk_score}\n风险等级：${obj.risk_level}\n命中模态：${(obj.hit_modalities || []).join("、") || "-"}\n违规类型：${(obj.violation_type || []).join("、")}\n系统解释：${obj.model_explanation}\n建议动作：${obj.review_suggestion}\n模型版本：${obj.model_version}</div>`;
  }
  return `<div class="result-box pre">${JSON.stringify(obj, null, 2)}</div>`;
}

function simpleList(rows, render) {
  return rows.length ? rows.map(r => `<div class="result-box" style="margin-bottom:8px">${render(r)}</div>`).join("") : `<div class="pre">暂无记录</div>`;
}

function openReview(id) {
  openModal(`
    <h3>人工审核</h3>
    <div class="form-grid">
      <label><span>审核动作</span><select id="review_status"><option value="confirmed">确认为违法线索</option><option value="false_positive">标记为误报</option><option value="observing">暂存观察</option><option value="ignored">忽略</option></select></label>
      <label><span>审核人</span><input id="reviewer" value="监管审核员" /></label>
      <label class="full"><span>审核意见</span><textarea id="review_opinion">命中交易引流表达，建议形成线索。</textarea></label>
    </div>
    <div class="dialog-actions"><button class="secondary" onclick="closeModal()">取消</button><button onclick="saveReview('${id}')">提交审核</button></div>
  `);
}

async function saveReview(id) {
  await api(`/api/contents/${id}/review`, { method: "POST", body: { review_status: $("#review_status").value, reviewer: $("#reviewer").value, review_opinion: $("#review_opinion").value } });
  closeModal(); toast("审核已提交"); renderApp();
}

async function queuePush(id) {
  await api(`/api/contents/${id}/push-queue`, { method: "POST", body: {} });
  toast("已加入推送队列");
  renderApp();
}

async function renderModels() {
  const rows = await api("/api/models");
  $("#view").innerHTML = `<div class="table-wrap"><table><thead><tr><th>模型编号</th><th>名称</th><th>类型</th><th>版本</th><th>接口</th><th>阈值</th><th>超时</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${r.model_name}</td><td>${r.model_type}</td><td>${r.model_version}</td><td>${r.endpoint}</td><td>${r.threshold}</td><td>${r.timeout}s</td><td>${r.enabled ? statusTag("enabled") : statusTag("disabled")}</td><td><button class="secondary" onclick='editModel(${JSON.stringify(r)})'>编辑</button></td></tr>`).join("")}</tbody></table></div>`;
}

function editModel(r) {
  openModal(`<h3>编辑模型配置</h3><div class="form-grid">
    <label><span>模型名称</span><input id="m_name" value="${r.model_name}"></label><label><span>版本</span><input id="m_ver" value="${r.model_version}"></label>
    <label class="full"><span>接口地址</span><input id="m_endpoint" value="${r.endpoint}"></label><label><span>阈值</span><input id="m_threshold" type="number" step="0.01" value="${r.threshold}"></label>
    <label><span>超时秒数</span><input id="m_timeout" type="number" value="${r.timeout}"></label><label><span>启用</span><select id="m_enabled"><option value="1">启用</option><option value="0">停用</option></select></label>
    <label class="full"><span>说明</span><textarea id="m_desc">${r.description || ""}</textarea></label>
  </div><div class="dialog-actions"><button class="secondary" onclick="closeModal()">取消</button><button onclick="saveModel('${r.id}')">保存</button></div>`);
  $("#m_enabled").value = String(r.enabled);
}

async function saveModel(id) {
  await api(`/api/models/${id}`, { method: "PUT", body: { model_name: $("#m_name").value, model_version: $("#m_ver").value, endpoint: $("#m_endpoint").value, threshold: Number($("#m_threshold").value), timeout: Number($("#m_timeout").value), enabled: Number($("#m_enabled").value), description: $("#m_desc").value } });
  closeModal(); toast("模型配置已保存"); renderModels();
}

async function renderFusion() {
  const c = await api("/api/fusion-config");
  const fields = ["text_weight", "image_weight", "audio_weight", "account_weight", "high_risk_threshold", "medium_risk_threshold", "low_risk_threshold"];
  $("#view").innerHTML = `<div class="panel"><h3 class="section-title">融合公式</h3><p class="pre">综合风险分 = 文本风险分 × 文本权重 + 图像风险分 × 图像权重 + 语音风险分 × 语音权重 + 账号行为分 × 账号权重</p></div>
    <div class="panel"><div class="form-grid">${fields.map(f => `<label><span>${f}</span><input id="${f}" type="number" step="0.01" value="${c[f]}"></label>`).join("")}</div><div class="dialog-actions"><button onclick="saveFusion()">保存配置</button></div></div>`;
}

async function saveFusion() {
  const fields = ["text_weight", "image_weight", "audio_weight", "account_weight", "high_risk_threshold", "medium_risk_threshold", "low_risk_threshold"];
  await api("/api/fusion-config", { method: "PUT", body: Object.fromEntries(fields.map(f => [f, Number($("#" + f).value)])) });
  toast("融合配置已保存");
}

async function renderRules() {
  const rows = await api("/api/rules");
  $("#view").innerHTML = `<div class="toolbar"><div><label><span>词库类型</span><select id="ruleFilter"><option value="">全部</option><option value="keyword">关键词</option><option value="blackword">黑话</option><option value="brand">品牌词</option><option value="whitelist">白名单</option><option value="region">地域词</option></select></label></div><div class="actions"><button onclick="filterRules()">查询</button><button class="secondary" onclick="openRuleForm()">新增词条</button></div></div><div class="table-wrap">${rulesTable(rows)}</div>`;
}

function rulesTable(rows) {
  return `<table><thead><tr><th>编号</th><th>类型</th><th>词条</th><th>权重</th><th>状态</th><th>备注</th><th>操作</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${r.rule_type}</td><td>${r.word}</td><td>${r.risk_weight}</td><td>${r.enabled ? "启用" : "停用"}</td><td>${r.remark || ""}</td><td class="actions-cell"><button class="secondary" onclick='openRuleForm(${JSON.stringify(r)})'>编辑</button><button class="danger" onclick="deleteRule('${r.id}')">删除</button></td></tr>`).join("")}</tbody></table>`;
}

async function filterRules() {
  const type = $("#ruleFilter").value;
  const rows = await api(`/api/rules${type ? "?rule_type=" + type : ""}`);
  $(".table-wrap").innerHTML = rulesTable(rows);
}

function openRuleForm(r = {}) {
  openModal(`<h3>${r.id ? "编辑" : "新增"}词条</h3><div class="form-grid">
    <label><span>类型</span><select id="r_type"><option value="keyword">关键词</option><option value="blackword">黑话</option><option value="brand">品牌词</option><option value="whitelist">白名单</option><option value="region">地域词</option></select></label>
    <label><span>词条</span><input id="r_word" value="${r.word || ""}"></label>
    <label><span>权重</span><input id="r_weight" type="number" step="0.01" value="${r.risk_weight ?? 0.1}"></label>
    <label><span>启用</span><select id="r_enabled"><option value="1">启用</option><option value="0">停用</option></select></label>
    <label class="full"><span>备注</span><textarea id="r_remark">${r.remark || ""}</textarea></label>
  </div><div class="dialog-actions"><button class="secondary" onclick="closeModal()">取消</button><button onclick="saveRule('${r.id || ""}')">保存</button></div>`);
  $("#r_type").value = r.rule_type || "keyword";
  $("#r_enabled").value = String(r.enabled ?? 1);
}

async function saveRule(id) {
  const body = { rule_type: $("#r_type").value, word: $("#r_word").value, risk_weight: Number($("#r_weight").value), enabled: Number($("#r_enabled").value), remark: $("#r_remark").value };
  await api(id ? `/api/rules/${id}` : "/api/rules", { method: id ? "PUT" : "POST", body });
  closeModal(); toast("词条已保存"); renderRules();
}

async function deleteRule(id) {
  if (!confirm("确认删除词条？")) return;
  await api(`/api/rules/${id}`, { method: "DELETE" });
  toast("词条已删除"); renderRules();
}

async function renderReviews() {
  const rows = await api("/api/reviews");
  $("#view").innerHTML = `<div class="table-wrap"><table><thead><tr><th>内容编号</th><th>平台</th><th>标题</th><th>风险分</th><th>风险等级</th><th>审核状态</th><th>审核人</th><th>审核时间</th><th>操作</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.content_id}</td><td>${r.platform}</td><td>${r.title}</td><td>${Number(r.risk_score || 0).toFixed(2)}</td><td>${riskTag(r.risk_level)}</td><td>${statusTag(r.review_status)}</td><td>${r.reviewer || "-"}</td><td>${r.review_time || "-"}</td><td class="actions-cell"><button class="secondary" onclick="setRoute('detail/${r.content_id}')">查看</button><button onclick="openReview('${r.content_id}')">审核</button></td></tr>`).join("")}</tbody></table></div>`;
}

async function renderPush() {
  const rows = await api("/api/push");
  $("#view").innerHTML = `<div class="table-wrap"><table><thead><tr><th>推送编号</th><th>内容编号</th><th>标题</th><th>风险等级</th><th>报告编号</th><th>状态</th><th>推送时间</th><th>重试</th><th>错误</th><th>操作</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${r.content_id}</td><td>${r.title || ""}</td><td>${riskTag(r.risk_level)}</td><td>${r.report_id || "-"}</td><td>${statusTag(r.push_status)}</td><td>${r.push_time || "-"}</td><td>${r.retry_count}</td><td>${r.error_message || ""}</td><td><button onclick="sendPush('${r.id}')">推送监管平台</button></td></tr>`).join("")}</tbody></table></div>
    <div class="panel"><h3 class="section-title">说明</h3><p class="pre">在内容详情页或审核后可将确认线索加入推送队列。本页调用 Mock 监管平台接口，随机返回推送成功或超时失败，失败记录可再次重试。</p></div>`;
}

async function sendPush(id) {
  await api(`/api/push/${id}/send`, { method: "POST", body: {} });
  toast("推送动作已完成"); renderPush();
}

function renderUsers() {
  $("#view").innerHTML = `<div class="grid-3">
    ${[
      ["系统管理员", "维护模型配置、融合规则、词库和用户角色。"],
      ["监管审核员", "处理待审核线索，确认违法、误报、观察或忽略。"],
      ["线索推送员", "维护推送队列，模拟推送监管平台并查看日志。"],
    ].map(([name, desc]) => `<div class="card"><div class="metric-label">角色</div><div class="metric-value" style="font-size:20px">${name}</div><p>${desc}</p></div>`).join("")}
  </div>`;
}

async function renderApp() {
  const [route, id] = currentRoute();
  updateChrome(route);
  try {
    if (route === "dashboard") await renderDashboard();
    else if (route === "contents") await renderContents();
    else if (route === "image-test") await renderImageTest();
    else if (route === "text-test") await renderTextTest();
    else if (route === "audio-test") await renderAudioTest();
    else if (route === "detail") await renderDetail(id);
    else if (route === "models") await renderModels();
    else if (route === "fusion") await renderFusion();
    else if (route === "rules") await renderRules();
    else if (route === "reviews") await renderReviews();
    else if (route === "push") await renderPush();
    else if (route === "users") renderUsers();
    else setRoute("dashboard");
  } catch (err) {
    $("#view").innerHTML = `<div class="panel pre">加载失败：${err.message}</div>`;
  }
}

window.addEventListener("hashchange", renderApp);
renderNav();
renderApp();
