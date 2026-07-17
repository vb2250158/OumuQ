# ONNX-VITS 极速 Worker

OumuQ 自带一个仅本机使用的固定多说话人 ONNX-VITS worker。它借鉴轻量桌面翻译器的低延迟结构，但不依赖团子翻译进程，也不复制或发布团子的模型、角色音频和声线表。

## 技术结构

```text
文本
  -> 中/日/英音素前端
  -> token ids
  -> enc_p.onnx
  -> emb_g.onnx（固定 speaker id）
  -> dp.onnx（时长）
  -> flow.onnx
  -> dec.onnx
  -> PCM16 WAV
```

五个 ONNX Runtime session 在 worker 启动时一次加载，后续请求只做本机内存推理。worker 使用 OumuQ 通用的 `/speak` 异步任务契约；最终 WAV 仍由 OumuQ 按进程内 FIFO 和主机级互斥锁播放。

## 模型包边界

仓库不包含模型权重、声线表、角色录音或生成音频。使用者需要准备自己有权使用的 VITS split-ONNX 模型包：

```text
<model-dir>/
  enc_p.onnx
  emb_g.onnx
  dp.onnx
  flow.onnx
  dec.onnx

<config>.json
```

配置需要包含 `symbols`、`data.sampling_rate`、`data.hop_length`、`data.text_cleaners`、`data.add_blank` 和 `speakers`。当前文本前端支持 `cjke_cleaners2` 的中文、日语和英语路径。

日语前端还需要本机 OpenJTalk 字典。为避免运行时静默联网下载，启动前显式指向已经存在的字典目录：

```powershell
$env:OPEN_JTALK_DICT_DIR = "<本机 open_jtalk_dic_utf_8-1.11 目录>"
```

## 安装和启动

```powershell
cd OumuQ
py -3.10 -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,onnx-vits]"

$env:OUMUQ_ONNX_VITS_MODEL_DIR = "<本机模型目录>"
$env:OUMUQ_ONNX_VITS_CONFIG = "<本机模型配置.json>"
$env:OUMUQ_ONNX_VITS_DEFAULT_SPEAKER = "<配置中的固定声线名>"
.\.venv\Scripts\python.exe -m app.workers.onnx_vits
```

默认监听 `http://127.0.0.1:8764`。可用接口：

- `GET /health`
- `GET /status`
- `GET /status/<job_id>`
- `GET /speakers`
- `POST /speak`

如果项目位于 NAS/UNC 路径，Python `venv` 可能因为映射盘与真实 UNC 路径不一致而无法执行 `ensurepip`。使用项目内依赖目录即可避开：

```powershell
.\tools\install_onnx_vits_deps.ps1
.\tools\start_onnx_vits_worker.ps1 -ModelDir "<本机模型目录>" -Config "<本机模型配置.json>" -DefaultSpeaker "<固定声线名>"
```

默认会按 ONNX Runtime 当前可用情况选择 CUDA、DirectML 或 CPU。需要显式选择时使用：

```powershell
$env:OUMUQ_ONNX_VITS_PROVIDERS = "CUDAExecutionProvider,CPUExecutionProvider"
```

`onnxruntime` 默认是 CPU 包。CUDA 推理需要在本机环境中改用与显卡/CUDA 匹配的 `onnxruntime-gpu`，不要同时安装两个 Runtime 包。

## 角色注册

固定声线绑定由角色注册表拥有，模型目录由 worker 环境拥有：

```json
{
  "id": "fast_local_character",
  "display_name_zh": "本地极速角色",
  "tts_engine": "ONNX-VITS",
  "worker_url": "http://127.0.0.1:8764",
  "speech_language": "Chinese",
  "visible_language": "Chinese",
  "onnx_vits_speaker": "<配置中的固定声线名>",
  "onnx_vits_speed": 1.0
}
```

也可以用 `onnx_vits_speaker_id`，但优先使用可读且由模型配置验证的声线名。带 `character_id` 的请求会忽略客户端残留的 `speaker`/`speaker_id`，避免会话串声线。

ONNX-VITS 是固定声线引擎，不读取 `prompt_audio`，也不做零样本克隆。需要从参考音频即时复刻时继续使用 IndexTTS2 或 Qwen3-TTS。

## 来源与许可证

五段模型结构参考 [VITS-fast-fine-tuning](https://github.com/Plachtaa/VITS-fast-fine-tuning) 的 Apache-2.0 开源实现；音素前端保留其 `text/` 目录中的 Keith Ito MIT 许可声明。详细第三方说明见 `app/workers/onnx_vits/THIRD_PARTY_LICENSES.md`。
