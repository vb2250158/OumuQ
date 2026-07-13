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
- `api_target_model`：云端实际合成模型的规范字段。
- `api_clone_target_model`：旧数据兼容别名；读取时排在 `api_target_model` 之后，新条目不要只写它。
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
[
  {
    "id": "cheerful_001",
    "audio_file": "voice-references/characters/my_character/audio/cheerful_001.wav",
    "text": "示例台词",
    "language": "Japanese",
    "mood": ["cheerful"],
    "emotion_tags": ["cheerful", "playful"],
    "emotion_vector": [0.55, 0, 0, 0, 0, 0, 0.08, 0.15],
    "match_patterns": ["开心|欢迎|早上好"],
    "duration_seconds": 6.2
  }
]
```

当前 resolver 要求 `voice-index.json` 顶层是数组；不要包在 `{ "entries": [...] }` 中。

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

## 云端 Qwen 音色与完成报告

`Qwen-TTS-API` 是 OumuQ 的兼容 worker 名，不代表实际模型。角色配置和完成报告必须分别写出：

- 服务商：阿里云百炼（Alibaba Cloud Model Studio）。
- API：DashScope HTTP API。
- 实际合成模型：例如 `qwen3-tts-vd-2026-01-26`、`qwen3-tts-vc-2026-01-22` 或 `cosyvoice-v3-plus`。
- 音色方式：`voice_design`、`voice_cloning`、已有 voice ID 或预设音色。

角色资料或参考音频的克隆授权不明确时，默认使用 `qwen-voice-design` 创建原创音色，不提交参考音频。只有用户明确拥有云端声音克隆权利时才使用 `qwen-voice-enrollment`。注册与合成模型必须完全匹配；真实 voice ID 只保存在本机私有注册表。

`oumuq-tts-character-creator` 的验收报告 schema v2 会记录 provider、API、真实模型、创建方式、语言、路由、WAV 验证与“进程内 FIFO + 主机级播放互斥”策略，且只输出 `voice_id_configured` 布尔值，不显示真实 voice ID。使用 `play=false` 验收时只证明策略配置，不代表实际扬声器播放已测试。

## 多会话角色隔离与热切换

OumuQ 的角色路由是无状态的：没有服务器全局“当前角色”。当前角色由调用方会话拥有，每次请求都必须显式携带该会话的 `character_id`。

`character_id` 使用稳定小写标识。命名角色的 `api_voice_id`、`api_target_model` 和 `character_folder` 由私有注册表绑定；旧客户端请求中残留的 voice/model/folder 会被忽略或覆盖。云端音色注册成功时，实际 enrollment/target model 必须与 voice ID 一起原子写回注册表，避免注册模型和合成模型漂移。

`session_id` 是调用方生成的不透明关联 ID，只用于请求记录和界面过滤，不建立服务器端 `session_id -> character_id` 隐式绑定。带 `session_id` 的语音请求如果缺少 `character_id` 会被拒绝，避免误用其他会话或进程默认音色。

两个会话可以交错提交：

```json
{"session_id":"session-a","character_id":"tifira","text":"第一句","play":true}
{"session_id":"session-b","character_id":"bb","text":"第二句","play":true}
{"session_id":"session-a","character_id":"tifira","text":"第三句","play":true}
```

A -> B -> A 的三次请求会分别重新解析角色注册表；会话 A 的角色变化不会修改会话 B。`POST /api/route/resolve` 只预览本次请求，不写入任何全局角色状态。`GET /status` 里的 `character_id` 若存在，也只能视为 worker 启动默认值或诊断字段，不能作为会话角色来源。

WebGUI 为每个页面会话生成 `?session=<opaque-id>`，并在 `sessionStorage` 中按“会话 × 角色”保存表单草稿。点击“新会话”会打开带新 ID 的标签页。角色切换会保存旧角色草稿并载入新角色草稿，不会把 `prompt_audio`、`ref_text`、情绪向量或匹配规则带到另一个角色。工作进程地址只有在用户手工修改时才作为请求覆盖值发送。

按会话查看记录：

```text
GET /api/runs?session_id=session-a
GET /api/runs?session_id=session-b&character_id=bb
```

### 进程内 FIFO 与主机级播放互斥

默认 `OUMUQ_GLOBAL_PLAYBACK=1`。当请求 `play=true` 时：

```text
多个会话提交
  -> OumuQ 分配进程内播放序号
  -> 各 worker 收到 play=false，只负责生成
  -> OumuQ 等待每个 job 完成
  -> 按提交序号进入本进程 FIFO
  -> 取得主机级播放锁
  -> Windows winsound 阻塞播放完整 WAV
```

因此不同角色即使路由到不同 worker 或不同 OumuQ 进程，也不会叠加。单一 OumuQ 进程内，后提交的语音即使先生成完成，也必须等待更早的播放序号；多个进程之间只保证互斥，不保证统一顺序。状态接口：

```text
GET /api/playback/status
```

只有调试 worker 本地播放时才可设置 `OUMUQ_GLOBAL_PLAYBACK=0`；此模式无法保证不同 worker 之间不重叠，不适合多会话对话。

### Worker 共享规则

- `worker_url` 是共享服务地址，不代表 worker 属于某个角色。
- IndexTTS2 和本地 Qwen3-TTS 在每个 job 中快照参考音频和角色参数。
- Qwen API worker 每次请求重新读取目标角色的 `api_voice_id`、模型、语言提示和说明。
- `--character-id` 只能作为 legacy 默认值，不能覆盖本次请求。
- 只能绑定单角色的旧 worker 必须使用角色专属端口隔离，不能反复重启共享端口。

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
