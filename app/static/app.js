const SESSION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SESSION_STORAGE_PREFIX = "oumuq.session.";
const CHARACTER_DRAFT_FIELDS = [
  "language",
  "emotionTags",
  "emotionVector",
  "emotionMode",
  "emotionAlpha",
  "emotionText",
  "matchPatterns",
  "refText",
  "promptAudio",
  "promptAudios",
];

function createSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return "session-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

function resolveSessionId() {
  const url = new URL(window.location.href);
  let sessionId = (url.searchParams.get("session") || "").trim();
  if (!SESSION_ID_PATTERN.test(sessionId)) {
    sessionId = createSessionId();
    url.searchParams.set("session", sessionId);
    window.history.replaceState({}, "", url);
  }
  return sessionId;
}

function readSessionState(sessionId) {
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_PREFIX + sessionId);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

const activeSessionId = resolveSessionId();
const initialSessionState = readSessionState(activeSessionId);
const state = {
  mode: "single",
  characters: [],
  config: null,
  busy: false,
  route: null,
  sessionId: activeSessionId,
  activeCharacterId: null,
  savedCharacterId: initialSessionState.character_id || null,
  characterDrafts: initialSessionState.character_drafts || {},
  workerUrlOverride: false,
  workerUrlRevision: 0,
  formRevision: 0,
  routeEpoch: 0,
  routeController: null,
  inferEpoch: 0,
  inferController: null,
  workerStatusEpoch: 0,
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

function persistSessionState() {
  try {
    window.sessionStorage.setItem(
      SESSION_STORAGE_PREFIX + state.sessionId,
      JSON.stringify({
        character_id: state.activeCharacterId,
        character_drafts: state.characterDrafts,
      }),
    );
  } catch {
    // sessionStorage is only a per-tab convenience cache; routing remains request-owned.
  }
}

function readCharacterDraftFromForm() {
  return Object.fromEntries(CHARACTER_DRAFT_FIELDS.map((id) => [id, $(id).value]));
}

function saveCharacterDraft(characterId = state.activeCharacterId) {
  if (!characterId) return;
  state.characterDrafts[characterId] = readCharacterDraftFromForm();
  persistSessionState();
}

function resetCharacterFields(character) {
  for (const id of CHARACTER_DRAFT_FIELDS) $(id).value = "";
  $("language").value = character?.speech_language || "";
}

function restoreCharacterDraft(characterId) {
  const draft = state.characterDrafts[characterId];
  if (!draft || typeof draft !== "object") return;
  for (const id of CHARACTER_DRAFT_FIELDS) {
    if (Object.hasOwn(draft, id)) $(id).value = draft[id] ?? "";
  }
}

function shortSessionId(sessionId = state.sessionId) {
  return sessionId.length > 12 ? sessionId.slice(0, 8) + "…" : sessionId;
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

function requestBase(character = selectedCharacter()) {
  const payload = {
    session_id: state.sessionId,
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
  const workerUrl = $("workerUrl").value.trim();
  if (state.workerUrlOverride && workerUrl) payload.worker_url = workerUrl;
  return payload;
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

function setWorkerVolumeHint(data, workerUrl) {
  const hint = $("workerVolumeHint");
  if (!hint) return;
  if (!data) {
    hint.textContent = "播放音量：工作进程离线";
    hint.className = "worker-volume-hint is-offline";
    return;
  }
  const host = data.playback_host || "OumuQ worker";
  const visibleProcess = data.windows_volume_process || host;
  const fallback = visibleProcess === host ? "；若 Windows 仍显示 Python，请调 Python 音量" : "";
  const enabled = data.playback_enabled === false ? "；当前禁用了自动播放" : "";
  hint.textContent = `播放音量：Windows 音量混合器请看 ${visibleProcess}${fallback}${enabled}。地址 ${workerUrl}`;
  hint.title = data.windows_volume_hint || "";
  hint.className = "worker-volume-hint";
}

function renderCharacterDetails({ restoreDraft = true } = {}) {
  const character = selectedCharacter();
  const box = $("characterDetails");
  box.replaceChildren();
  if (!character) {
    box.className = "character-card is-empty";
    box.textContent = "没有角色";
    $("activeRoute").textContent = "会话 " + shortSessionId() + " / 未选择路由";
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

  state.formRevision += 1;
  resetCharacterFields(character);
  if (restoreDraft) restoreCharacterDraft(character.id);
  state.workerUrlOverride = false;
  $("workerUrl").value = workerUrlForCharacter(character);
  $("activeRoute").textContent =
    "会话 " + shortSessionId() + " / " + character.id + " / " +
    (character.tts_engine || "worker") + " / " + (character.speech_language || "语音语言");
}

async function resolveHotSwitchRoute() {
  const character = selectedCharacter();
  if (!character) return;

  state.routeController?.abort();
  const controller = new AbortController();
  const epoch = ++state.routeEpoch;
  const characterId = character.id;
  const usedWorkerOverride = state.workerUrlOverride;
  const workerUrlRevision = state.workerUrlRevision;
  const workerUrlValue = $("workerUrl").value.trim();
  state.routeController = controller;

  try {
    const data = await api("/api/route/resolve", {
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({ ...requestBase(character), text: activeText(), character_id: characterId }),
    });
    if (
      epoch !== state.routeEpoch ||
      selectedCharacter()?.id !== characterId ||
      data.route_id !== characterId ||
      data.session_id !== state.sessionId ||
      state.workerUrlRevision !== workerUrlRevision ||
      state.workerUrlOverride !== usedWorkerOverride ||
      $("workerUrl").value.trim() !== workerUrlValue
    ) {
      return;
    }
    state.route = data;
    state.workerUrlOverride = usedWorkerOverride;
    $("workerUrl").value = data.worker_url || $("workerUrl").value;
    $("activeRoute").textContent =
      "会话 " + shortSessionId() + " / 热切换: " + data.route_id + " -> " + data.worker_url;
    setChip("routerStatus", "路由", "会话隔离就绪", "is-online");
    await refreshWorkerStatus();
  } catch (error) {
    if (error?.name === "AbortError") return;
    throw error;
  }
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
    option.textContent = characterName(character) + " / " + (character.tts_engine || "worker");
    $("character").appendChild(option);
  }
  $("characterCount").textContent = String(state.characters.length);
  const characterIds = new Set(state.characters.map((item) => item.id));
  const preferredCharacterId = [state.activeCharacterId, state.savedCharacterId]
    .find((characterId) => characterId && characterIds.has(characterId));
  if (preferredCharacterId) $("character").value = preferredCharacterId;
  state.activeCharacterId = selectedCharacter()?.id || null;
  state.savedCharacterId = state.activeCharacterId;
  renderCharacterDetails();
  persistSessionState();
  await resolveHotSwitchRoute();
}

async function handleCharacterChange() {
  saveCharacterDraft(state.activeCharacterId);
  state.routeController?.abort();
  state.inferController?.abort();
  state.activeCharacterId = selectedCharacter()?.id || null;
  state.savedCharacterId = state.activeCharacterId;
  state.workerUrlOverride = false;
  renderCharacterDetails();
  persistSessionState();
  await resolveHotSwitchRoute();
  await refreshRuns();
}

function setMode(mode) {
  if (state.mode !== mode) state.formRevision += 1;
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
  const character = selectedCharacter();
  if (!character) throw new Error("请先选择角色。");
  clearError();
  setBusy(true);
  try {
    const payload = { ...requestBase(character), text, character_id: character.id };
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
  const character = selectedCharacter();
  if (!character) throw new Error("请先选择角色。");
  clearError();
  setBusy(true);
  try {
    const payload = { ...requestBase(character), lines, character_id: character.id };
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
  const envelope = data.request || {};
  const request = envelope.payload || {};
  return {
    id: response.id || "本地",
    status: response.status || "submitted",
    text: response.text || request.text || "",
    output: response.output || data.run_dir || "",
    runDir: data.run_dir || "",
    workerUrl: envelope.worker_url || "",
    characterId: envelope.route_id || request.character_id || response.character_id || "",
    sessionId: envelope.session_id || request.session_id || "",
    playbackSequence: data.playback?.sequence || envelope.playback?.sequence || null,
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
  const character = selectedCharacter();
  if (!character) throw new Error("请先选择角色。");

  state.inferController?.abort();
  const controller = new AbortController();
  const epoch = ++state.inferEpoch;
  const characterId = character.id;
  const formRevision = state.formRevision;
  state.inferController = controller;

  clearError();
  $("inferParameters").disabled = true;
  try {
    const data = await api("/api/infer-parameters", {
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({
        text,
        session_id: state.sessionId,
        character_id: characterId,
      }),
    });
    if (
      epoch !== state.inferEpoch ||
      selectedCharacter()?.id !== characterId ||
      data.session_id !== state.sessionId ||
      state.formRevision !== formRevision ||
      activeText() !== text
    ) {
      return;
    }
    applyInferredParameters(data.parameters || {});
    saveCharacterDraft(characterId);
    $("inferStatus").textContent = data.source === "llm" ? "LLM 已回填" : "本地启发式已回填";
  } catch (error) {
    if (error?.name === "AbortError") return;
    throw error;
  } finally {
    if (epoch === state.inferEpoch) $("inferParameters").disabled = false;
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
  status.className = "run-status " + fields.status;
  status.textContent = statusText(fields.status);
  top.append(id, status);

  const text = document.createElement("div");
  text.className = "run-text";
  text.textContent = fields.text || "（空文本）";

  const path = document.createElement("div");
  path.className = "run-path";
  path.textContent = fields.output || fields.runDir;

  const character = state.characters.find((item) => item.id === fields.characterId);
  const metaParts = [];
  if (fields.characterId) {
    metaParts.push("角色 " + (characterName(character) || fields.characterId) + " (" + fields.characterId + ")");
  }
  if (fields.sessionId) metaParts.push("会话 " + shortSessionId(fields.sessionId));
  if (fields.playbackSequence) metaParts.push("串行播放 #" + fields.playbackSequence);
  if (fields.workerUrl) metaParts.push(fields.workerUrl);
  else if (fields.runDir) metaParts.push(fields.runDir);
  const meta = document.createElement("div");
  meta.className = "run-meta";
  meta.textContent = metaParts.join(" · ");

  card.append(top, text, path, meta);
  $("jobs").prepend(card);
}

async function refreshRuns() {
  const sessionId = encodeURIComponent(state.sessionId);
  const data = await api("/api/runs?limit=12&session_id=" + sessionId);
  $("jobs").replaceChildren();
  $("runCount").textContent = String(data.runs.length);
  if (!data.runs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "会话 " + shortSessionId() + " 暂无请求";
    $("jobs").appendChild(empty);
    return;
  }
  const runs = await Promise.all(data.runs.map((run) => withFreshWorkerJob(run)));
  for (const run of runs) prependRun(run);
}

async function refreshWorkerStatus() {
  const rawWorkerUrl = $("workerUrl").value.trim();
  if (!rawWorkerUrl) return;
  const epoch = ++state.workerStatusEpoch;
  const workerUrl = encodeURIComponent(rawWorkerUrl);
  try {
    const data = await api("/api/worker/status?worker_url=" + workerUrl);
    if (epoch !== state.workerStatusEpoch || $("workerUrl").value.trim() !== rawWorkerUrl) return;
    const queue = data.queued ?? 0;
    const ready = data.ready ? "就绪" : "加载中";
    const host = data.playback_host || data.engine || "工作进程";
    setChip("workerStatus", host, ready + " / " + queue, "is-online");
    setWorkerVolumeHint(data, rawWorkerUrl);
  } catch {
    if (epoch !== state.workerStatusEpoch || $("workerUrl").value.trim() !== rawWorkerUrl) return;
    setChip("workerStatus", "工作进程", "离线", "is-offline");
    setWorkerVolumeHint(null, rawWorkerUrl);
  }
}

async function refreshPlaybackStatus() {
  try {
    const data = await api("/api/playback/status?limit=20");
    const active = data.active_sequence ? "播放 #" + data.active_sequence : "空闲";
    setChip("playbackStatus", "串行播放", active + " / 排队 " + data.queued, "is-online");
  } catch {
    setChip("playbackStatus", "串行播放", "不可用", "is-offline");
  }
}

async function refreshAll({ reloadCharacters = false } = {}) {
  clearError();
  if (reloadCharacters) {
    saveCharacterDraft(state.activeCharacterId);
    await loadCharacters();
  }
  await Promise.all([refreshWorkerStatus(), refreshPlaybackStatus(), refreshRuns()]);
}

function openNewSession() {
  const url = new URL(window.location.href);
  url.searchParams.set("session", createSessionId());
  window.open(url.toString(), "_blank", "noopener");
}

$("send").addEventListener("click", () => sendText().catch(showError));
$("sendBatch").addEventListener("click", () => sendBatch().catch(showError));
$("refresh").addEventListener("click", () => refreshAll({ reloadCharacters: true }).catch(showError));
$("newSession").addEventListener("click", openNewSession);
$("inferParameters").addEventListener("click", () => inferParameters().catch(showError));
$("singleMode").addEventListener("click", () => setMode("single"));
$("batchMode").addEventListener("click", () => setMode("batch"));
$("character").addEventListener("change", () => handleCharacterChange().catch(showError));
$("workerUrl").addEventListener("input", () => {
  state.workerUrlOverride = true;
  state.workerUrlRevision += 1;
  state.formRevision += 1;
});
$("workerUrl").addEventListener("change", () => refreshWorkerStatus());
for (const id of CHARACTER_DRAFT_FIELDS) {
  $(id).addEventListener("input", () => {
    state.formRevision += 1;
    saveCharacterDraft();
  });
  $(id).addEventListener("change", () => {
    state.formRevision += 1;
    saveCharacterDraft();
  });
}
$("maxTokens").addEventListener("input", () => {
  state.formRevision += 1;
});
$("maxTokens").addEventListener("change", () => {
  state.formRevision += 1;
});
$("play").addEventListener("change", () => {
  state.formRevision += 1;
});
$("text").addEventListener("input", () => {
  state.formRevision += 1;
  updateMeta();
});
$("batchText").addEventListener("input", () => {
  state.formRevision += 1;
  updateMeta();
});
$("text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendText().catch(showError);
  }
});

setChip("sessionStatus", "会话", shortSessionId(), "is-online");

loadConfig()
  .then(loadCharacters)
  .then(refreshAll)
  .then(updateMeta)
  .catch((error) => {
    setChip("routerStatus", "路由", "错误", "is-offline");
    showError(error);
  });

setInterval(() => {
  refreshWorkerStatus();
  refreshPlaybackStatus();
}, 2500);
