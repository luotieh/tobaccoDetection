const state = { route: "dashboard", data: null };

const menus = [
  ["核心功能", [["dashboard", "工作台"], ["contents", "识别内容列表"], ["image-test", "图像识别测试"], ["text-test", "文本识别测试"], ["audio-test", "语音识别测试"]]],
  ["配置管理", [["models", "模型配置"], ["text-llm", "LLM 文本配置"], ["fusion", "多模态融合配置"], ["rules", "规则词库"]]],
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
  "text-llm": ["LLM 文本配置", "配置文本语义识别引擎与本地大模型参数"],
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

const contentsState = { page: 1, page_size: 20, total: 0 };

function contentsQuery() {
  const params = new URLSearchParams();
  if ($("#kw")?.value) params.set("keyword", $("#kw").value);
  if ($("#platform")?.value) params.set("platform", $("#platform").value);
  if ($("#ctype")?.value) params.set("content_type", $("#ctype").value);
  if ($("#risk")?.value) params.set("risk_level", $("#risk").value);
  params.set("page", contentsState.page);
  params.set("page_size", contentsState.page_size);
  return params;
}

async function loadContents() {
  const data = await api(`/api/contents?${contentsQuery().toString()}`);
  contentsState.total = data.total;
  contentsState.page = data.page;
  contentsState.page_size = data.page_size;
  const wrap = $(".table-wrap");
  if (wrap) wrap.innerHTML = contentsTable(data.items) + contentsPager();
  return data;
}

// 合并默认项与数据库实际取值（去重保序），保证拼音/中文等真实平台值都能被筛选
function facetOptions(defaults, actual) {
  const seen = new Set();
  const out = [];
  for (const v of [...defaults, ...(actual || [])]) {
    if (v && !seen.has(v)) { seen.add(v); out.push(v); }
  }
  return ['<option value="">全部</option>', ...out.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`)].join("");
}

async function renderContents() {
  contentsState.page = 1;
  let facets = { platforms: [], content_types: [] };
  try { facets = await api("/api/content-facets"); } catch (e) { /* 退回仅默认项 */ }
  const platformOpts = facetOptions(["抖音", "快手", "小红书", "微博"], facets.platforms);
  const ctypeOpts = facetOptions(["视频", "音频", "图片", "文本", "评论", "账号"], facets.content_types);
  $("#view").innerHTML = `
    <div class="toolbar">
      <div><label><span>关键词</span><input id="kw" placeholder="标题/账号/正文" /></label></div>
      <div><label><span>平台</span><select id="platform">${platformOpts}</select></label></div>
      <div><label><span>内容类型</span><select id="ctype">${ctypeOpts}</select></label></div>
      <div><label><span>风险等级</span><select id="risk"><option value="">全部</option><option>高风险</option><option>中风险</option><option>低风险</option><option>无风险</option></select></label></div>
      <div class="actions"><button onclick="filterContents()">查询</button><button class="secondary" onclick="openContentForm()">新增内容</button><button class="secondary" id="rerecogBtn" onclick="rerecognizeAll()">重新识别全部</button></div>
    </div>
    <div class="table-wrap"></div>
  `;
  await loadContents();
  pollRerecognize(false);
}

async function rerecognizeAll() {
  if (!confirm("将对全部内容重新识别（刷新帖子风险与评论风险分；已人工审核的状态会保留）。确定？")) return;
  try {
    const res = await api("/api/contents/recognize-all", { method: "POST", body: {} });
    toast(res.message || "已开始重识别");
    pollRerecognize(true);
  } catch (e) { toast("启动失败：" + e.message); }
}

async function pollRerecognize(announceDone) {
  let data;
  try { data = await api("/api/contents/recognize-all"); } catch (e) { return; }
  const s = data.state || {};
  const btn = $("#rerecogBtn");
  if (s.running) {
    if (btn) { btn.disabled = true; btn.textContent = `重识别中 ${s.done}/${s.total}`; }
    setTimeout(() => pollRerecognize(true), 3000);
  } else {
    if (btn) { btn.disabled = false; btn.textContent = "重新识别全部"; }
    if (announceDone && s.total) {
      toast(`重识别完成 ${s.done}/${s.total}${s.failed ? `，失败 ${s.failed}` : ""}`);
      if (currentRoute()[0] === "contents") loadContents();
    }
  }
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
      <td>${r.id}</td><td>${escapeHtml(r.platform)}</td><td>${escapeHtml(r.content_type)}</td><td class="title-cell" title="${escapeHtml(r.title || "")}">${escapeHtml(r.title || "")}</td><td>${escapeHtml(r.account_name)}</td><td>${escapeHtml(r.collect_time)}</td>
      <td>${statusTag(r.recognize_status)}</td><td>${riskTag(r.risk_level)} ${Number(r.risk_score || 0).toFixed(2)}</td><td>${statusTag(r.review_status)}</td>
      <td class="actions-cell">
        <button class="secondary" onclick="setRoute('detail/${r.id}')">查看</button>
        <button onclick="recognize('${r.id}')">识别</button>
        <button class="danger" onclick="removeContent('${r.id}')">删除</button>
      </td>
    </tr>`).join("")}</tbody>
  </table>`;
}

// 通用分页条：state 含 {page,page_size,total}，gotoName/sizeName 为全局翻页函数名
function pagerHtml(state, gotoName, sizeName) {
  const { page, page_size, total } = state;
  const pages = Math.max(1, Math.ceil(total / page_size));
  const start = total ? (page - 1) * page_size + 1 : 0;
  const end = Math.min(total, page * page_size);
  return `<div class="pager">
    <span class="pager-info">共 ${total} 条，第 ${start}-${end} 条 / 第 ${page}/${pages} 页</span>
    <span class="pager-ctrl">
      <button class="secondary" onclick="${gotoName}(1)" ${page <= 1 ? "disabled" : ""}>首页</button>
      <button class="secondary" onclick="${gotoName}(${page - 1})" ${page <= 1 ? "disabled" : ""}>上一页</button>
      <button class="secondary" onclick="${gotoName}(${page + 1})" ${page >= pages ? "disabled" : ""}>下一页</button>
      <button class="secondary" onclick="${gotoName}(${pages})" ${page >= pages ? "disabled" : ""}>末页</button>
      <label class="pager-size"><span>每页</span>
        <select onchange="${sizeName}(this.value)">
          ${[10, 20, 50, 100].map(n => `<option value="${n}" ${n === page_size ? "selected" : ""}>${n}</option>`).join("")}
        </select>
      </label>
    </span>
  </div>`;
}

function contentsPager() {
  return pagerHtml(contentsState, "gotoContentsPage", "changeContentsPageSize");
}

async function gotoContentsPage(page) {
  const pages = Math.max(1, Math.ceil(contentsState.total / contentsState.page_size));
  contentsState.page = Math.max(1, Math.min(pages, page));
  await loadContents();
}

async function changeContentsPageSize(size) {
  contentsState.page_size = Number(size) || 20;
  contentsState.page = 1;
  await loadContents();
}

async function filterContents() {
  contentsState.page = 1;
  await loadContents();
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
      <label><span>内容类型</span><select id="f_type"><option>视频</option><option>音频</option><option>图片</option><option>文本</option><option>评论</option><option>账号</option></select></label>
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
    <div class="detail-layout">
      <aside class="phone-column">
        ${phonePostPreview(c, byType, detail.comments || [])}
      </aside>
      <div class="detail-main">
        <div class="grid-2">
          <div class="panel"><h3 class="section-title">基础信息</h3><div class="kv">
            <b>平台</b><span>${escapeHtml(c.platform)}</span><b>内容类型</b><span>${escapeHtml(c.content_type)}</span><b>标题</b><span>${escapeHtml(c.title)}</span><b>账号</b><span>${escapeHtml(c.account_name)}</span>
            <b>原始链接</b><span>${escapeHtml(c.content_url || "-")}</span><b>发布时间</b><span>${escapeHtml(c.publish_time)}</span><b>采集时间</b><span>${escapeHtml(c.collect_time)}</span>
          </div></div>
          <div class="panel"><h3 class="section-title">多模态融合结果</h3>${resultBox(byType.fusion, "fusion")}</div>
        </div>
        <div class="grid-3">
          <div class="panel"><h3 class="section-title">文本识别结果</h3>${resultBox(byType.text)}</div>
          <div class="panel"><h3 class="section-title">图像识别结果</h3>${resultBox(byType.image)}</div>
          <div class="panel"><h3 class="section-title">语音识别结果</h3>${resultBox(byType.audio)}</div>
        </div>
        <div class="grid-2">
          <div class="panel"><h3 class="section-title">审核记录</h3>${simpleList(detail.reviews, r => `${statusText(r.review_status)}｜${escapeHtml(r.reviewer)}｜${escapeHtml(r.review_time)}<br>${escapeHtml(r.review_opinion || "")}`)}</div>
          <div class="panel"><h3 class="section-title">推送日志</h3>${simpleList(detail.push_logs, r => `${statusText(r.push_status)}｜${escapeHtml(r.report_id || "-")}｜重试 ${r.retry_count}<br>${escapeHtml(r.error_message || r.push_time || "")}`)}</div>
        </div>
      </div>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
}

function phonePostPreview(c, byType, comments = []) {
  const transcript = byType.audio?.transcript || "";
  const ocrText = (byType.image?.ocr_text || []).join(" ");
  const author = c.author || {};
  const authorName = c.account_name || author.nickname || author.id || "未知账号";
  const authorDesc = author.description || "";
  const mediaItems = phoneMediaItems(c, byType);
  const nestedComments = nestPhoneComments(comments);
  const totalComments = comments.length;
  const replyCount = comments.filter(item => item.comment_type === "sub_comment").length;
  return `
    <div class="phone-shell">
      <div class="phone-island"></div>
      <div class="phone-screen crawler-phone-screen">
        <div class="phone-status"><span>09:41</span><span>5G 100%</span></div>
        <div class="crawler-phone-header">
          <button class="crawler-back" type="button" aria-label="返回">‹</button>
          <strong>${escapeHtml(c.title || "内容详情")}</strong>
          <span></span>
        </div>
        <article class="crawler-detail-card">
          <div class="crawler-chip-row">
            ${phoneCrawlerBadge(c.platform, "platform")}
            ${phoneCrawlerBadge(c.crawler_type || c.content_type, "type", crawlerTypeLabel(c))}
            ${riskTag(c.risk_level)}
          </div>
          <header class="crawler-author">
            ${phoneAvatar(author.avatarUrl, authorName)}
            <div>
              <strong>${escapeHtml(authorName)}</strong>
              ${authorDesc ? `<span>${escapeHtml(authorDesc)}</span>` : `<span>${escapeHtml(c.publish_time || c.collect_time || "-")}</span>`}
            </div>
          </header>
          ${c.title ? `<section class="crawler-section"><b>标题</b><h3>${escapeHtml(c.title)}</h3></section>` : ""}
          <section class="crawler-section">
            <b>${c.content_type === "视频" ? "简介" : "内容"}</b>
            <p class="crawler-text">${escapeHtml(c.raw_text || "暂无正文内容")}</p>
          </section>
          <div class="crawler-meta-grid">
            <div><b>发布日期</b><span>${escapeHtml(c.publish_time || "-")}</span></div>
            <div><b>采集时间</b><span>${escapeHtml(c.collect_time || "-")}</span></div>
          </div>
          ${c.content_url ? `<a class="crawler-link" href="${escapeHtml(c.content_url)}" target="_blank" rel="noreferrer">查看原文</a>` : ""}
          ${phoneMedia(c, byType, mediaItems)}
          ${transcript ? `<div class="crawler-evidence"><b>语音转写</b><span>${escapeHtml(transcript)}</span></div>` : ""}
          ${ocrText ? `<div class="crawler-evidence"><b>画面文字</b><span>${escapeHtml(ocrText)}</span></div>` : ""}
          <section class="crawler-comments">
            <div class="crawler-comments-title">
              <span>评论</span>
              <em>${totalComments} 条评论（${nestedComments.length} 条一级，${replyCount} 条回复）</em>
            </div>
            ${nestedComments.length ? nestedComments.map(comment => phoneCommentNode(comment)).join("") : `<p class="crawler-empty-text">暂无评论</p>`}
          </section>
        </article>
      </div>
    </div>
  `;
}

function crawlerTypeLabel(c) {
  const typ = String(c.crawler_type || "").toLowerCase();
  if (typ === "video") return "视频";
  if (typ === "note") return "图文";
  return c.content_type || "内容";
}

function phoneCrawlerBadge(value, kind, label) {
  const text = label || value || "-";
  const cls = kind === "platform" ? platformBadgeClass(value) : "crawler-badge-type";
  return `<span class="crawler-badge ${cls}">${escapeHtml(text)}</span>`;
}

function platformBadgeClass(platform) {
  if (platform === "抖音") return "crawler-badge-douyin";
  if (platform === "快手") return "crawler-badge-kuaishou";
  if (platform === "小红书") return "crawler-badge-redbook";
  if (platform === "微博") return "crawler-badge-weibo";
  return "crawler-badge-default";
}

function phoneAvatar(url, name) {
  const fallback = escapeHtml((name || "?").slice(0, 1));
  if (!url) return `<div class="crawler-avatar">${fallback}</div>`;
  return `<span class="crawler-avatar crawler-avatar-image"><img src="${escapeHtml(url)}" alt="" onerror="this.parentElement.classList.add('avatar-failed');"><em>${fallback}</em></span>`;
}

function phoneMediaItems(c, byType = {}) {
  const parsed = Array.isArray(c.media_list_parsed) ? c.media_list_parsed : [];
  const media = parsed.length ? parsed : [c.media_preview_url || c.media_url].filter(Boolean);
  const fallback = evidenceImageUrl(byType);
  if (!media.length && fallback) return [fallback];
  return media;
}

function platformTone(platform) {
  if (platform === "抖音") return "tone-douyin";
  if (platform === "快手") return "tone-kuaishou";
  if (platform === "小红书") return "tone-redbook";
  if (platform === "微博") return "tone-weibo";
  return "tone-default";
}

function postMetric(seed, min, max) {
  const text = String(seed || "");
  const sum = [...text].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
  return min + (sum % Math.max(1, max - min + 1));
}

function evidenceImageUrl(byType) {
  const frame = byType.image?.visual_service_result?.evidence_frames?.[0]?.image_path;
  return frame ? "/" + String(frame).replace(/^\/+/, "") : "";
}

function phoneMedia(c, byType = {}, mediaItems = null) {
  const mediaList = mediaItems || phoneMediaItems(c, byType);
  const type = c.content_type || "";
  const fallbackImage = evidenceImageUrl(byType);
  if (!mediaList.length) {
    return `<div class="crawler-section"><b>媒体</b><div class="crawler-media-empty">无媒体内容</div></div>`;
  }
  if (type === "视频" || mediaList.some(url => /\.(mp4|mov|avi|mkv|webm)$/i.test(url))) {
    const mediaUrl = mediaList.find(url => /\.(mp4|mov|avi|mkv|webm)$/i.test(url)) || mediaList[0];
    const safeUrl = escapeHtml(mediaUrl);
    const fallbackAttr = fallbackImage ? ` data-fallback="${escapeHtml(fallbackImage)}"` : "";
    return `<div class="crawler-section"><b>视频</b><div class="crawler-video"><video src="${safeUrl}"${fallbackAttr} controls muted playsinline onerror="swapPhoneVideoFallback(this);"></video></div></div>`;
  }
  if (type === "音频" || mediaList.some(url => /\.(wav|mp3|m4a|aac|flac|ogg)$/i.test(url))) {
    const mediaUrl = mediaList.find(url => /\.(wav|mp3|m4a|aac|flac|ogg)$/i.test(url)) || mediaList[0];
    const safeUrl = escapeHtml(mediaUrl);
    return `<div class="crawler-section"><b>音频</b><div class="phone-media audio">
      <div class="audio-art"><span></span></div>
      <audio src="${safeUrl}" controls preload="metadata"></audio>
      <span>${escapeHtml((c.media_url || mediaUrl).split("/").pop() || "音频内容")}</span>
    </div></div>`;
  }
  const images = mediaList.filter(url => /^https?:\/\//.test(url) || /\.(jpg|jpeg|png|webp|bmp|gif)$/i.test(url));
  if (images.length) {
    return `<div class="crawler-section"><b>图片</b><div class="crawler-media-grid ${images.length === 1 ? "single" : ""}">
      ${images.slice(0, 9).map((url, index) => `<img src="${escapeHtml(url)}" alt="图片 ${index + 1}" loading="lazy" onerror="this.classList.add('failed-img');">`).join("")}
    </div></div>`;
  }
  return `<div class="crawler-section"><b>媒体</b><div class="crawler-media-empty">${mediaList.map(escapeHtml).join("<br>")}</div></div>`;
}

function nestPhoneComments(comments = []) {
  const nodes = comments.map(item => ({ ...item, replies: [] }));
  const byRawId = new Map();
  const roots = [];
  nodes.forEach(node => {
    const rawId = node.raw?.id || node.id;
    byRawId.set(rawId, node);
  });
  nodes.forEach(node => {
    const parentId = node.parent_comment_id || node.raw?.parentId || "";
    if (node.comment_type === "sub_comment" && byRawId.has(parentId)) {
      byRawId.get(parentId).replies.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

function phoneCommentNode(comment, depth = 0) {
  const sender = comment.sender || {};
  const senderName = sender.nickname || sender.id || "匿名用户";
  const rs = Number(comment.risk_score || 0);
  const scored = !!comment.risk_updated_at;
  const cls = rs >= 0.65 ? "high" : rs >= 0.4 ? "mid" : "low";
  const riskBadge = scored
    ? `<span class="comment-risk ${cls}" title="评论文本风险分；≥0.65 审核确认后反馈爬虫端">风险 ${rs.toFixed(2)}</span>`
    : `<span class="comment-risk none" title="尚未打分，重新识别后生成">未打分</span>`;
  return `
    <div class="crawler-comment ${depth ? "reply" : ""}">
      ${phoneAvatar(sender.avatarUrl, senderName)}
      <div class="crawler-comment-body">
        <div class="crawler-comment-meta">
          <strong>${escapeHtml(senderName)}</strong>
          <span>${escapeHtml(comment.date || "-")}</span>
          ${riskBadge}
        </div>
        <p>${escapeHtml(comment.content || "")}</p>
        ${comment.replies?.length ? `<div class="crawler-replies">${comment.replies.map(reply => phoneCommentNode(reply, depth + 1)).join("")}</div>` : ""}
      </div>
    </div>
  `;
}

function swapPhoneImageFallback(img) {
  const fallback = img.dataset.fallback;
  if (fallback && img.src !== fallback) {
    img.removeAttribute("data-fallback");
    img.src = fallback;
    return;
  }
  img.parentElement.classList.add("failed");
  img.remove();
}

function swapPhoneVideoFallback(video) {
  const fallback = video.dataset.fallback;
  if (fallback) {
    video.parentElement.innerHTML = `<img src="${fallback}" alt="视频证据帧">`;
    return;
  }
  video.parentElement.classList.add("failed");
  video.remove();
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
    <tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${escapeHtml(r.model_name)}</td><td>${escapeHtml(r.model_type)}</td><td>${escapeHtml(r.model_version)}</td><td>${escapeHtml(r.endpoint)}</td><td>${r.threshold}</td><td>${r.timeout}s</td><td>${r.enabled ? statusTag("enabled") : statusTag("disabled")}</td><td><button class="secondary" onclick='editModel(${escapeHtml(JSON.stringify(r))})'>编辑</button></td></tr>`).join("")}</tbody></table></div>`;
}

function editModel(r) {
  openModal(`<h3>编辑模型配置</h3><div class="form-grid">
    <label><span>模型名称</span><input id="m_name" value="${escapeHtml(r.model_name)}"></label><label><span>版本</span><input id="m_ver" value="${escapeHtml(r.model_version)}"></label>
    <label class="full"><span>接口地址</span><input id="m_endpoint" value="${escapeHtml(r.endpoint)}"></label><label><span>阈值</span><input id="m_threshold" type="number" step="0.01" value="${r.threshold}"></label>
    <label><span>超时秒数</span><input id="m_timeout" type="number" value="${r.timeout}"></label><label><span>启用</span><select id="m_enabled"><option value="1">启用</option><option value="0">停用</option></select></label>
    <label class="full"><span>说明</span><textarea id="m_desc">${escapeHtml(r.description || "")}</textarea></label>
  </div><div class="dialog-actions"><button class="secondary" onclick="closeModal()">取消</button><button onclick="saveModel('${r.id}')">保存</button></div>`);
  $("#m_enabled").value = String(r.enabled);
}

async function saveModel(id) {
  await api(`/api/models/${id}`, { method: "PUT", body: { model_name: $("#m_name").value, model_version: $("#m_ver").value, endpoint: $("#m_endpoint").value, threshold: Number($("#m_threshold").value), timeout: Number($("#m_timeout").value), enabled: Number($("#m_enabled").value), description: $("#m_desc").value } });
  closeModal(); toast("模型配置已保存"); renderModels();
}

function textServiceStatusPanel(status) {
  if (!status) {
    return `<div class="panel"><h3 class="section-title">运行状态 <span class="tag red">不可用</span></h3><p class="pre">无法读取文本服务状态，请确认服务地址和进程。</p></div>`;
  }
  const semantic = status.models?.semantic_model || {};
  const health = status.health || {};
  return `<div class="panel">
    <h3 class="section-title">运行状态 <span class="tag ${health.status === "ok" ? "green" : "orange"}">${health.status || "unknown"}</span></h3>
    <div class="kv">
      <b>服务地址</b><span>${status.base_url || "-"}</span>
      <b>当前引擎</b><span>${semantic.engine || "-"}</span>
      <b>当前来源</b><span>${semantic.provider || (semantic.engine === "mock" ? "旧有文本识别服务" : "-")}</span>
      <b>Mock 模式</b><span>${semantic.mock ? "是" : "否"}</span>
      <b>加载错误</b><span>${semantic.error || "-"}</span>
    </div>
  </div>`;
}

async function renderTextLlmConfig() {
  let config = null;
  let configError = "";
  try {
    config = await api("/api/text-llm-config");
  } catch (err) {
    configError = err.message;
    config = {
      saved: {
        semantic_engine: "mock",
        use_mock_model: 1,
        transformer_model_dir: "text_models/text-risk-model",
        llm_provider: "local",
        llm_model_dir: "text_models/qwen2.5-0.5b-instruct",
        llm_api_base_url: "",
        llm_api_key_set: false,
        llm_api_key_masked: "",
        llm_api_model: "",
        llm_max_new_tokens: 256,
        llm_temperature: 0,
        llm_timeout_seconds: 10,
        max_text_length: 512,
      },
      runtime_env: {},
      text_service_url: "",
    };
  }
  let status = null;
  try {
    status = await api("/api/text-service/status");
  } catch (err) {
    status = null;
  }
  const c = config.saved;
  const savedMode = c.semantic_engine === "llm" && c.llm_provider === "openai_compatible" ? "llm-api" : "legacy";
  const running = status?.models?.semantic_model || {};
  const runningMode = running.engine === "llm" && running.provider === "openai_compatible" ? "llm-api" : "legacy";
  $("#view").innerHTML = `
    ${configError ? `<div class="panel pre">配置接口暂不可用：${escapeHtml(configError)}。请部署并重启管理端后再切换。</div>` : ""}
    <div class="panel">
      <h3 class="section-title">文本识别服务切换</h3>
      <div class="table-wrap"><table>
        <thead><tr><th>配置</th><th>用途</th><th>保存状态</th><th>运行状态</th><th>操作</th></tr></thead>
        <tbody>
          <tr>
            <td><b>旧有文本识别服务</b></td>
            <td>规则词库、实体抽取和现有 mock/规则语义识别。</td>
            <td>${savedMode === "legacy" ? `<span class="tag green">已保存</span>` : `<span class="tag gray">未选择</span>`}</td>
            <td>${runningMode === "legacy" ? `<span class="tag green">运行中</span>` : `<span class="tag gray">未运行</span>`}</td>
            <td><button onclick="switchTextService('legacy')">切换到旧有服务</button></td>
          </tr>
          <tr>
            <td><b>LLM 第三方 API</b></td>
            <td>
              <div class="form-grid">
                <label class="full"><span>API Base URL</span><input id="llm_api_base_url" placeholder="https://api.example.com/v1" value="${c.llm_api_base_url || ""}"></label>
                <label><span>模型名</span><input id="llm_api_model" placeholder="deepseek-chat" value="${c.llm_api_model || ""}"></label>
                <label><span>API Key</span><input id="llm_api_key" type="password" autocomplete="off" placeholder="${c.llm_api_key_set ? `已保存：${c.llm_api_key_masked}` : "sk-..."}"></label>
              </div>
            </td>
            <td>${savedMode === "llm-api" ? `<span class="tag green">已保存</span>` : `<span class="tag gray">未选择</span>`}<br>${c.llm_api_key_set ? `<span class="tag green">Key 已保存</span>` : `<span class="tag orange">Key 未保存</span>`}</td>
            <td>${runningMode === "llm-api" ? `<span class="tag green">运行中</span>` : `<span class="tag gray">未运行</span>`}</td>
            <td class="actions-cell"><button class="secondary" onclick="checkTextLlmApi()">健康检查</button><button onclick="switchTextService('llm-api')">切换到 LLM API</button></td>
          </tr>
        </tbody>
      </table></div>
    </div>
    <div class="grid-2">
      ${textServiceStatusPanel(status)}
      <div class="panel"><h3 class="section-title">操作结果</h3><div id="llmActionResult" class="result-box pre">尚未操作</div></div>
    </div>`;
}

function textServiceSwitchPayload(mode) {
  const base = {
    transformer_model_dir: "text_models/text-risk-model",
    llm_model_dir: "text_models/qwen2.5-0.5b-instruct",
    llm_max_new_tokens: 256,
    llm_temperature: 0,
    llm_timeout_seconds: 10,
    max_text_length: 512,
  };
  if (mode === "llm-api") {
    return {
      ...base,
      semantic_engine: "llm",
      use_mock_model: true,
      llm_provider: "openai_compatible",
      llm_api_base_url: $("#llm_api_base_url")?.value || "",
      llm_api_key: $("#llm_api_key")?.value || "",
      llm_api_model: $("#llm_api_model")?.value || "",
    };
  }
  return {
    ...base,
    semantic_engine: "mock",
    use_mock_model: true,
    llm_provider: "local",
    llm_api_base_url: "",
    llm_api_key: "",
    llm_api_model: "",
  };
}

async function checkTextLlmApi() {
  const box = $("#llmActionResult");
  box.textContent = "检查中...";
  try {
    const result = await api("/api/text-llm-config/health-check", { method: "POST", body: textServiceSwitchPayload("llm-api") });
    box.textContent = [
      `状态：${result.ok ? "正常" : "异常"}`,
      `说明：${result.message || "-"}`,
      `Provider：${result.provider || "-"}`,
      `Endpoint：${result.endpoint || "-"}`,
      `模型：${result.model || "-"}`,
      `HTTP：${result.status_code || "-"}`,
      `延迟：${result.latency_ms != null ? result.latency_ms + "ms" : "-"}`,
      `API Key 已设置：${result.api_key_present ? "是" : "否"}`,
      `API Key 来源：${({ page_input: "页面输入", saved_config: "已保存配置", environment: "环境变量" })[result.api_key_source] || "-"}`,
      `响应摘要：${result.response_preview || "-"}`,
    ].join("\n");
  } catch (err) {
    box.textContent = `检查失败：${err.message}`;
  }
}

async function switchTextService(mode) {
  const box = $("#llmActionResult");
  box.textContent = "正在保存配置并重启文本服务...";
  try {
    const result = await api("/api/text-llm-config/apply-text-service", { method: "POST", body: textServiceSwitchPayload(mode) });
    const semantic = result.status?.models?.semantic_model || {};
    box.textContent = [
      `状态：${result.success ? "已生效" : "待确认"}`,
      `说明：${result.message || "-"}`,
      `端口：${result.port || "-"}`,
      `停止进程：${(result.stopped_pids || []).join(", ") || "-"}`,
      `启动进程：${result.started_pid || "-"}`,
      `应用引擎：${result.applied?.semantic_engine || "-"}`,
      `应用来源：${result.applied?.llm_provider || "-"}`,
      `API Key 已保存：${result.applied?.llm_api_key_set ? "是" : "否"}`,
      `运行引擎：${semantic.engine || "-"}`,
      `运行来源：${semantic.provider || "-"}`,
      `Mock 模式：${semantic.mock ? "是" : "否"}`,
      `错误：${result.error || semantic.error || "-"}`,
    ].join("\n");
    toast(result.success ? "文本服务已切换" : "文本服务切换待确认");
    setTimeout(renderTextLlmConfig, 800);
  } catch (err) {
    box.textContent = `切换失败：${err.message}`;
  }
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

const rulesState = { page: 1, page_size: 20, total: 0 };

async function loadRules() {
  const params = new URLSearchParams();
  if ($("#ruleFilter")?.value) params.set("rule_type", $("#ruleFilter").value);
  params.set("page", rulesState.page);
  params.set("page_size", rulesState.page_size);
  const data = await api(`/api/rules?${params.toString()}`);
  rulesState.total = data.total;
  rulesState.page = data.page;
  rulesState.page_size = data.page_size;
  const wrap = $(".table-wrap");
  if (wrap) wrap.innerHTML = rulesTable(data.items) + pagerHtml(rulesState, "gotoRulesPage", "changeRulesPageSize");
}

async function gotoRulesPage(page) {
  const pages = Math.max(1, Math.ceil(rulesState.total / rulesState.page_size));
  rulesState.page = Math.max(1, Math.min(pages, page));
  await loadRules();
}

async function changeRulesPageSize(size) {
  rulesState.page_size = Number(size) || 20;
  rulesState.page = 1;
  await loadRules();
}

async function renderRules() {
  rulesState.page = 1;
  $("#view").innerHTML = `<div class="toolbar"><div><label><span>词库类型</span><select id="ruleFilter"><option value="">全部</option><option value="keyword">关键词</option><option value="blackword">黑话</option><option value="brand">品牌词</option><option value="whitelist">白名单</option><option value="region">地域词</option></select></label></div><div class="actions"><button onclick="filterRules()">查询</button><button class="secondary" onclick="openRuleForm()">新增词条</button></div></div>
    <div class="panel"><h3 class="section-title">上传文件导入</h3><div class="form-grid">
      <label><span>导入类型</span><select id="ruleImportType"><option value="keyword">关键词</option><option value="blackword">黑话</option><option value="brand">品牌词</option><option value="whitelist">白名单</option><option value="region">地域词</option></select></label>
      <label class="full"><span>规则文件</span><input id="ruleImportFile" type="file" accept=".txt,.csv,.json"></label>
    </div><div class="dialog-actions"><button class="secondary" onclick="importRulesFile()">上传并识别规则</button></div><div id="ruleImportResult" class="result-box pre">支持 txt 每行一个词，csv 字段 rule_type,word,risk_weight,remark,enabled，json 数组或对象分组。</div></div>
    <div class="table-wrap"></div>`;
  await loadRules();
}

function rulesTable(rows) {
  return `<table><thead><tr><th>编号</th><th>类型</th><th>词条</th><th>权重</th><th>状态</th><th>备注</th><th>操作</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${escapeHtml(r.rule_type)}</td><td>${escapeHtml(r.word)}</td><td>${r.risk_weight}</td><td>${r.enabled ? "启用" : "停用"}</td><td>${escapeHtml(r.remark || "")}</td><td class="actions-cell"><button class="secondary" onclick='openRuleForm(${escapeHtml(JSON.stringify(r))})'>编辑</button><button class="danger" onclick="deleteRule('${r.id}')">删除</button></td></tr>`).join("")}</tbody></table>`;
}

