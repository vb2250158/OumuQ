---
name: tts-router-workflow
description: 当 Agent 需要从 voice-references 中选择 OumuQ 兼容的本地 TTS worker、语言、角色、固定声线、参考音频或播放行为时使用。
---

# TTS 路由工作流

> 当前本机只允许本地 ONNX-VITS、Qwen3-TTS 与 IndexTTS2。所有云端/API worker 路线已归档，不得选择或启动。

把 `voice-references/reference-index.json` 作为唯一路由来源。

OumuQ 正在运行时，优先通过 OumuQ 路由，通常是 `http://127.0.0.1:8780`。直接 worker 调用只作为调试 fallback，或在路由层不可用时使用。

## 路由选择

1. 通过 `id`、`name` 或显示字段查找请求的角色。
2. 使用 `speech_language` 作为音频语言，使用 `visible_language` 作为屏幕文本语言。
3. 使用 `tts_engine` 选择 worker URL。
4. 优先把 `character_id` 传给 OumuQ 或 worker，而不是在每个请求里嵌入已解析的 provider 细节。
5. 生成音频、prompt composites、缓存和日志都要放在 `voice-references` 外面。

与 `character-dialogue-workflow` 一起使用时，需要路由两段文本：发送给 TTS 的语音语言文本，以及 `queued` 后显示的可见语言文本。两段文本都必须保持同一个角色口吻和意图。先把语音文本提交给 OumuQ `POST /api/speak`，等 OumuQ/worker 接受任务后再显示可见文本。

建议 engine key：

- `ONNX-VITS`：本地固定多说话人极速 worker，默认 `http://127.0.0.1:8764`；角色用 `onnx_vits_speaker` 绑定固定声线，不读取参考音频。
- `Qwen3-TTS`：本地多语言 worker。
- `IndexTTS2`：本地中文/克隆 worker。

## 会话隔离与串行播放

- 当前角色属于调用方会话，不属于 OumuQ 或 worker 进程。
- 每个会话保留不透明 `session_id`，并在每次参数推理、路由解析和语音请求中发送 `session_id + character_id`。
- `worker_url` 是共享引擎地址。不能因为另一个会话选择不同角色而重启它。
- `status.character_id` 只能视为 legacy 启动默认值或诊断字段。
- OumuQ 是唯一播放所有者：下游 worker 收到 `play=false`，生成可以并行，最终 WAV 按路由提交序号进入同一个 FIFO。
- 播放顺序用 `GET /api/playback/status` 检查；任何两条 OumuQ 语音都不得叠加。
- direct worker fallback 只有在 worker 支持逐请求解析 `character_id` 时才能共享；否则给 legacy 角色分配独立端口。

## 云端声线字段

云端 API 角色可以包含：

- `api_voice_id`
- `api_clone_audio_url`
- `api_target_model`（规范字段）
- `api_clone_target_model`（仅旧数据兼容）
- `api_clone_language_hint`
- `api_voice_instructions`
- `send_instructions_by_default`

公开仓库中这些值应该是占位符。真实值应保存在本地副本、部署 secret store 或私有配置中。

## OumuQ 路由层

有用的本地 endpoint：

- `GET /api/config`：确认 OumuQ 路由层配置。
- `GET /api/characters`：列出已解析的注册角色。
- `GET /api/tts-model-capabilities`：暴露 canonical 字段和特定模型支持/降级规则。
- `POST /api/infer-parameters`：不生成音频，只推断高层请求参数。
- `POST /api/speak`：向选中的 worker 提交一句发言。
- `GET /api/worker/status`：通过 OumuQ 检查 worker 状态。
- `GET /api/playback/status`：检查单进程 FIFO 与主机级播放互斥；禁止叠音，但不宣称多个 OumuQ 进程共享 FIFO 顺序。

AI client 如果知道 canonical intent 字段，应发送这些字段：

- correlation：`session_id`
- identity：`character_id`、`speaker`、`speaker_id`、`model`、`worker_url`
- content：`text`、`language`、`visible_language`、`speech_language`
- style：`emotion_mode`、`emotion_alpha`、`emotion_tags`、`emotion_vector`、`emotion_text`、`instructions`、`send_instructions`
- prosody：`volume`、`speech_rate`、`pitch_rate`、`speed`
- reference：`prompt_audio`、`prompt_audios`、`ref_text`、`reference_audio_url`
- routing：`match_patterns`、`character_folder`

不支持但无害的字段应由 OumuQ/workers 降级或忽略，不应变成致命错误。对于云端 CosyVoice 克隆声线，`emotion_vector` 是高层意图，可能映射为 `instructions`、`speech_rate`、`pitch_rate` 和 `volume`。

## 绘图模式

如果图像生成工作流使用同一个角色，只读取公开安全的 visual 字段，例如：

- `visual_profile.id`
- `visual_profile.prompt_profile`
- `visual_profile.safety_note`

不要把声线来源转换成视觉身份。声线来源、真实说话人身份、私有参考文件和云端 URL 都不是图像提示词素材。
