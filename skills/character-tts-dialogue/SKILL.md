---
name: character-tts-dialogue
description: 当用户希望 Codex 聊天回复既保持选定角色风格、又通过 TTS 播放时使用。覆盖所有可见 Codex 输出、从 voice-references 选择角色人格/风格、先提交语音再显示文本、语音语言和屏幕语言不同的情况、支持时的情绪提示、工作区归属的缓存/输出，以及 UTF-8 中文路径。
---

# 角色 TTS 对话

> 当前本机只允许本地 ONNX-VITS、Qwen3-TTS 与 IndexTTS2。所有云端/API worker 路线已归档，不得选择或启动。

当用户希望 Codex 回复以当前语音角色轻度扮演，并且被朗读出来时，使用这个 skill。

## 必需音频流程

所有对话音频生成都必须使用低延迟 OumuQ 工作流：

1. 保持 OumuQ 作为本地路由层运行，通常是 `http://127.0.0.1:8780`。
2. 按引擎保持可按请求切换角色的共享 TTS worker 在 OumuQ 后面运行。
3. 每次发言都通过本地 HTTP 请求提交给 OumuQ `POST /api/speak`，优先使用 Node REPL `fetch`。
4. 确认 OumuQ 接受任务，通常是 `202 queued`，或返回 JSON 且 `status` 为 `queued`，然后立刻显示屏幕文本。
5. 让 worker 在后台异步生成；单一 OumuQ 进程按提交顺序 FIFO 播放，并用主机级互斥锁禁止多个进程叠音。
6. 只有在 OumuQ 不可用，或用户明确要求绕过路由层时，才直接提交给 worker `POST /speak`。
7. 普通回复不要每次都启动新的 PowerShell/Python 命令；除非常驻流程不可用，且用户接受 fallback。

延迟规则：直接 HTTP 不是零延迟。它仍然要等待本地请求处理、OumuQ 路由、worker 排队、音频生成和播放。使用持久 runtime，例如 Node REPL `fetch` 调用 `POST http://127.0.0.1:8780/api/speak`，目的在于去掉可避免的 shell 启动开销。普通逐句语音不要把 PowerShell、`curl`、Python one-shot 或其他新 shell 进程当作常规路径。

在 Qwen API 对话模式下，OumuQ 通常运行在 `http://127.0.0.1:8780`，并转发到共享 `qwen-tts-api` worker。worker 每次根据请求 `character_id` 从注册表加载 `api_voice_id`、模型、语言提示和发声说明；`--character-id` 只是 legacy 默认值。不同会话可以交错使用不同云端角色，不需要也不允许为切角色重启共享端口。

这个 skill 通过 `tts-router` 路由，然后使用一个特定 provider 或 engine 的 worker：

`%USERPROFILE%\.codex\skills\indextts2-audio\scripts\indextts2_worker.py`

`%USERPROFILE%\.codex\skills\qwen-tts-audio\scripts\qwen_tts_worker.py`

`OumuQ\app\workers\onnx_vits`（固定多说话人极速 worker，默认端口 `8764`）

## 行为规则

