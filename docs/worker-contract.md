# Worker 契约

OumuQ 通过 HTTP 和模型 worker 通信。

worker 契约采用角色优先设计。调用方最好只发送 `character_id` 和文本，由 worker 或路由层解析语言、引擎参数、参考音频、情绪提示和播放行为。

worker 可以复用 `app/core/voice_reference.py` 完成角色注册表读取、正则匹配、情绪向量评分、短参考音频补长和 composite prompt WAV 创建。

## 热切换

热切换的高层 key 是 `character_id`。

调用方切换角色时，不应重启 worker，也不应把某条声线写死为进程启动参数。正确流程是：

```text
选择 character_id -> OumuQ 解析角色注册表 -> 下一次 /speak 带 character_id 和解析参数 -> worker 按请求切声线
```

OumuQ 提供辅助接口预览当前角色会被解析到哪里：

```text
POST /api/route/resolve
```

请求：

```json
{
  "character_id": "<character_id>"
}
```

返回会包含：

```json
{
  "hot_switch": true,
  "switch_key": "character_id",
  "route_id": "<character_id>",
  "worker_url": "http://127.0.0.1:8767",
  "payload": {
    "character_id": "<character_id>",
    "language": "Japanese"
  }
}
```

这个接口只解析路由，不提交语音，不触发生成。旧式“一个 worker 进程只绑定一条 prompt audio”的模式只能作为兼容 fallback。

## 多会话和串行播放

OumuQ 不保存全局当前角色。调用方会话拥有 `session_id` 和 `character_id`，并在每次请求中显式发送。worker 必须把角色、音色、模型、语言、参考音频和说明解析成不可变 job 快照；不得读取“上一条请求角色”。

一旦请求带有已注册的 `character_id`，该角色注册表中的云端 voice、`api_target_model` 和存在的 `character_folder` 是权威绑定。客户端残留的 voice/model/folder 不得覆盖角色身份；只有不带角色的 legacy/高级直连路径才允许这些覆盖。

`session_id` 是 OumuQ 关联字段，默认不会转发给旧 worker。支持该字段的 worker 可以把它写入 job 诊断信息，但不能用它建立隐式角色绑定。

启用统一播放时，OumuQ 会把下游 `play` 改为 `false`。worker 只生成最终 WAV；单一 OumuQ 进程的 FIFO 按路由层提交序号播放，实际播放持有主机级互斥锁。不同 worker 不得自行播放，因此跨引擎、跨 OumuQ 进程也不会重叠；但多个 OumuQ 进程之间不保证统一 FIFO 顺序。

```text
route sequence 1 -> worker A generate ─┐
route sequence 2 -> worker B generate ─┼-> process FIFO + host lock -> one WAV at a time
route sequence 3 -> worker A generate ─┘
```

worker 的 `done` 必须表示最终输出文件已经写完，可以安全打开。播放状态由 `GET /api/playback/status` 查询。

## 必需接口

```text
GET  /health
GET  /status
GET  /status/<job_id>
POST /speak
```

## POST /speak

`text` 是 TTS 实际要朗读的语音文本，不一定等于屏幕可见文本。Agent 对话模式应先准备语音文本和可见文本，提交语音文本，拿到 `queued` 后再显示可见文本。

请求体示例：

```json
{
  "text": "晚上好，今天辛苦了。",
  "play": true,
  "session_id": "opaque-session-id",
  "language": "Japanese",
  "character_id": "jp_companion",
  "emotion_tags": ["cheerful", "gentle"],
  "emotion_vector": [0.22, 0, 0, 0, 0, 0, 0.08, 0.14],
  "emotion_mode": "vector",
  "emotion_alpha": 0.5,
  "emotion_text": "bright and gentle",
  "ref_text": "晚上好，今天辛苦了。",
  "match_patterns": ["晚上好|辛苦了"],
  "prompt_audio": "voice-references/characters/jp_companion/audio/sample.wav",
  "instructions": "Use a warm conversational delivery.",
  "send_instructions": false,
  "max_new_tokens": 192
}
```

