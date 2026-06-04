# Worker 契约

Local TTS Studio 通过 HTTP 和模型 worker 通信。

worker 契约采用角色优先设计。调用方最好只发送 `character_id` 和文本，由 worker 或路由层解析语言、引擎参数、参考音频、情绪提示和播放行为。

worker 可以复用 `app/core/voice_reference.py` 完成角色注册表读取、正则匹配、情绪向量评分、短参考音频补长和 composite prompt WAV 创建。

## 必需接口

```text
GET  /health
GET  /status
GET  /status/<job_id>
POST /speak
```

## POST /speak

请求体示例：

```json
{
  "text": "晚上好，今天辛苦了。",
  "play": true,
  "language": "Japanese",
  "character_id": "jp_companion",
  "emotion_tags": ["cheerful", "gentle"],
  "emotion_vector": [0.22, 0, 0, 0, 0, 0, 0.08, 0.14],
  "match_patterns": ["晚上好|辛苦了"],
  "max_new_tokens": 192
}
```

worker 应尽快返回任务对象：

```json
{
  "id": "20260604-010203-abcd1234",
  "status": "queued",
  "output": "outputs/2026-06-04/010203-abcd1234/final.wav",
  "play": true
}
```

生成和播放应在 worker 进程里异步继续执行。

## 角色感知字段

- `character_id`：推荐使用的高层角色选择器。
- `character_folder`：可选，显式指定角色目录。
- `language`：语音输出语言，通常来自角色配置。
- `emotion_tags`：人类可读的情绪提示。
- `emotion_vector`：数值情绪控制，也可用于参考音频匹配。
- `match_patterns`：请求侧正则或关键词提示。
- `prompt_audio`：显式指定单条参考音频。
- `prompt_audios`：显式指定多条参考音频。

正常对话优先使用 `character_id`。显式参考音频路径更适合调试、测试和手动配音生产。

## 输出组织

worker 推荐按日期和时间写最终音频：

```text
outputs/
  2026-06-04/
    010203-abcd1234/
      request.json
      response.json
      chunks/
      final.wav
```

路由层也会记录请求和响应元数据：

```text
runs/YYYY-MM-DD/HHMMSS-<id>/
```

## 播放规则

worker 应负责顺序播放。路由层可以快速提交很多请求，但播放必须排队、串行、按提交顺序进行。

如果 worker 支持分句生成，应保证同一请求内的分句顺序稳定。