async function filterRules() {
  rulesState.page = 1;
  await loadRules();
}

function openRuleForm(r = {}) {
  openModal(`<h3>${r.id ? "编辑" : "新增"}词条</h3><div class="form-grid">
    <label><span>类型</span><select id="r_type"><option value="keyword">关键词</option><option value="blackword">黑话</option><option value="brand">品牌词</option><option value="whitelist">白名单</option><option value="region">地域词</option></select></label>
    <label><span>词条</span><input id="r_word" value="${escapeHtml(r.word || "")}"></label>
    <label><span>权重</span><input id="r_weight" type="number" step="0.01" value="${r.risk_weight ?? 0.1}"></label>
    <label><span>启用</span><select id="r_enabled"><option value="1">启用</option><option value="0">停用</option></select></label>
    <label class="full"><span>备注</span><textarea id="r_remark">${escapeHtml(r.remark || "")}</textarea></label>
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

async function importRulesFile() {
  const file = $("#ruleImportFile").files[0];
  if (!file) {
    toast("请选择规则文件");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  form.append("rule_type", $("#ruleImportType").value || "keyword");
  $("#ruleImportResult").textContent = "导入中...";
  try {
    const result = await apiForm("/api/rules/import", form);
    $("#ruleImportResult").textContent = `解析：${result.parsed}\n新增：${result.inserted}\n跳过重复：${result.skipped}`;
    toast("规则文件导入完成");
    filterRules();
  } catch (err) {
    $("#ruleImportResult").textContent = `导入失败：${err.message}`;
  }
}

const reviewsState = { page: 1, page_size: 20, total: 0 };

function reviewsTable(rows) {
  return `<table><thead><tr><th>内容编号</th><th>平台</th><th>标题</th><th>风险分</th><th>风险等级</th><th>审核状态</th><th>审核人</th><th>审核时间</th><th>操作</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.content_id}</td><td>${escapeHtml(r.platform)}</td><td>${escapeHtml(r.title || "")}</td><td>${Number(r.risk_score || 0).toFixed(2)}</td><td>${riskTag(r.risk_level)}</td><td>${statusTag(r.review_status)}</td><td>${escapeHtml(r.reviewer || "-")}</td><td>${escapeHtml(r.review_time || "-")}</td><td class="actions-cell"><button class="secondary" onclick="setRoute('detail/${r.content_id}')">查看</button><button onclick="openReview('${r.content_id}')">审核</button></td></tr>`).join("")}</tbody></table>`;
}

