---
name: character-dialogue-workflow
description: 当 Agent 回复需要在屏幕和语音里都完整保持角色时使用。先把语音提交给 OumuQ 兼容的常驻 TTS worker，等待 queued 成功后再显示可见文本，并在屏幕语言和语音语言不同时保留角色语气。
---

# 角色对话工作流

这个公开 skill 模板用于需要同时输出屏幕文本和语音的 Agent 回复。

屏幕文本也是表演的一部分。不要屏幕上写中性的 Codex/Agent 答案，只让音频像角色。

## 工作流

如果用户只用一个角色名调用这个 skill，就把它视为进入该角色对话模式的请求。

1. 为当前 Agent 会话保留不透明 `session_id`，并从 `voice-references/reference-index.json` 解析该会话的 `character_id`。
2. 如果角色 README 存在，先读取它。
3. 用 `visible_language` 写屏幕可见回复，并完整保持当前角色口吻。
4. 用 `speech_language` 写匹配的语音文本。如果两种语言不同，翻译含义而不是逐字翻译，并保留相同意图、情绪、关系姿态和角色语气。
5. 用本地 HTTP `POST /api/speak` 把语音文本提交给 OumuQ。
6. 把 `queued` 视为成功，然后再显示屏幕文本。
7. 让选中的 worker 在 OumuQ 后面异步生成和播放音频。

对话模式下，不要为每句普通发言启动新的 shell 进程。保持 OumuQ 和一个兼容 worker 运行，然后提交轻量本地 HTTP 请求。只有 OumuQ 不可用或被明确绕过时，才 fallback 到直接 worker `POST /speak`。

## 对话一致性

OumuQ 是角色优先的 TTS 工作流，不是“中性助手回复 + 声音滤镜”。当对话模式启用时：

- 可见的 Codex 或 Agent 回复从第一句到最后一句都必须在角色中。
- 语音文本和屏幕文本应像同一个角色用两种语言表达同一想法。
- 如果 `speech_language` 和 `visible_language` 不同，翻译含义时要尽量保留角色语气、礼貌程度、句子节奏、温度、调侃感、正式程度和常用称呼。
- 不要把角色特有表达压平成普通助手总结。
- 技术准确性、安全边界和拒绝规则仍然适用，但应通过当前角色的方式表达，而不是脱离角色。
- 如果用户纠正表演方向，把这个纠正作为同一对话模式后续可见文本和语音文本的有效指导。

例如，语音是日语、可见文本是中文时，可见中文应是日语含义的角色化中文呈现，而不是对日语台词的平淡解释。

## 角色解析

用用户提供的名字匹配这些注册字段：

- `id`
- `name`
- `display_name`
- `display_name_zh`
- `style_summary`
- `style_summary_zh`

当注册表条目已经匹配时，不要开始大范围文件搜索。如果没有条目匹配，只问用户要使用哪个本地角色 id；不能从 worker status 猜测当前会话角色。

OumuQ 运行时，把它作为路由层。`worker_url` 是共享服务地址；每次请求由 `character_id` 决定声线。健康检查只确认 readiness，绝不能因为 status 显示另一个默认角色而重启共享 worker。

## 多会话与播放

会话 A/B 各自持有 `session_id` 和 `character_id`，每次请求都显式发送。OumuQ 不保存全局当前角色。worker 静默生成；单一 OumuQ 进程内按提交序号 FIFO 播放，主机级互斥锁保证多个进程也不叠音。`queued` 表示生成已接受，不表示可以绕过本进程前面的播放序号或主机播放锁。

## 请求形状

```json
{
  "text": "Speech-language text to submit to TTS.",
  "play": true,
  "session_id": "opaque-session-id",
  "character_id": "cloud_zh_voice",
  "language": "Chinese"
}
```

优先 endpoint：

```http
POST http://127.0.0.1:8780/api/speak
```

可选预检 endpoint：

```http
GET  http://127.0.0.1:8780/api/config
GET  http://127.0.0.1:8780/api/characters
GET  http://127.0.0.1:8780/api/tts-model-capabilities
POST http://127.0.0.1:8780/api/infer-parameters
```

`/api/infer-parameters` 可以在 `/api/speak` 前推断高层 TTS 控制参数；它不会生成音频。

可选字段：

- `emotion_tags`
- `emotion_vector`
- `emotion_mode`
- `emotion_alpha`
- `emotion_text`
- `match_patterns`
- `ref_text`
- `instructions`
- `send_instructions`
- `speech_rate`
- `pitch_rate`
- `volume`

只有目标 provider 和声线已经验证过 provider-side instructions 时，才设置 `send_instructions`。对于云端 CosyVoice 克隆声线，由于不能保证原生支持逐请求 emotion vector，OumuQ/worker 可能会把高层情绪意图降级成 provider instructions 和韵律字段。

## 公开安全

这个模板必须保持通用：

- 不要硬编码私有角色名。
- 不要包含真实 voice id 或 clone URL。
- 不要包含 API key、个人路径、服务器 IP、cookie 或 token。
- 私有角色细节只放在用户本地的 `voice-references` 副本里。
