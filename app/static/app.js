const state = {
  mode: "single",
  characters: [],
  config: null,
  busy: false,
};

const $ = (id) => document.getElementById(id);

function splitComma(value) {
  return value
    .split(/[,\uFF0C]/)
    .map((item) => item.trim())
    .filter(Boolean);
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
    match_patterns: splitComma($("matchPatterns").value),
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
  $("activeRoute").textContent = `${character.id} / ${character.tts_engine || "worker"} / ${
    character.speech_language || "语音语言"
  }`;
}

async function loadConfig() {
  state.config = await api("/api/config");
  $("workerUrl").value = state.config.default_worker_url;
  $("registryBadge").textContent = state.config.registry_exists ? "工作区" : "示例";
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
  };
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
  path.textContent = fields.output;

  card.append(top, text, path);
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
  for (const run of data.runs) prependRun(run);
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
  await Promise.all([refreshWorkerStatus(), refreshRuns()]);
}

$("send").addEventListener("click", () => sendText().catch((error) => alert(error.message)));
$("sendBatch").addEventListener("click", () => sendBatch().catch((error) => alert(error.message)));
$("refresh").addEventListener("click", () => refreshAll().catch((error) => alert(error.message)));
$("singleMode").addEventListener("click", () => setMode("single"));
$("batchMode").addEventListener("click", () => setMode("batch"));
$("character").addEventListener("change", renderCharacterDetails);
$("workerUrl").addEventListener("change", () => refreshWorkerStatus());
$("text").addEventListener("input", updateMeta);
$("batchText").addEventListener("input", updateMeta);
$("text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendText().catch((error) => alert(error.message));
  }
});

loadConfig()
  .then(loadCharacters)
  .then(refreshAll)
  .then(updateMeta)
  .catch((error) => {
    setChip("routerStatus", "路由", "错误", "is-offline");
    alert(error.message);
  });

setInterval(refreshWorkerStatus, 2500);
