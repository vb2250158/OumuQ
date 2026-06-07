const state = {
  mode: "single",
  characters: [],
  config: null,
  busy: false,
  route: null,
};

const $ = (id) => document.getElementById(id);

function clearError() {
  $("errorBanner").classList.add("is-hidden");
  $("errorBanner").textContent = "";
}

function showError(error) {
  const message = error?.message || String(error);
  $("errorBanner").textContent = message;
  $("errorBanner").classList.remove("is-hidden");
}

function splitComma(value) {
  return value
    .split(/[,\uFF0C]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinList(value) {
  return Array.isArray(value) ? value.join(", ") : value || "";
}

function parseVector(value) {
  const parts = splitComma(value);
  if (!parts.length) return null;
  const vector = parts.map(Number);
  if (vector.some((item) => Number.isNaN(item))) {
    throw new Error("情绪向量里包含非数字内容。");
  }
  return vector;
}

function selectedCharacter() {
  const id = $("character").value;
  return state.characters.find((item) => item.id === id) || null;
}

function optionalNumber(value) {
  if (!value.trim()) return undefined;
  const number = Number(value);
  if (Number.isNaN(number)) {
    throw new Error("数值字段里包含非数字内容。");
  }
  return number;
}

function workerUrlForCharacter(character) {
  if (!character) return state.config?.default_worker_url || "";
  const engineKey = (character.tts_engine || "").toLowerCase();
  return (
    character.worker_url ||
    character.resolved_worker_url ||
    state.config?.engine_worker_urls?.[engineKey] ||
    state.config?.default_worker_url ||
    ""
  );
}

function characterName(character) {
  return character?.display_name_zh || character?.name || character?.id || "";
}

function characterSummary(character) {
  return character?.style_summary_zh || character?.style_summary || character?.character_folder || character?.id || "";
}

function statusText(status) {
  return {
    queued: "已排队",
    running: "生成中",
    done: "已完成",
    error: "错误",
    submitted: "已提交",
  }[status] || status || "已提交";
}

function requestBase() {
  const character = selectedCharacter();
  return {
    worker_url: $("workerUrl").value,
    play: $("play").checked,
    language: $("language").value || character?.speech_language || undefined,
    character_id: character?.id || undefined,
    emotion_tags: splitComma($("emotionTags").value),
    emotion_vector: parseVector($("emotionVector").value),
    emotion_mode: $("emotionMode").value || undefined,
    emotion_alpha: optionalNumber($("emotionAlpha").value),
    emotion_text: $("emotionText").value.trim() || undefined,
    match_patterns: splitComma($("matchPatterns").value),
    ref_text: $("refText").value.trim() || undefined,
    prompt_audio: $("promptAudio").value.trim() || undefined,
    prompt_audios: splitComma($("promptAudios").value),
    max_new_tokens: Number($("maxTokens").value) || undefined,
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || response.statusText);
  return data;
}

function setBusy(value) {
  state.busy = value;
  $("send").disabled = value;
  $("sendBatch").disabled = value;
}

function setChip(id, label, value, className = "") {
  const chip = $(id);
  chip.className = `status-chip ${className}`.trim();
  chip.replaceChildren();
  const span = document.createElement("span");
  span.textContent = label;
  const strong = document.createElement("strong");
  strong.textContent = value;
  chip.append(span, strong);
}

function renderCharacterDetails() {
  const character = selectedCharacter();
  const box = $("characterDetails");
  box.replaceChildren();
  if (!character) {
    box.className = "character-card is-empty";
    box.textContent = "没有角色";
    $("activeRoute").textContent = "未选择路由";
    return;
  }

  box.className = "character-card";
  const badges = document.createElement("div");
  badges.className = "badge-row";
  for (const value of [character.tts_engine, character.speech_language, character.visible_language]) {
    if (!value) continue;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = value;
    badges.appendChild(badge);
  }

  const summary = document.createElement("div");
  summary.className = "character-summary";
  summary.textContent = characterSummary(character);
  box.append(badges, summary);

  $("language").value = character.speech_language || "";
  $("workerUrl").value = workerUrlForCharacter(character);
  $("activeRoute").textContent = `${character.id} / ${character.tts_engine || "worker"} / ${
    character.speech_language || "语音语言"
  }`;
}

async function resolveHotSwitchRoute() {
  const character = selectedCharacter();
  if (!character) return;
  const data = await api("/api/route/resolve", {
    method: "POST",
    body: JSON.stringify({ ...requestBase(), text: activeText(), character_id: character.id }),
  });
  state.route = data;
  $("workerUrl").value = data.worker_url || $("workerUrl").value;
  $("activeRoute").textContent = `热切换: ${data.route_id || character.id} -> ${data.worker_url}`;
  setChip("routerStatus", "路由", "热切换就绪", "is-online");
  await refreshWorkerStatus();
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("workerUrl").value = state.config.default_worker_url;
  $("registryBadge").textContent = state.config.registry_exists ? "工作区" : "示例";
  $("inferStatus").textContent = state.config.llm_inference?.configured
    ? `LLM / ${state.config.llm_inference.model}`
    : "本地启发式";
  setChip("routerStatus", "路由", "在线", "is-online");
}

async function loadCharacters() {
  const data = await api("/api/characters");
  state.characters = data.characters || [];
  $("character").replaceChildren();
  for (const character of state.characters) {
    const option = document.createElement("option");
    option.value = character.id;
    option.textContent = `${characterName(character)} / ${character.tts_engine || "worker"}`;
    $("character").appendChild(option);
  }
  $("characterCount").textContent = String(state.characters.length);
  renderCharacterDetails();
  await resolveHotSwitchRoute();
}

function setMode(mode) {
  state.mode = mode;
  $("singleMode").classList.toggle("is-active", mode === "single");
  $("batchMode").classList.toggle("is-active", mode === "batch");
  $("singlePane").classList.toggle("is-hidden", mode !== "single");
  $("batchPane").classList.toggle("is-hidden", mode !== "batch");
}

function updateMeta() {
  const textLength = $("text").value.length;
  const lines = $("batchText").value.split(/\r?\n/).filter((line) => line.trim()).length;
  $("textMeta").textContent = `${textLength} 字符`;
  $("batchMeta").textContent = `${lines} 行`;
}

async function sendText() {
  const text = $("text").value.trim();
  if (!text || state.busy) return;
  clearError();
  setBusy(true);
  try {
    const payload = { ...requestBase(), text };
    const data = await api("/api/speak", { method: "POST", body: JSON.stringify(payload) });
    $("text").value = "";
    updateMeta();
    prependRun(data);
    await refreshRuns();
  } finally {
    setBusy(false);
  }
}

async function sendBatch() {
  const lines = $("batchText").value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (!lines.length || state.busy) return;
  clearError();
  setBusy(true);
  try {
    const payload = { ...requestBase(), lines };
    const data = await api("/api/batch", { method: "POST", body: JSON.stringify(payload) });
    for (const job of data.jobs) prependRun(job);
    $("batchText").value = "";
    updateMeta();
    await refreshRuns();
  } finally {
    setBusy(false);
  }
}

function runFields(data) {
  const response = data.worker_response || data.response || {};
  const request = data.request?.payload || {};
  return {
    id: response.id || "本地",
    status: response.status || "submitted",
    text: response.text || request.text || "",
    output: response.output || data.run_dir || "",
    runDir: data.run_dir || "",
    workerUrl: data.request?.worker_url || "",
  };
}

async function withFreshWorkerJob(data) {
  const fields = runFields(data);
  if (!fields.workerUrl || !fields.id || fields.id === "本地") return data;
  if (["done", "error", "missing"].includes(fields.status)) return data;

  try {
    const workerUrl = encodeURIComponent(fields.workerUrl);
    const job = await api(`/api/worker/status/${encodeURIComponent(fields.id)}?worker_url=${workerUrl}`);
    if (data.worker_response) {
      return { ...data, worker_response: { ...data.worker_response, ...job } };
    }
    return { ...data, response: { ...(data.response || {}), ...job } };
  } catch {
    return data;
  }
}

function activeText() {
  if (state.mode === "batch") {
    return $("batchText").value.split(/\r?\n/).find((line) => line.trim())?.trim() || "";
  }
  return $("text").value.trim();
}

function applyInferredParameters(parameters) {
  $("language").value = parameters.language || $("language").value;
  $("emotionTags").value = joinList(parameters.emotion_tags);
  $("emotionVector").value = joinList(parameters.emotion_vector);
  $("emotionMode").value = parameters.emotion_mode || "";
  $("emotionAlpha").value = parameters.emotion_alpha ?? "";
  $("emotionText").value = parameters.emotion_text || "";
  $("matchPatterns").value = joinList(parameters.match_patterns);
  $("refText").value = parameters.ref_text || "";
  $("maxTokens").value = parameters.max_new_tokens || $("maxTokens").value;
}

async function inferParameters() {
  const text = activeText();
  if (!text || state.busy) return;
  clearError();
  $("inferParameters").disabled = true;
  try {
    const character = selectedCharacter();
    const data = await api("/api/infer-parameters", {
      method: "POST",
      body: JSON.stringify({ text, character_id: character?.id || undefined }),
    });
    applyInferredParameters(data.parameters || {});
    $("inferStatus").textContent = data.source === "llm" ? "LLM 已回填" : "本地启发式已回填";
  } finally {
    $("inferParameters").disabled = false;
  }
}

function prependRun(data) {
  const fields = runFields(data);
  const card = document.createElement("article");
  card.className = "run-card";

  const top = document.createElement("div");
  top.className = "run-top";
  const id = document.createElement("div");
  id.className = "run-id";
  id.textContent = fields.id;
  const status = document.createElement("span");
  status.className = `run-status ${fields.status}`;
  status.textContent = statusText(fields.status);
  top.append(id, status);

  const text = document.createElement("div");
  text.className = "run-text";
  text.textContent = fields.text || "（空文本）";

  const path = document.createElement("div");
  path.className = "run-path";
  path.textContent = fields.output || fields.runDir;

  const meta = document.createElement("div");
  meta.className = "run-meta";
  meta.textContent = fields.workerUrl || fields.runDir;

  card.append(top, text, path, meta);
  $("jobs").prepend(card);
}

async function refreshRuns() {
  const data = await api("/api/runs?limit=12");
  $("jobs").replaceChildren();
  $("runCount").textContent = String(data.runs.length);
  if (!data.runs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "暂无请求";
    $("jobs").appendChild(empty);
    return;
  }
  const runs = await Promise.all(data.runs.map((run) => withFreshWorkerJob(run)));
  for (const run of runs) prependRun(run);
}

async function refreshWorkerStatus() {
  const workerUrl = encodeURIComponent($("workerUrl").value);
  try {
    const data = await api(`/api/worker/status?worker_url=${workerUrl}`);
    const queue = data.queued ?? 0;
    const ready = data.ready ? "就绪" : "加载中";
    setChip("workerStatus", data.engine || "工作进程", `${ready} / ${queue}`, "is-online");
  } catch {
    setChip("workerStatus", "工作进程", "离线", "is-offline");
  }
}

async function refreshAll() {
  clearError();
  await Promise.all([refreshWorkerStatus(), refreshRuns()]);
}

$("send").addEventListener("click", () => sendText().catch(showError));
$("sendBatch").addEventListener("click", () => sendBatch().catch(showError));
$("refresh").addEventListener("click", () => refreshAll().catch(showError));
$("inferParameters").addEventListener("click", () => inferParameters().catch(showError));
$("singleMode").addEventListener("click", () => setMode("single"));
$("batchMode").addEventListener("click", () => setMode("batch"));
$("character").addEventListener("change", () => {
  renderCharacterDetails();
  resolveHotSwitchRoute().catch(showError);
});
$("workerUrl").addEventListener("change", () => refreshWorkerStatus());
$("text").addEventListener("input", updateMeta);
$("batchText").addEventListener("input", updateMeta);
$("text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendText().catch(showError);
  }
});

loadConfig()
  .then(loadCharacters)
  .then(refreshAll)
  .then(updateMeta)
  .catch((error) => {
    setChip("routerStatus", "路由", "错误", "is-offline");
    showError(error);
  });

setInterval(refreshWorkerStatus, 2500);
