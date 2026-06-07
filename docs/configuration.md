# 配置指南

本项目的配置分成三层：

1. 项目本身：Web GUI、路由 API、请求日志。
2. 角色和参考音色：`voice-references`。
3. TTS worker：Qwen3-TTS、IndexTTS2、Qwen-TTS-API 或后续 API provider。

## 启动项目

```powershell
cd OumuQ
py -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8780
```

浏览器打开：

```text
http://127.0.0.1:8780
```

## 本地 Smoke 测试

开发路由和 Web GUI 时，可以先用 mock worker 代替真实 TTS 模型：

```powershell
py -X utf8 -m pip install -e .[dev]
py -X utf8 -m uvicorn tools.mock_worker:app --host 127.0.0.1 --port 8765
```

另开一个终端启动 OumuQ：

```powershell
$env:LOCAL_TTS_WORKER_URL = "http://127.0.0.1:8765"
$env:OUMUQ_QWEN3_TTS_WORKER_URL = "http://127.0.0.1:8765"
$env:OUMUQ_INDEXTTS2_WORKER_URL = "http://127.0.0.1:8765"
$env:OUMUQ_QWEN_TTS_API_WORKER_URL = "http://127.0.0.1:8765"
py -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8780
```

然后运行自动测试：

```powershell
py -X utf8 -m pytest
py -X utf8 -m ruff check .
```

mock worker 会返回任务元数据，不会生成真实音频，适合验证角色路由、批量提交、请求记录和 worker 状态轮询。

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

云端 API 语音角色可以额外包含：

- `api_voice_id`：已有克隆音色 ID，本地私有副本填写。
- `api_clone_audio_url`：公开或签名参考音频 URL，本地私有副本填写。
- `api_clone_target_model`：云端克隆目标模型。
- `api_clone_language_hint`：克隆参考语种提示。
- `api_voice_instructions`：自然语言发声说明。
- `send_instructions_by_default`：是否默认把发声说明发送给 provider。
- `visual_profile`：给绘画模式读取的公开安全视觉描述。

公开仓库里的这些字段应使用占位符。真实 `voice_id`、URL、角色名和私有视觉参考只放在本地副本或部署环境。

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
Qwen-TTS-API: http://127.0.0.1:8767
Web GUI:    http://127.0.0.1:8780
```

对应环境变量：

```powershell
$env:OUMUQ_QWEN3_TTS_WORKER_URL = "http://127.0.0.1:8765"
$env:OUMUQ_INDEXTTS2_WORKER_URL = "http://127.0.0.1:8766"
$env:OUMUQ_QWEN_TTS_API_WORKER_URL = "http://127.0.0.1:8767"
```

worker 必须兼容 [worker-contract.md](worker-contract.md)。

默认情况下，OumuQ 只允许把请求转发到本机 worker：

```text
127.0.0.1
localhost
::1
```

如果确实需要访问内网或白名单域名，可以用逗号分隔配置：

```powershell
$env:OUMUQ_ALLOWED_WORKER_HOSTS = "tts.internal.example,192.168.1.20"
```

这只放开 host 校验；worker 仍应由可信网络或反向代理保护。

## 角色热切换

角色热切换只依赖 `character_id`。前端选择角色或 Agent 指定角色时，OumuQ 会用 `/api/route/resolve` 解析下一次请求的 worker URL、语言、模型、参考音频和 provider 参数。

这个解析步骤不会调用 `/api/speak`，也不会启动、停止或重启任何 worker。

真正生成语音时，请求体仍然带上同一个 `character_id`：

```json
{
  "text": "こんばんは。",
  "character_id": "<character_id>"
}
```

只要 worker 支持按请求读取 `character_id` 或解析后的参数，就可以常驻运行并热切换声线。

## LLM 参数推理

OumuQ 可以在提交语音前，先用 `/api/infer-parameters` 推理 TTS 控制参数，再把结果回填到表单或请求体里。

默认不调用云端模型，也不会触发 TTS worker。未配置 LLM 时，接口使用本地启发式规则推理：

```json
{
  "text": "谢谢你，今天太好了",
  "character_id": "jp_companion"
}
```

返回示例：

```json
{
  "source": "heuristic",
  "parameters": {
    "language": "Japanese",
    "emotion_mode": "vector",
    "emotion_alpha": 0.62,
    "emotion_vector": [0.58, 0, 0, 0, 0, 0, 0.08, 0.14],
    "emotion_tags": ["warm", "cheerful"],
    "emotion_text": "warm, cheerful",
    "ref_text": "谢谢你，今天太好了",
    "match_patterns": ["warm", "cheerful"],
    "max_new_tokens": 192
  }
}
```

如果要接入 OpenAI-compatible 的大语言模型接口，配置：

```powershell
$env:OUMUQ_LLM_BASE_URL = "https://api.example.com/v1"
$env:OUMUQ_LLM_API_KEY = "..."
$env:OUMUQ_LLM_MODEL = "your-model"
```

然后请求时可以显式指定：

```json
{
  "text": "晚上好，今天辛苦了。",
  "character_id": "jp_companion",
  "provider": "llm"
}
```

提示词模板在：

```text
app/prompts/parameter_inference.zh.md
```

模板会读取角色配置、角色 README、参考音频索引摘录和当前文本，要求 LLM 只返回 JSON 参数。

## 输出目录

路由层会在项目目录下写入：

```text
runs/YYYY-MM-DD/HHMMSS-<id>/
  request.json
  response.json
```

worker 可以把音频输出写到自己的 `outputs/` 或缓存目录。生成文件默认不应提交到 git。
