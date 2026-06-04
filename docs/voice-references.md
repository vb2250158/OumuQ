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

## 匹配规则

worker 推荐按以下顺序评分：

1. 请求侧 `match_patterns` 与索引侧 `match_patterns`。
2. 请求 `emotion_vector` 与索引 `emotion_vector` 的距离。
3. `emotion_tags` 和 `mood` 的重合度。
4. 文本与 `title`、`ja`、`zh`、`text` 的相似度。
5. 参考音频时长，以及短音频补长时的相邻台词关系。

如果参考片段太短，worker 可以把相关片段拼成缓存用 prompt WAV。拼接结果属于 worker 缓存，不属于 `voice-references` 源数据。