async function loadReviews() {
  const data = await api(`/api/reviews?page=${reviewsState.page}&page_size=${reviewsState.page_size}`);
  reviewsState.total = data.total;
  reviewsState.page = data.page;
  reviewsState.page_size = data.page_size;
  const wrap = $(".table-wrap");
  if (wrap) wrap.innerHTML = reviewsTable(data.items) + pagerHtml(reviewsState, "gotoReviewsPage", "changeReviewsPageSize");
}

async function gotoReviewsPage(page) {
  const pages = Math.max(1, Math.ceil(reviewsState.total / reviewsState.page_size));
  reviewsState.page = Math.max(1, Math.min(pages, page));
  await loadReviews();
}

async function changeReviewsPageSize(size) {
  reviewsState.page_size = Number(size) || 20;
  reviewsState.page = 1;
  await loadReviews();
}

async function renderReviews() {
  reviewsState.page = 1;
  $("#view").innerHTML = `<div class="table-wrap"></div>`;
  await loadReviews();
}

const pushState = { page: 1, page_size: 20, total: 0 };

function pushTable(rows) {
  return `<table><thead><tr><th>推送编号</th><th>内容编号</th><th>标题</th><th>风险等级</th><th>报告编号</th><th>状态</th><th>推送时间</th><th>重试</th><th>错误</th><th>操作</th></tr></thead><tbody>${rows.map(r => `<tr><td>${r.id}</td><td>${r.content_id}</td><td>${escapeHtml(r.title || "")}</td><td>${riskTag(r.risk_level)}</td><td>${escapeHtml(r.report_id || "-")}</td><td>${statusTag(r.push_status)}</td><td>${escapeHtml(r.push_time || "-")}</td><td>${r.retry_count}</td><td>${escapeHtml(r.error_message || "")}</td><td><button onclick="sendPush('${r.id}')">推送监管平台</button></td></tr>`).join("")}</tbody></table>`;
}