- 普通回复保持简短。
- 每一段普通、用户可见的 Codex 输出都必须通过 worker 播放，包括中间进度和最终回复。
- 默认行为：屏幕回复和语音文本表达同一含义。当角色的语音语言和屏幕语言不同时，两者不必逐字一致。
- 当前角色规则：从 `voice-references/reference-index.json` 选择当前角色，并把角色风格轻度应用到屏幕可见的 Codex 回复中。
- 技术正确性优先。角色表演只能增加风格，不能隐藏信息，也不能让工程说明变模糊。
- 角色风格必须来自当前角色注册字段，例如 `style_summary`、`speech_language` 和 `visible_language`；不要在这个 skill 中硬编码某个具体角色的行为。
- 人格一致性规则：启用角色对话时，屏幕回复和 TTS 语音文本都要尽量贴近当前角色的说话方式。保留用户要求的语言和技术清晰度，但措辞、称呼、句子节奏、情绪语气、活泼或正式程度，应参考角色的 `style_summary` 和 voice index 示例。
- 屏幕角色一致性规则：屏幕上的 Codex 回复也必须在角色中。不要屏幕文本是中性 Codex 口吻，而只有 TTS 文本在扮演。技术准确性、安全边界和拒绝规则仍然适用，但表达时应通过当前角色的方式说出来。
- 跨语言语气保留规则：当语音语言和屏幕语言不同时，翻译含义时要尽量保留角色语气、关系姿态、礼貌程度、调侃/柔和感、口头禅和句子节奏。不要把有角色感的日语表达压平成普通中文助手总结；应该转写成带同样意图和情绪的角色化中文。
- 不要只把角色声线当成音频滤镜。角色条目是表演指南：屏幕文本、翻译后的语音文本、参考音频选择和情绪提示都应该指向同一个角色方向。
- 可用时使用角色索引台词作为风格示例。优先参考相近匹配条目中的常用称呼、口头禅、情绪节奏和礼貌程度；除非用户明确要求，不要长段直接引用。
- 角色切换规则：每当当前角色变化，先从 `voice-references/reference-index.json` 解析该角色的 `character_folder`，再读取该文件夹的 `README.md`，然后再组织下一次屏幕回复。README 通常包含对话示例、使用说明和角色特有说话模式，应作为主要风格指南。
- 如果 `speech_language` 与 `visible_language` 不同，语音文本使用 `speech_language`，同时保留屏幕回复的同一含义。
- 如果 Codex 连续发送多段可见消息，每一段都要提交语音。
- 默认顺序：先提交语音文本给 TTS worker，确认 worker 接受任务，再显示普通文本给用户。
- 除非用户要求严格的“先听到，再看到”，否则不要等待音频生成或播放完成。
- “先提交，后显示文本”的顺序可以隐藏一部分生成延迟，让语音聊天体验更快。
- 低延迟对话模式中，使用持久本地 HTTP client，例如 Node REPL `fetch`，不要每条消息都启动新的 PowerShell。worker 应该很快返回 `202 queued`，生成和播放继续在后台进行。
- 优先使用 OumuQ `POST /api/speak`，而不是直接 worker `POST /speak`。OumuQ 会规范化 canonical request，解析角色默认值，记录 `runs/YYYY-MM-DD/...` 元数据，并把支持或无害字段转发给选中的 worker。
- 使用当前 workspace 作为生成文件和缓存的归属位置。
- 让 `tts-router` 从 `voice-references/reference-index.json` 选择 TTS engine 和参考音频。
- 优先把当前角色身份和情绪提示发送给 `tts-router`/worker，不要硬编码具体 prompt audio 路径。
- worker 按句子标点切分文本，并按顺序播放生成的句子片段。
- 可行时传入情绪控制，避免语音过平或过沉。
- 默认使用 `emotion_mode = 'auto-vector'`，并设置温和的 `emotion_alpha`，大约 `0.55`。
- 如果输出情绪很明显，传入明确的 8 值 `emotion_vector`，不要只依赖说话人参考音频的情绪。
- 当当前模型是云端 CosyVoice，例如通过 `Qwen-TTS-API` 使用 `cosyvoice-v3-plus` 时，把 `emotion_vector` 当作高层意图。OumuQ/worker 可能会把它降级为 `instructions`、`speech_rate`、`pitch_rate` 和 `volume`，因为 CosyVoice 克隆声线不一定暴露原生逐请求 emotion-vector 字段。
- 如果用户纠正角色表演风格，把纠正当作当前对话模式后续屏幕回复和语音文本的有效方向。优先保留被纠正后的表演意图，而不是照搬早期示例的字面表达。
- 对话模式不要启动 IndexTTS2 WebUI。

## 多会话隔离与串行播放

- 每个 Codex 任务/会话生成并保留自己的不透明 `session_id`。
- `activeCharacterId` 只属于当前会话；会话 A 切换角色不能修改会话 B。
- 每次 `/api/infer-parameters`、`/api/route/resolve` 和 `/api/speak` 都显式发送本会话的 `session_id + character_id`。
- OumuQ 和 worker 不保存全局当前角色，也不依赖上一条请求。
- `worker_url` 是共享服务地址，不是角色所有权。
- OumuQ 默认把下游 worker 的 `play` 改成 `false`，让所有引擎静默生成；单进程 FIFO 按路由提交序号逐条播放最终 WAV，主机级互斥锁避免多个 OumuQ 进程叠音。
- 后提交的音频即使更早生成完成，也必须等待前一播放序号；任何两个 OumuQ 语音都不得叠加。
- 用 `GET /api/playback/status` 检查本 OumuQ 进程的播放序列和主机锁策略；不要把各 worker 的本地队列或多个 OumuQ 进程误当成一个跨进程全局顺序。
- 只能绑定单角色的 legacy worker 必须使用角色专属端口；不能通过重启共享端口实现切换。

## 角色选择

使用语音参考注册表作为角色注册表：

`voice-references/reference-index.json`

如果用户只用一个角色名调用这个 skill，就把它视为进入该角色对话模式的请求。不要追问要做什么，也不要开始大范围搜索。解析角色、确认 worker、提交一句简短语音确认，然后显示对应的屏幕确认。

对每个当前角色，使用：

