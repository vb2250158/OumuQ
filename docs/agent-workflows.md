# Agent 与多模态工作流

OumuQ 的目标不是把某个私有角色写死进项目，而是提供一套可以复用的角色路由契约。Agent、TTS worker 和绘画模式都应读取同一份已脱敏的角色配置，再把私有资产留在本地副本或部署环境里。

## 统一角色入口

公开仓库只保留通用角色 id 和示例字段：

```json
{
  "id": "cloud_zh_voice",
  "tts_engine": "Qwen-TTS-API",
  "speech_language": "Chinese",
  "visible_language": "Chinese",
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "visual_profile": {
    "id": "generic_companion_visual",
    "prompt_profile": "A public, original companion character design."
  }
}
```

本地私有副本可以填入真实音色、真实参考音频、私有视觉参考和更细的人格说明。公开仓库不要提交这些值。

## 对话语音流程

实时对话应使用常驻 worker：

```text
Agent 生成角色化可见文本和语音文本
  -> 选择 character_id
  -> 本地 HTTP POST /speak 提交语音文本
  -> worker 立即返回 queued
  -> Agent 显示角色化可见文本
  -> worker 后台生成并顺序播放
```

这样 Agent 不需要为每句话启动 PowerShell 或 Python 进程。`202 queued` 或同等的 queued 响应即代表提交成功。

可见文本和语音文本都必须保持角色扮演语气。若 `speech_language` 和 `visible_language` 不同，先确定语音实际要说的文本，再把它的含义翻译成屏幕语言；翻译时保留角色的礼貌程度、称呼方式、亲疏关系、调侃或温柔感。不要让屏幕文字变成普通 Codex/Agent 的摘要。

安全、准确性和拒绝边界仍然生效，但应在角色语气里表达。例如不能满足的请求也应由角色自然地说清楚原因和可替代方向，而不是突然切换成系统说明。

推荐请求：

```json
{
  "text": "这里是语音实际要说出来的文本。",
  "play": true,
  "character_id": "cloud_zh_voice",
  "language": "Chinese"
}
```

当云端克隆音色需要固定 `voice_id` 时，优先让 worker 用 `--character-id cloud_zh_voice` 从 `voice-references/reference-index.json` 读取本地配置。Agent 侧只传 `character_id`，避免把 provider 细节散落在每个调用里。

## 绘画模式流程

绘画模式可以复用同一个 `character_id`，但只读取适合公开和生成图像的视觉字段：

```text
Agent 绘画请求
  -> 选择 character_id
  -> 读取 visual_profile
  -> 合成图像提示词
  -> 调用图像生成或绘画工具
```

`visual_profile.prompt_profile` 应描述原创、可发布的视觉方向，不应包含：

- 真实角色名或私有昵称
- 私有参考图路径
- 第三方版权角色名
- 音色提供者、真人身份或账号信息
- 云端文件 URL、签名 URL 或内部对象存储路径

语音人格和视觉设定可以共享一个抽象角色，但不要把“音色来源”当作“视觉身份”。这能让开源项目保留工作流，同时降低泄露和授权风险。

## Skill 配套

`skills/` 目录里放的是公开版 Agent skill 模板。它们只描述契约和操作顺序：

- `character-dialogue-workflow`：每个可见回复先提交语音，再显示文字。
- `oumuq-character-creator`：创建或更新角色条目、角色 README、`voice-index.json` 和公开安全的云端/视觉占位字段。
- `tts-router-workflow`：从 `voice-references` 选择角色、语言、worker 和参考字段。
- `qwen-api-tts-worker`：云端 API worker 的通用启动和脱敏配置方式。
- `qwen-voice-language-training`：在克隆音色或跨语种说话前确认参考语料语言、目标语音语言和口音取舍。

私有 Codex 环境可以有更具体的 skill，例如固定某个本地端口、私有角色或真实音色 ID。发布到 OumuQ 时应改成占位符和通用字段。

安装到 Codex 的步骤见 [codex-skill-install.md](codex-skill-install.md)。新用户完成安装后，可以在新的 Codex 会话里直接要求使用这些 skill 进入 OumuQ 角色语音模式。

## 脱敏边界

可以公开：

- 通用字段名和契约
- 占位角色 id
- 示例 JSON
- mock worker 和接口测试
- 不含真实音频的 `.gitkeep`

不要公开：

- API key、cookie、token
- 真实 `voice_id`
- 真实克隆参考音频 URL
- 个人路径、服务器 IP、对象存储桶名
- 真实参考音频、生成音频和 worker 日志
- 私有角色名、私有称呼、不可公开的角色口癖或视觉参考
