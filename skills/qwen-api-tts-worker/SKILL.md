---
name: qwen-api-tts-worker
description: 当需要运行或记录一个 OumuQ 兼容的 Qwen/DashScope 云端 TTS API worker 时使用。支持可选克隆声线，并使用公开安全的占位符配置。
---

# Qwen API TTS Worker

这个公开模板用于暴露 OumuQ worker contract 的云端 TTS worker：

```text
GET  /health
GET  /status
GET  /status/<job_id>
POST /speak
```

## 必需运行模式

为当前角色运行一个长生命周期 worker，然后提交本地 HTTP 请求：

```text
Agent -> http://127.0.0.1:8767/speak -> worker -> cloud TTS provider
```

`POST /speak` 应该快速返回一个 queued job object。生成和播放继续在 worker 内进行。

## 配置

密钥使用环境变量：

```powershell
$env:DASHSCOPE_API_KEY = "..."
```

非密钥路由使用本地角色元数据：

```json
{
  "id": "cloud_zh_voice",
  "tts_engine": "Qwen-TTS-API",
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "api_clone_target_model": "cosyvoice-v3-plus",
  "send_instructions_by_default": false
}
```

## 声音克隆

云端 voice enrollment 通常需要 provider 可访问的参考音频 URL。除非已经上传到公开或签名 URL，否则 `voice-references` 下的本地文件并不足够。

注册克隆声线时，如果 provider 支持，传入参考音频语言提示，例如日语用 `language_hints: ["ja"]`，中文用 `language_hints: ["zh"]`。合成时，每次请求也要传入当前语音文本的语言提示。即使克隆是用日语参考音频注册的，如果后续合成省略 `ja`，让 provider 猜语言，也可能导致发音错误。

不要发布：

- 真实 API key。
- 真实 `voice_id`。
- 真实 clone URL。
- 服务器 IP 或 bucket 名称。
- 个人参考音频。

## 指令

部分克隆声线在发送 provider-side `instructions` 时可能失败或不稳定。在特定 provider、model 和 voice 测试通过之前，保持 `send_instructions_by_default` 为 false。Agent 文本在提交前仍然应该遵循角色风格。
