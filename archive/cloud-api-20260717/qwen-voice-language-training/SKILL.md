---
name: qwen-voice-language-training
description: 当需要规划 Qwen/DashScope 克隆声线注册、语言提示，或处理跨语言语音时使用，例如日语参考音频说中文。尤其适用于用户还没有明确想要的语音语言和口音取舍时。
---

# Qwen 声线语言训练

当参考音频语言、屏幕回复语言和期望语音语言可能不同时，在注册或使用 Qwen/DashScope 克隆声线前使用这个 skill。

## 第一个决策

先分清三个值：

- `reference_audio_language`：克隆参考音频里实际说的语言。
- `speech_language`：TTS 输出应该说的语言。
- `visible_language`：作为文本/字幕展示给用户的语言。

如果用户没有清楚选择 `speech_language`，并且目标语言不同于参考音频语言，克隆或合成前要先问。问题保持简短：

```text
参考音频是日语。你希望生成语音也说日语，还是保留音色但改说中文？后者可能更容易有跨语种口音。
```

如果询问不现实，且没有确认目标语言，默认使用参考音频语言。日语参考音频默认生成日语语音；需要时可以使用中文屏幕文本/字幕。

## Qwen API 语言提示

对于 Qwen/DashScope 克隆声线，在两个阶段都传入语言提示：

1. 声线注册 / clone registration：设置参考音频语言，例如 `language_hints: ["ja"]`。
2. 语音合成：每次请求都设置当前文本语言，例如日语语音用 `language_hints: ["ja"]`，中文语音用 `language_hints: ["zh"]`。

不要假设本地元数据里的 `speech_language: "Japanese"` 就足够。worker 应该在调用 provider 前，把它映射成 provider language hint，例如 `ja`、`zh`、`en`。

## 同语言克隆

当用户希望角色用参考音频的同一种语言说话时，使用这个方案。

推荐配置：

```json
{
  "tts_engine": "Qwen-TTS-API",
  "speech_language": "Japanese",
  "visible_language": "Chinese",
  "api_clone_language_hint": "ja",
  "api_target_model": "cosyvoice-v3-plus"
}
```

运行时规则：

- 把日语语音文本发送给 `/speak`。
- 合成时发送或推导 `language_hints: ["ja"]`。
- 如果用户需要中文可见对话，单独显示中文文本。

这是只有日语参考音频时最安全的默认方案。

## 跨语言克隆

当参考音频是一种语言，但用户希望另一种语音语言时使用，例如日语参考音频说中文。

继续前，用直白方式说明取舍：

- 可能保留一部分音色和角色感。
- 可能带入跨语言口音，或出现不稳定发音。
- 更好的结果通常需要同一授权声线的目标语言干净参考音频，或已经证明擅长跨语种克隆的 model/provider。

推荐选项：

- 最佳：使用同一授权声线的目标语言参考音频，并用目标语言提示注册。
- 可接受实验：用参考语言提示注册，用目标语音语言提示合成，然后试听口音和发音。
- 保守 fallback：语音保持参考语言，给用户显示字幕/翻译。

对于日语参考音频说中文，不要静默切换成中文语音。除非用户已经明确要求，否则先问。

## Worker Contract 指导

worker 应保存足够元数据来排查语言问题：

```json
{
  "reference_audio_language": "Japanese",
  "speech_language": "Japanese",
  "visible_language": "Chinese",
  "api_clone_language_hint": "ja",
  "synthesis_language_hint": "ja"
}
```

每个生成任务都应把解析后的 synthesis hint 持久化到 `job.json` 和 chunk metadata。这样可以清楚判断坏口音来自克隆注册、合成语言路由，还是源材料本身。

## 公开安全

公开 OumuQ skills 和 docs 可以描述语言策略和占位符字段，但不能发布：

- 真实 voice ID。
- 真实 clone audio URL。
- 私有角色名。
- 第三方来源页面。
- 下载的参考音频。
- 个人服务器 IP、bucket 名称或签名 URL。