worker 应尽快返回任务对象：

```json
{
  "id": "20260604-010203-abcd1234",
  "status": "queued",
  "output": "outputs/2026-06-04/010203-abcd1234/final.wav",
  "play": true
}
```

生成和播放应在 worker 进程里异步继续执行。

如果 worker 收到的是角色对话请求，调用方负责保证传入的 `text` 已经符合 `speech_language` 和角色语气。worker 可以记录 `character_id`、`language` 和解析后的路由信息，但不应把普通助手文本自动改写成角色文本，除非它显式实现了安全的文本改写层。

## 角色感知字段

- `session_id`：可选的调用方会话关联 ID；不代表角色绑定。
- `character_id`：推荐使用的高层角色选择器，每个会话请求都应显式携带。
- `character_folder`：无 `character_id` 的高级直连可显式指定；有已注册角色时必须由角色注册表解析，防止跨会话串用参考音频。
- `language`：语音输出语言，通常来自角色配置。
- `emotion_tags`：人类可读的情绪提示。
- `emotion_vector`：数值情绪控制，也可用于参考音频匹配。
- `emotion_mode`：worker 对情绪字段的解释模式，例如 `tags`、`vector` 或 `text`。
- `emotion_alpha`：情绪控制强度，通常是 0 到 1 的浮点数。
- `emotion_text`：自然语言情绪描述，适合支持文本情绪提示的 worker。
- `match_patterns`：请求侧正则或关键词提示。
- `ref_text`：参考音频对应的文本，适合需要显式 prompt text 的 worker。
- `prompt_audio`：显式指定单条参考音频。
- `prompt_audios`：显式指定多条参考音频。
- `instructions`：provider 侧发声说明，适合已验证支持该字段的 API worker。
- `send_instructions`：是否把 `instructions` 发送给 provider；未验证时建议为 `false`。

正常对话优先使用 `character_id`。显式参考音频路径更适合调试、测试和手动配音生产。

## 云端 API worker

云端 worker 应保持和本地 worker 一样的路由接口。调用方优先传 `character_id`，由 worker 从本地 `voice-references/reference-index.json` 读取云端字段：

```json
{
  "id": "cloud_zh_voice",
  "tts_engine": "Qwen-TTS-API",
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "api_target_model": "cosyvoice-v3-plus",
  "send_instructions_by_default": false
}
```

公开仓库只能保留占位符。真实 `voice_id`、克隆 URL、API key 和服务器地址应放在本地私有配置、环境变量或部署密钥中。

## POST /api/infer-parameters

这是 OumuQ 路由层的辅助接口，不是 worker 必需接口。它用于在提交 `/api/speak` 或 `/api/batch` 前，根据文本和角色推理参数。

```json
{
  "text": "晚上好，今天辛苦了。",
  "character_id": "jp_companion",
  "provider": "auto"
}
```

`provider` 可选：

- `auto`：如果配置了 LLM 就用 LLM，否则用本地启发式。
- `heuristic`：只用本地启发式。
- `llm`：强制使用 OpenAI-compatible LLM。

接口只返回参数，不会触发语音生成或播放。

## 输出组织

worker 推荐按日期和时间写最终音频：

```text
outputs/
  2026-06-04/
    010203-abcd1234/
      request.json
      response.json
      chunks/
      final.wav
```

路由层也会记录请求和响应元数据：

```text
runs/YYYY-MM-DD/HHMMSS-<id>/
```

## 播放规则

默认由 OumuQ 统一负责播放。路由层可以快速向不同 worker 提交请求，但会把下游 `play` 改为 `false`；worker 只生成完整 WAV，OumuQ 再按提交序号进入进程内 FIFO，并持有主机级互斥锁完成播放。

只有显式设置 `OUMUQ_GLOBAL_PLAYBACK=0` 的兼容模式才由 worker 自行播放。该模式只能保证单个 worker 内的顺序，无法保证跨 worker 或跨进程不叠音，不适合作为多会话默认配置。

如果 worker 支持分句生成，应保证同一请求内的分句顺序稳定。
