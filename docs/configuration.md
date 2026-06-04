# 配置指南

本项目的配置分成三层：

1. 项目本身：Web GUI、路由 API、请求日志。
2. 角色和参考音色：`voice-references`。
3. TTS worker：Qwen3-TTS、IndexTTS2 或后续 API provider。

## 启动项目

```powershell
cd local-tts-studio
py -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8780
```

浏览器打开：

```text
http://127.0.0.1:8780
```

## 配置角色目录

复制示例目录：

```powershell
Copy-Item -Recurse voice-references.example voice-references
```

推荐结构：

```text
voice-references/
  reference-index.json
  characters/
    my_character/
      README.md
      voice-index.json
      audio/
```

`reference-index.json` 用来登记所有可选角色。每个角色至少应包含：

- `id`：稳定角色 id
- `display_name`：显示名
- `character_folder`：角色目录
- `index_file`：参考音频索引
- `speech_language`：语音输出语言
- `visible_language`：屏幕显示语言
- `tts_engine`：首选 TTS 引擎
- `worker_url`：默认 worker 地址

## 角色 README

每个角色目录里的 `README.md` 是人格说明文件。建议写清楚：

- 角色的说话气质
- 常用称呼和语气
- 适合的语言
- 参考音频来源说明
- 不适合模仿的边界

对话模式读取角色时，应优先看这个文件，再生成屏幕文字和语音文本。

## 参考音频索引

`voice-index.json` 记录每条参考音频的元数据：

```json
{
  "entries": [
    {
      "id": "cheerful_001",
      "audio_file": "voice-references/characters/my_character/audio/cheerful_001.wav",
      "text": "示例台词",
      "language": "Japanese",
      "mood": "cheerful",
      "emotion_tags": ["cheerful", "playful"],
      "emotion_vector": [0.55, 0, 0, 0, 0, 0, 0.08, 0.15],
      "match_patterns": ["开心|欢迎|早上好"],
      "duration_sec": 6.2
    }
  ]
}
```

路径建议使用工作目录相对路径，避免写死个人机器路径。

## Worker URL

GUI 可以指定 worker 地址。推荐本机约定：

```text
Qwen3-TTS:  http://127.0.0.1:8765
IndexTTS2:  http://127.0.0.1:8766
Web GUI:    http://127.0.0.1:8780
```

worker 必须兼容 [worker-contract.md](worker-contract.md)。

## 输出目录

路由层会在项目目录下写入：

```text
runs/YYYY-MM-DD/HHMMSS-<id>/
  request.json
  response.json
```

worker 可以把音频输出写到自己的 `outputs/` 或缓存目录。生成文件默认不应提交到 git。