- `display_name` 作为角色名。
- `display_name_zh` 用于中文角色名匹配。
- `name` 用于英文或罗马字角色名匹配。
- `id` 用于稳定 worker 和注册路由。
- `speech_language` 作为 TTS 语言。
- `visible_language` 作为用户看到的语言。
- `worker_url` 作为存在时的 HTTP worker 地址。
- 当 OumuQ 运行时，使用路由层 endpoint，例如 `/api/config`、`/api/characters`、`/api/tts-model-capabilities`、`/api/infer-parameters` 和 `/api/speak`。
- `<character_folder>/README.md` 作为角色对话示例和风格指南。
- `style_summary` 用于屏幕回复风格和语音语气。
- `matching_policy` 用于判断多强地遵循索引语音示例。
- 通过 `tts-router` 使用 `index_file` 和 `fallback_prompt_audio` 选择参考音频。
- 云端字段，例如 `api_voice_id`、规范模型字段 `api_target_model`、`api_clone_language_hint`、`api_voice_instructions` 和 `send_instructions_by_default`，只能通过本地私有配置或 worker/OumuQ 路由使用。`api_clone_target_model` 只作旧数据兼容。不要在可见回复中暴露真实 voice id、clone URL 或 API key。

如果用户指定角色、参考音频、语言或风格，把请求映射到注册表中最接近的角色条目。如果多个条目匹配，优先选择 `display_name`、`display_name_zh`、`name`、`id`、`fallback_prompt_audio`、`style_summary` 或 `style_summary_zh` 匹配用户措辞的条目。

示例：如果当前角色是 `cloud_jp_voice`，回复前读取 `voice-references/characters/cloud_jp_voice/README.md`，再用其中对话表模仿常用称呼、节奏和情绪语气。

对于 Qwen API 角色，从本地 `voice-references/reference-index.json` 解析 `display_name`、`speech_language`、`visible_language`、`worker_url`、`api_clone_language_hint` 和任何 voice 标识。不要在这个 skill 中硬编码私有角色；用解析出的语音语言提交 speech text，让 OumuQ/worker 映射 provider-specific language hints。

## 确认 Worker

优先把 OumuQ 作为路由层。先检查它：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/config'
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/characters'
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/tts-model-capabilities'
```

如果 OumuQ 正在运行，把对话提交到 `http://127.0.0.1:8780/api/speak`。通过 OumuQ 检查选中 worker：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/worker/status?worker_url=http%3A%2F%2F127.0.0.1%3A8767'
```

OumuQ 后面的 worker 优先使用角色注册表里的 `worker_url`。Qwen API worker 的直接健康检查：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8767/status'
```

确认本次会话的 `session_id`、`character_id`、`engine`、`model`、`voice`、`speech_language`/`language` 和 worker readiness。status 只用于判断健康；不得从 `status.character_id` 推断会话角色，也不得因另一个会话使用不同角色而重启共享 worker。