async function loadPush() {
  const data = await api(`/api/push?page=${pushState.page}&page_size=${pushState.page_size}`);
  pushState.total = data.total;
  pushState.page = data.page;
  pushState.page_size = data.page_size;
  const wrap = $(".table-wrap");
  if (wrap) wrap.innerHTML = pushTable(data.items) + pagerHtml(pushState, "gotoPushPage", "changePushPageSize");
}

async function gotoPushPage(page) {
  const pages = Math.max(1, Math.ceil(pushState.total / pushState.page_size));
  pushState.page = Math.max(1, Math.min(pages, page));
  await loadPush();
}

async function changePushPageSize(size) {
  pushState.page_size = Number(size) || 20;
  pushState.page = 1;
  await loadPush();
}

async function renderPush() {
  pushState.page = 1;
  $("#view").innerHTML = `<div class="table-wrap"></div>
    <div class="panel"><h3 class="section-title">说明</h3><p class="pre">在内容详情页或审核后可将确认线索加入推送队列。本页调用 Mock 监管平台接口，随机返回推送成功或超时失败，失败记录可再次重试。</p></div>`;
  await loadPush();
}

async function sendPush(id) {
  await api(`/api/push/${id}/send`, { method: "POST", body: {} });
  toast("推送动作已完成"); await loadPush();
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
    else if (route === "text-llm") await renderTextLlmConfig();
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
