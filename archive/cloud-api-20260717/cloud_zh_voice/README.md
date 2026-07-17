# 云端中文语音示例

这是一个已脱敏的云端 API 语音角色示例，用来说明 OumuQ 如何把角色配置、TTS API worker 和绘画模式共用起来。

## 语音风格

- 温和、清晰、自然对话感。
- 不使用播音腔或过强表演腔。
- 屏幕文字和语音文字都使用中文。

## API 音色

本示例不会提交真实 `voice_id`、真实参考音频 URL 或任何 API key。

在本地副本里可以填写：

- `api_voice_id`：已有云端克隆音色 ID。
- `api_clone_audio_url`：公开或签名的参考音频 URL，用于首次注册音色。
- `api_clone_target_model`：云端克隆目标模型。
- `api_voice_instructions`：可选的自然语言发声说明。

如果某个 provider 对 `instructions` 不稳定，把 `send_instructions_by_default` 保持为 `false`，只在 Agent 文本层塑造角色语气。

## 绘画模式

`visual_profile` 只描述公开、原创、可发布的视觉方向。不要在公开仓库写真实角色名、私有参考图、版权角色或个人身份线索。
