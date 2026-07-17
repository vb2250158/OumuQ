---
name: qwen-tts-api
description: 通过阿里云百炼 / DashScope 的 Qwen TTS API 生成语音，并让一个常驻 worker 按请求在多个角色与会话之间安全切换。支持 Qwen 声音设计、个人非商业用途的声音复刻、已有 voice_id 和 OumuQ 全局串行播放。
---

# Qwen TTS API

用于 Qwen Cloud / DashScope 的 OumuQ 兼容常驻 worker。

## 首选链路

```text
会话 A / 角色 A ─┐
会话 B / 角色 B ─┼─> OumuQ :8780 ─> 共享 Qwen API worker :8767
会话 C / 角色 A ─┘
```

- 保持一个按 provider/engine 共享的长生命周期 worker。
- 每次请求都显式携带当前会话的 `character_id`。
- OumuQ 每次从 `voice-references/reference-index.json` 解析 `voice_id`、模型、语言提示和发声说明。
- `--character-id` 只是无 `character_id` 请求的兼容默认值，不是 worker 的全局当前角色。
- 不要因为另一个会话使用不同角色而重启共享 worker。

worker 脚本：

`%USERPROFILE%\.codex\skills\qwen-tts-api\scripts\qwen_tts_api_worker.py`

## 会话隔离

当前角色归调用方会话所有，不归 worker 所有。推荐每次请求同时发送：

```json
{
  "session_id": "opaque-session-id",
  "character_id": "cloud_zh_voice",
  "text": "你好。",
  "play": true
}
```

worker 会在提交时为每个 job 独立快照：

- `character_id` 与可选 `session_id`
- `voice` / `voice_id`
- 模型
- 语言与 `language_hint`
- `instructions` / `send_instructions`
- 音量、语速和音调（仅向实际支持这些参数的模型发送）

显式携带 `character_id` 时，本次角色注册表中的 `api_voice_id` 与 `api_target_model` 是权威值，必须忽略请求里残留或恶意注入的 `voice`、`voice_id`、`model`；只有没有显式角色的 legacy 路径允许请求覆盖。模型字段优先读取 `api_target_model`，`api_clone_target_model` 只作为兼容别名。显式角色缺少 `api_voice_id` 时必须报错：即使角色条目已经包含完整声音设计/复刻参数，`POST /speak` 也不得临时注册音色；应先通过 OumuQ 的显式注册流程完成注册和持久化，避免生成请求超时、重复计费或产生孤立音色。普通 Qwen 模型不发送 CosyVoice 的音量、语速和音调字段，只有模型 ID 明确为 `qwen3-tts-instruct-*` 时才发送 instructions。

## 启动

密钥只从环境变量读取：

- `DASHSCOPE_API_KEY`
- `QWEN_API_KEY`

```powershell
$worker = Join-Path $env:USERPROFILE '.codex\skills\qwen-tts-api\scripts\qwen_tts_api_worker.py'
Start-Process -FilePath 'py' -ArgumentList @(
  '-X','utf8',
  $worker,
  '--workdir',(Get-Location).Path,
  '--host','127.0.0.1',
  '--port','8767',
  '--base-url','https://dashscope.aliyuncs.com',
  '--model','qwen3-tts-flash',
  '--language','Chinese',
  '--no-play'
) -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
```

健康检查：

```powershell
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8767/status'
```

`/status.character_id` 只是启动默认角色的诊断信息。会话角色必须来自本次请求，不能从 status 推断。

## 注册表字段

完成报告必须把 OumuQ worker 名与真实模型分开：`Qwen-TTS-API` 是本地兼容 worker；服务商是阿里云百炼，API 是 DashScope；实际模型优先由规范字段 `api_target_model` 决定，旧数据才回退 `api_clone_target_model`。

Qwen 声音设计（仅在用户明确要求原创音色时使用，不提交参考音频）：

- `api_voice_creation_method: voice_design`
- `api_enrollment_model: qwen-voice-design`
- `api_target_model: qwen3-tts-vd-2026-01-26`
- `api_voice_prompt`
- `api_voice_preview_text`
- `api_voice_design_language: zh`

Qwen 声音复刻（用户说明个人非商业用途并要求克隆时使用）：

- `api_voice_creation_method: voice_cloning`
- `api_enrollment_model: qwen-voice-enrollment`
- `api_target_model: qwen3-tts-vc-2026-01-22`
- `api_clone_audio_url`，或仅保存在本机私有配置中的 `api_clone_audio_path`
- `api_clone_reference_text`
- `api_clone_reference_language`

角色创建上游应先把可用参考音频提取到本机私有目录。用户要求“千问版”或声音克隆时，优先把本地样本编码为 Data URL 直接提交百炼 API；不需要 GitHub、公开 URL 或公网对象存储。只有明确拒绝提交给阿里云百炼或确实没有可用样本时才停止云端注册。不得把“不上传 GitHub/公网”解释为“不提取本地音频”或“不允许通过受控 API 提交”，也不得自行选择声音设计作为 fallback。

注册完成后保存 `api_voice_id` 和规范字段 `api_target_model`；不要给新条目只写兼容别名 `api_clone_target_model`。注册过程有进程内锁，同一配置的并发注册只创建一次音色；显式携带 `character_id` 的 `/speak` 热路径不得触发注册。

CosyVoice 也可由此 worker 调用，但完成报告必须写实际 `cosyvoice-*` 模型，不得称为 Qwen3-TTS。

## 直接请求

优先经 OumuQ `POST /api/speak`。只有路由层不可用时才直接调用 worker；直接调用也必须携带 `character_id`：

```json
{
  "text": "こんにちは。",
  "session_id": "session-b",
  "character_id": "cloud_jp_voice",
  "play": true
}
```

## 播放与完成报告

经 OumuQ 调用时让 worker 保持 `play=false`，由单一 OumuQ 进程的 FIFO 逐条播放，并由主机级互斥锁避免多个 OumuQ 进程叠音。worker 建议用 `--no-play` 启动，避免绕过统一播放入口。

完成后用中文说明：服务商、DashScope API、OumuQ 引擎、真实模型 ID、`voice_design` / `voice_cloning` / 预设音色、角色 ID、语言、WAV 验证状态，以及“进程内 FIFO + 主机级播放互斥”。不要在可见报告中显示真实 voice ID；`play=false` 不得报告为实际播放已测试。

## 公开安全

不要把真实 API key、私有 voice_id、签名 URL、个人路径、参考音频或生成音频提交到 Git/GitHub、公开 URL、可见报告或公共响应。克隆所需参考音频可以在请求内以 Data URL 直接提交给百炼 API，但不得落入日志或缓存。其他真实值只留在本地注册表、环境变量或部署密钥中。`/status`、`/status/<job_id>`、`POST /speak` 响应和启动日志只能返回 `voice_configured` 布尔值，不能返回 voice ID；API 失败也只能报告状态码、provider code、request ID 和字段名等安全元数据，不能透传完整响应。

运行缓存也必须使用安全视图：`job.json` 不得保存 `voice` / `voice_id`；分块 metadata 的 settings 只保存 `voice_configured`；provider response 必须递归移除 voice ID、音频 Data URL/base64、音频 URL 和签名/私有 URL，只保留状态、模型、request ID 等诊断字段。生成请求所需的真实值只保留在进程内存中，不要为了迁移而自动改写或删除历史缓存。