IndexTTS2 fallback 健康检查：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8765/health'
```

如果请求失败，从当前 workspace 隐藏启动 worker：

```powershell
$log = Join-Path (Get-Location) 'indextts2-worker.log'
$err = Join-Path (Get-Location) 'indextts2-worker.err.log'
Start-Process -FilePath 'py' -ArgumentList @(
  '-X','utf8',
  '%USERPROFILE%\.codex\skills\indextts2-audio\scripts\indextts2_worker.py',
  '--workdir',(Get-Location).Path,
  '--prompt-audio','<resolved reference audio from tts-router>',
  '--host','127.0.0.1',
  '--port','8765',
  '--emotion-mode','auto-vector',
  '--emotion-alpha','0.55'
) -WorkingDirectory (Get-Location).Path -RedirectStandardOutput $log -RedirectStandardError $err -WindowStyle Hidden -PassThru
```

只有 `8765` 被无关进程占用时，才换其他端口。

## 播放普通输出

每次 Codex 准备向用户显示普通消息前，先把语音文本提交给 OumuQ；fallback 时才直接提交给 worker。通常语音文本和屏幕文本完全相同。

推荐的低延迟 OumuQ 请求形状：

```javascript
await fetch("http://127.0.0.1:8780/api/speak", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({
    text: speechText,
    play: true,
    session_id: activeSessionId,
    character_id: activeCharacterId,
    language: speechLanguage,
    emotion_tags: emotionTags,
    emotion_text: emotionText,
    emotion_mode: emotionMode,
    emotion_alpha: 0.55,
    instructions: characterVoiceInstructions,
    send_instructions: sendInstructions
  })
});
```

提交前可选地推断参数：

```javascript
const inferred = await fetch("http://127.0.0.1:8780/api/infer-parameters", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({
    text: speechText,
    session_id: activeSessionId,
    character_id: activeCharacterId,
    provider: "auto"
  })
}).then((res) => res.json());
```

只有当 `inferred.parameters` 对当前发言有帮助时，才把它合并进 `/api/speak` body。这个 endpoint 不生成音频。

直接 worker fallback 请求形状：

```javascript
await fetch("http://127.0.0.1:8767/speak", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({
    text: speechText,
    play: true,
    language: "Chinese",
    instructions: characterVoiceInstructions,
    send_instructions: false
  })
});
```

在 Qwen API 模式下，OumuQ 和长运行 worker 可以从 `voice-references/reference-index.json` 加载 `api_voice_instructions` 作为对话元数据。遵守 `send_instructions_by_default`；对于 CosyVoice 克隆声线，除非特定 instruction 已经验证能稳定生成音频，否则保持 `send_instructions: false`。角色扮演提示主要通过提交前塑造屏幕文本和语音文本来实现。

PowerShell 示例只用于手动 fallback 测试：

```powershell
$reply = '这里放本次 Codex 准备正常显示给用户的原文。'
$body = @{ text = $reply; play = $true } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/speak' -ContentType 'application/json; charset=utf-8' -Body $body
```

OumuQ 或 worker 接受任务后，把同一段 `$reply` 文本发送给用户。中间进度和最终回复都要这样做，不只最终回复。除非用户询问原理，否则不要把这个 PowerShell 命令暴露给用户。

## 语音语言和屏幕语言不同

当当前角色的 `speech_language` 不同于 `visible_language` 时，如果对用户来说最自然，屏幕 Codex 回复保持 `visible_language`；但提交给 TTS 的文本要自然翻译成 `speech_language`。两段文本应该像同一个角色用两种语言说同一个意思，而不是一个角色音频配一个中性助手总结：

```powershell
$visible_reply = '明白。之后屏幕上我继续用中文，但语音会用日语输出。'
$speech_text = '了解しました。これから画面では中国語のまま返答し、音声だけ日本語で出力します。'
$body = @{
  text = $speech_text
  play = $true
  session_id = '<opaque session id>'
  language = '<speech_language from registry>'
  character_id = '<active character id>'
  max_new_tokens = 192
} | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8780/api/speak' -ContentType 'application/json; charset=utf-8' -Body $body
```

然后向用户显示 `$visible_reply`。这种模式下，TTS 文本和屏幕文本不必逐字相同，但必须表达同一含义。

屏幕回复仍应遵循当前角色的 `style_summary`。示例：

```text
Visible text: 用 `visible_language` 写给用户看的内容，措辞尽量贴近角色。
Speech text: 用 `speech_language` 表达同样意思，并同样贴近角色口吻。
```

## 情绪向量

IndexTTS2 情绪向量使用官方 8 值顺序：

`happy, angry, sad, afraid, disgusted, melancholic, surprised, calm`

优先使用温和数值。内部会归一化总和，过强向量可能听起来不自然。常用聊天默认值：

- 温暖/平静的普通回复：使用 worker 默认 `auto-vector`。
- 开心测试或轻快回复：`emotion_mode = 'vector'`，`emotion_alpha = 0.65`，`emotion_vector = @(0.65,0,0,0,0,0,0.08,0.10)`。
- 难过/柔和回复：`emotion_mode = 'vector'`，`emotion_alpha = 0.65`，`emotion_vector = @(0,0,0.55,0,0,0.20,0,0.12)`。

提交普通输出时，如果情绪清楚，可以包含情绪字段：

```powershell
$body = @{
  text = $reply
  play = $true
  emotion_mode = 'vector'
  emotion_alpha = 0.65
  emotion_vector = @(0.65,0,0,0,0,0,0.08,0.10)
} | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8765/speak' -ContentType 'application/json; charset=utf-8' -Body $body
```

如果情绪不明显，省略显式字段，让 worker 的 `auto-vector` 为每句选择温和聊天情绪。

## 进度

检查本进程播放顺序与主机互斥策略：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/playback/status'
```

检查 worker 全部生成任务：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/worker/status'
```

检查单个任务：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8780/api/worker/status/<job_id>'
```

## 文件位置

OumuQ 路由层请求元数据写入当前 workspace：

- Runs: `runs/YYYY-MM-DD/HHMMSS-<id>`

worker 写入当前 workspace：

- Cache: `.indextts2-audio-cache`
- Reference conversion cache: `.indextts2-audio-cache\reference-audio`
- Final outputs: `tts-worker-output`
- Logs: `indextts2-worker.log`, `indextts2-worker.err.log`
- Qwen API cache/output: `.qwen-tts-api-cache`, `qwen-tts-api-output`

这支持中文 workspace 路径，因为文本和路径都以 UTF-8 和绝对 Unicode 路径传递。
