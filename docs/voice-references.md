# 参考音色规范

`voice-references` 是本地角色音色库。它既是角色注册表，也是参考音频索引。

## 推荐目录

```text
voice-references/
  reference-index.json
  characters/
    my_character/
      README.md
      voice-index.json
      audio/
```

## 什么可以提交

开源仓库里通常只提交：

- 目录结构
- 示例 JSON
- 示例 README
- `.gitkeep`
- 无版权风险的说明文档

## 什么不应该提交

不要提交：

- 个人录音
- 未确认授权的第三方角色语音
- 下载的游戏或动画音频
- 模型输出音频
- worker 缓存
- composite prompt WAV
- 真实云端 `voice_id`
- 真实克隆参考音频 URL
- 私有绘画参考图或不可公开的视觉提示词

## 本地角色音色数据

个人本地实验可以准备角色参考音频，例如从公开 wiki 页面整理台词信息，或使用自己有权使用的录音。

如果音频来自第三方作品，使用和再分发前必须确认来源许可和原始素材权利。本仓库不应包含这些 MP3/WAV 文件。

推荐流程：

1. 创建 `voice-references/characters/my_character/audio`。
2. 本地准备参考音频。
3. 保持文件名稳定。
4. 在 `voice-index.json` 中填写相对工作目录路径。
5. 补充 `emotion_tags`、`emotion_vector`、`match_patterns`。
6. 在 GUI 中选择对应角色测试。

## 云端 API 语音字段

如果角色使用云端 API worker，可以在本地 `reference-index.json` 里加入：

```json
{
  "id": "cloud_zh_voice",
  "tts_engine": "Qwen-TTS-API",
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "api_target_model": "cosyvoice-v3-plus",
  "api_clone_language_hint": "zh",
  "api_voice_instructions": "Use a natural conversational delivery.",
  "send_instructions_by_default": false
}
```

公开仓库只保留字段结构和占位符。真实音色 ID、参考音频 URL 和 provider 配置属于本地私有数据。

## 语言与跨语种合成

云端克隆音色应区分参考语料语言和目标语音语言：

- `api_clone_language_hint` 表示注册音色时参考音频的语言。
- `speech_language` 表示每次合成实际要说出的语言。
- `visible_language` 表示 Agent 显示给用户的文字语言。

如果参考音频是日语，而用户没有明确要求跨语种中文语音，默认应让合成也说日语，并把中文放在可见回复或字幕里。若用户希望“日语参考音色说中文”，需要在合成时传中文语言 hint，并接受可能出现跨语种口音；更稳的方案是使用同一授权音色的中文参考音频重新注册。

## 绘画模式字段

同一个角色也可以提供已脱敏的视觉配置：

```json
{
  "visual_profile": {
    "id": "generic_companion_visual",
    "prompt_profile": "A public, original companion character design.",
    "safety_note": "Keep image prompts generic and original when publishing examples."
  }
}
```

绘画模式只应读取这类公开安全字段。不要把声音来源、真人身份、私有角色名或私有参考图写入图像提示词。

## 匹配规则

worker 推荐按以下顺序评分：

1. 请求侧 `match_patterns` 与索引侧 `match_patterns`。
2. 请求 `emotion_vector` 与索引 `emotion_vector` 的距离。
3. `emotion_tags` 和 `mood` 的重合度。
4. 文本与 `title`、`ja`、`zh`、`text` 的相似度。
5. 参考音频时长，以及短音频补长时的相邻台词关系。

如果参考片段太短，worker 可以把相关片段拼成缓存用 prompt WAV。拼接结果属于 worker 缓存，不属于 `voice-references` 源数据。
