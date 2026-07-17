# 配置指南（仅本地模型）

OumuQ 当前执行本地模型策略，不使用任何付费 TTS/ASR API。

## 本地服务

```text
ONNX-VITS: http://127.0.0.1:8764
Qwen3-TTS: http://127.0.0.1:8765
IndexTTS2: http://127.0.0.1:8766
OumuQ:     http://127.0.0.1:8780
```

- 固定多说话人、低延迟即时朗读使用 `ONNX-VITS`。
- 日语或多语言角色使用 `Qwen3-TTS`。
- 中文参考音色使用 `IndexTTS2`。
- worker 只允许 `127.0.0.1`、`localhost` 或 `::1`。
- 云端 worker、音色注册、公网参考音频上传和相关配置已归档。

启动 OumuQ：

```powershell
cd OumuQ
py -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8780
```

角色注册表只应包含：角色 id、角色目录、参考音频索引、语言、`tts_engine` 和本机 `worker_url`。ONNX-VITS 固定声线额外使用 `onnx_vits_speaker` 或 `onnx_vits_speaker_id`。不要在活跃注册表中加入 `api_*`、云音色 ID、服务商 URL或远程模型字段。

ONNX-VITS 的模型包、依赖和启动参数见 [onnx-vits-worker.md](onnx-vits-worker.md)。

本地参考音频保存在 `voice-references/characters/<id>/audio/`，保持私有，不提交 GitHub。

## 播放策略

默认由 OumuQ 统一接管播放：单一 OumuQ 进程内按提交顺序 FIFO，多个进程通过主机级文件锁避免叠音。worker 只负责本地生成。

## 历史云端配置

历史实现和迁移前配置位于工作区 `archive/local-models-only-20260717/` 及 `OumuQ/archive/cloud-api-20260717/`。恢复前必须重新取得用户明确授权。
