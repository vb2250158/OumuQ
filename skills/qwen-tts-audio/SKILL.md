---
name: qwen-tts-audio
description: 使用本地 Qwen3-TTS 常驻 worker 生成日语或多语言语音，并按请求从 voice-references 选择不同角色、参考音频和情绪参数。适用于多个会话共享同一 worker。
---

# Qwen TTS Audio

使用本地 Qwen3-TTS 常驻 worker。worker 脚本和参考音频解析器都随本 Skill 安装：

- `%USERPROFILE%\.codex\skills\qwen-tts-audio\scripts\qwen_tts_worker.py`
- `%USERPROFILE%\.codex\skills\qwen-tts-audio\scripts\voice_reference.py`

## 多会话规则

- 一个常驻 worker 可以接收不同会话、不同 `character_id` 的交错请求。
- 每个 job 在提交阶段独立解析角色目录、voice index、参考音频、语言和生成参数。
- 当前角色属于调用方会话，不属于 worker 全局状态。
- 每次请求必须显式发送当前会话的 `character_id`；不要依赖上一条请求。
- 不要因为另一个会话切换角色而重启共享 worker。
- `session_id` 可用于直接 worker 调试记录；经 OumuQ 时由 OumuQ 自己保存关联记录。

如果旧 worker 只能固定单一 prompt audio，应给不同角色分配独立端口，不能反复重启共享端口。

## 启动

从拥有缓存与输出目录的工作区启动：

```powershell
$worker = Join-Path $env:USERPROFILE '.codex\skills\qwen-tts-audio\scripts\qwen_tts_worker.py'
Start-Process -FilePath '<qwen-python>' -ArgumentList @(
  '-X','utf8',
  $worker,
  '--workdir',(Get-Location).Path,
  '--model','<model-or-snapshot>',
  '--host','127.0.0.1',
  '--port','8765',
  '--max-new-tokens','192'
) -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru
```

`<qwen-python>` 和模型位置属于本机配置，不要写死到公开 Skill。

## 请求

优先经 OumuQ：

```json
{
  "session_id": "session-a",
  "character_id": "jp_companion",
  "text": "こんばんは。",
  "language": "Japanese",
  "play": true,
  "emotion_tags": ["warm"],
  "match_patterns": ["greeting"]
}
```

直接 worker fallback 也可以额外传：

- `character_folder`
- `prompt_audio` / `prompt_audios`
- `emotion_vector`
- `ref_text`
- `max_new_tokens`

## 参考音频隔离

worker 在每个请求中从该角色的 `voice-index.json` 选择参考音频，并把选择结果写入 job 快照。角色请求没有显式 `ref_text` 时，不继承进程启动时属于另一个角色的 `--ref-text`；它会使用安全的 x-vector-only 模式。只有不带角色身份的 legacy 请求才可使用进程默认 `ref_text`。

生成音频、组合 prompt、缓存和日志都必须位于工作区输出目录，不能写回 `voice-references`。
