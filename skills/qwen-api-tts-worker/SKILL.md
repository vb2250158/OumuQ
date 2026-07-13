---
name: qwen-api-tts-worker
description: 当需要运行或记录一个 OumuQ 兼容的阿里云百炼 / DashScope 云端 TTS worker 时使用。支持真正的 Qwen 声音设计、经授权的声音复刻、动态多角色和全局串行播放。
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

按 provider/engine 运行一个共享的长生命周期 worker，并让每次请求独立选择角色：

```text
Agent -> http://127.0.0.1:8767/speak -> worker -> cloud TTS provider
```

`POST /speak` 应该快速返回一个 queued job object。生成和播放继续在 worker 内进行。

## 多会话契约

- 会话角色由调用方拥有，每次 `POST /speak` 都携带 `character_id`。
- `--character-id` 只提供 legacy 默认值。
- 每个 job 必须快照本次角色的 voice、model、language hint 和 instructions。
- 显式角色缺少云端音色时应报错，不能借用启动角色音色。
- OumuQ 默认接管播放；worker 收到 `play=false` 并只负责生成。
- 所有角色最终 WAV 在单一 OumuQ 进程内按 FIFO 播放，并由主机级互斥锁保证多个进程也不叠音；不宣称跨进程 FIFO 顺序。
- 可执行源码随 `qwen-tts-api` Skill 安装。

## 配置

密钥使用环境变量：

```powershell
$env:DASHSCOPE_API_KEY = "..."
```

完成报告必须区分三层：服务商为阿里云百炼，API 为 DashScope，`Qwen-TTS-API` 是本地 OumuQ worker 名；真实模型单独写出。

默认使用不提交参考音频的 Qwen 声音设计：

```json
{
  "id": "cloud_designed_voice",
  "tts_engine": "Qwen-TTS-API",
  "api_voice_creation_method": "voice_design",
  "api_enrollment_model": "qwen-voice-design",
  "api_target_model": "qwen3-tts-vd-2026-01-26",
  "api_voice_prompt": "<original-voice-description>",
  "api_voice_preview_text": "<original-preview-text>",
  "api_voice_design_language": "zh",
  "send_instructions_by_default": false
}
```

只有用户明确确认拥有云端声音克隆权利时，才使用：

- `qwen-voice-enrollment` 与完全匹配的 `qwen3-tts-vc-*`。
- Qwen 可以提交公网 URL 或在本机受控编码的 Data URL。
- CosyVoice 的 `voice-enrollment` 需要 provider 可访问 URL，完成报告必须写真实 `cosyvoice-*` 模型。

声音设计/复刻完成后，真实 `api_voice_id` 只保存在本机私有注册表。每个 job 必须快照角色、模型、语言和创建方式；不能借用其他会话的音色。

不要发布 API key、voice ID、Data URL、签名 URL、服务器地址、个人路径或参考音频。最终可见报告只显示 voice 是否已配置。

## 指令

Qwen3-TTS-VC/VD 不支持 provider-side instruction control；不要向它们发送 CosyVoice 的音量、语速、音调或 instructions 字段。只有目标模型明确支持并已验证时才发送。Agent 文本在提交前仍然应该遵循角色风格。

完成后用中文报告服务商、DashScope API、OumuQ 引擎、实际模型、声音设计/复刻方式、角色 ID、语言、WAV 验证状态，以及“OumuQ 进程内 FIFO + 主机级播放互斥、不叠音”。使用 `play=false` 时只能报告策略已验证，不能声称实际扬声器播放已测试。
