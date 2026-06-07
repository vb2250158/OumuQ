---
name: oumuq-character-creator
description: 创建或更新 OumuQ 的 voice-references 角色条目，包括角色文件夹、README.md、voice-index.json、reference-index.json 记录、本地/私有声线字段、云端克隆占位符、worker 路由、语言设置和公开安全的 visual_profile 元数据。当用户要求创建、添加、注册、脚手架化新的 OumuQ 角色、语音角色、人格、voice-reference 条目或对话模式角色时使用。
---

# OumuQ 角色创建器

使用这个 skill 在 OumuQ workspace 中创建或更新角色。

目标是产出可用的 `voice-references` 角色条目，同时避免把私有声线数据泄露进公开仓库。

## 输入

收集或推断：

- `character_id`：稳定的小写 id，例如 `cloud_zh_voice` 或 `jp_companion`。
- 显示名称：`name`、`display_name` 和/或 `display_name_zh`。
- `tts_engine`：通常是 `Qwen-TTS-API`、`Qwen3-TTS` 或 `IndexTTS2`。
- `speech_language`：TTS 实际说出的语言。
- `visible_language`：展示给用户看的语言。
- 角色风格：简洁的人格、语气、称呼方式和对话边界。
- Worker URL：除非用户提供其他本地 URL，否则使用 OumuQ 约定。
- 声线来源状态：本地参考音频、已有云端 `api_voice_id`、待克隆 URL，或仅占位符。
- 公开/私有目标：本次编辑是给公开仓库示例，还是给用户本地私有 `voice-references`。

如果用户只给出角色概念，选择保守默认值并创建占位符。不要索要密钥。

## 文件目标

使用本地 workspace 路径：

```text
voice-references/reference-index.json
voice-references/characters/<character_id>/README.md
voice-references/characters/<character_id>/voice-index.json
voice-references/characters/<character_id>/audio/.gitkeep
```

如果 `voice-references` 不存在但 `voice-references.example` 存在，询问用户是否需要一份私有本地副本。公开模板只编辑 `voice-references.example`。

除非用户明确为私有本地副本提供了授权参考音频，否则不要把生成音频、缓存文件、worker 日志或 clone samples 放进 `voice-references`。

## 工作流

1. 检查现有 `voice-references/reference-index.json` 或 `voice-references.example/reference-index.json`。
2. 确保 `character_id` 唯一。如果条目已存在，更新它，不要重复创建。
3. 创建角色文件夹和 `audio/.gitkeep`。
4. 编写 `README.md`，作为对话模式的主要风格指南。
5. 编写 `voice-index.json`，包含公开元数据或本地授权参考元数据。
6. 通过 JSON 解析编辑 `reference-index.json` 的 `characters` 数组，并保持合法 JSON。
7. 对所有改过的 JSON 文件运行解析检查。
8. 如果 OumuQ 正在运行，在适用时重启或刷新后验证 `GET /api/characters` 能看到该角色。
9. 只有 skill 本身发生变化时才安装更新后的 skills；创建角色不需要重新安装 skills。

编辑 `reference-index.json` 时使用结构化 JSON 解析，不要用正则替换。

## 参考条目形状

基础角色条目：

```json
{
  "id": "my_character",
  "name": "My Character",
  "display_name": "My Character",
  "display_name_zh": "我的角色",
  "character_folder": "voice-references/characters/my_character",
  "index_file": "voice-references/characters/my_character/voice-index.json",
  "fallback_prompt_audio": "voice-references/characters/my_character/audio/sample.wav",
  "tts_engine": "IndexTTS2",
  "worker_url": "http://127.0.0.1:8766",
  "speech_language": "Chinese",
  "visible_language": "Chinese",
  "style_summary": "Warm, clear, conversational delivery.",
  "style_summary_zh": "温和、清晰、自然对话感。"
}
```

推荐 worker URL：

- `Qwen3-TTS`：`http://127.0.0.1:8765`
- `IndexTTS2`：`http://127.0.0.1:8766`
- `Qwen-TTS-API`：`http://127.0.0.1:8767`
- OumuQ 路由层：`http://127.0.0.1:8780`

## 云端 API 角色

对于 `tts_engine = "Qwen-TTS-API"`，添加公开安全的云端字段：

```json
{
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "api_clone_target_model": "cosyvoice-v3-plus",
  "api_clone_language_hint": "zh",
  "api_voice_instructions": "Use a natural conversational delivery. Keep the tone warm and clear.",
  "send_instructions_by_default": false
}
```

在私有本地副本中，如果用户选择保存在那里，可以存放真实 `api_voice_id` 和 clone URL。公开仓库里必须保留占位符。

CosyVoice 克隆样本优先使用 15-20 秒，并且需要 provider 可访问的 URL。像 `<local-reference-audio-path>` 这样的本地路径不足以完成云端注册。

## 本地参考音频角色

对于 `IndexTTS2` 或 `Qwen3-TTS`，使用本地授权参考音频：

```json
[
  {
    "id": "warm_001",
    "audio_file": "voice-references/characters/my_character/audio/warm_001.wav",
    "text": "Reference transcript.",
    "language": "Chinese",
    "mood": "warm",
    "emotion_tags": ["warm", "clear"],
    "emotion_vector": [0.35, 0, 0, 0, 0, 0, 0.02, 0.3],
    "match_patterns": ["hello|thanks|warm"],
    "style_notes": "Authorized local reference audio."
  }
]
```

如果暂时没有音频，创建空数组形式的 `voice-index.json`，或创建不含 `audio_file` 的 metadata-only 示例。不要编造不存在的音频路径，除非该条目明确是占位符。

## 角色 README

让 `README.md` 简洁，并对对话模式有用：

- 角色用途和公开/私有说明。
- 说话风格和情绪范围。
- 安全时可写称呼方式和常用表达。
- `speech_language` 和 `visible_language`。
- TTS engine 和 worker 预期。
- 声线/参考音频状态。
- 安全边界：不要模仿、泄露或发布什么。

不要包含真实说话人身份、私有角色名、受版权保护的角色来源、API key、cookie、token、私有服务器 URL 或未授权参考链接。

## Visual Profile

如果用户也需要绘图模式，只添加公开安全的 visual 字段：

```json
{
  "visual_profile": {
    "id": "generic_companion_visual",
    "prompt_profile": "A public, original companion character design.",
    "safety_note": "Do not reference private characters, private names, copyrighted characters, real voice owners, or private reference images."
  }
}
```

不要把声线来源转换成视觉身份。

## 公开安全

公开 OumuQ 示例可以包含：

- 通用角色 id。
- 云端字段占位符。
- 公开安全的风格摘要。
- Metadata-only 的 voice-index 示例。
- `audio/` 里的 `.gitkeep`。

公开 OumuQ 示例不能包含：

- 真实 `api_voice_id`、API key、cookie 或 token。
- 真实 clone URL 或签名对象存储链接。
- 个人机器路径。
- 私有角色名或私有称呼方式。
- 未授权第三方音频、生成输出音频、worker 缓存或日志。
- 会暴露受保护身份的私有视觉参考或提示词。

## 验证

编辑后：

```powershell
Get-Content -Raw -Encoding utf8 voice-references\reference-index.json | ConvertFrom-Json | Out-Null
Get-Content -Raw -Encoding utf8 voice-references\characters\<character_id>\voice-index.json | ConvertFrom-Json | Out-Null
```

公开示例要对 `voice-references.example` 运行同样检查。

如果存在测试，运行覆盖角色加载或路由配置的聚焦 OumuQ 检查。
