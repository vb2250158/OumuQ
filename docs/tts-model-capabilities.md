# TTS Model Capabilities（仅本地）

机器可读能力表位于 `app/tts_model_capabilities.json`。

当前活跃模型只有：

- `onnx-vits-split`：本地五段 ONNX VITS，固定多说话人、低延迟生成。
- `qwen3-tts-local`：本地 Qwen3-TTS，多语言与参考音频生成。
- `indextts2`：本地 IndexTTS2，中文参考音色与情绪参数。

云端 CosyVoice、Qwen Voice Design、Voice Cloning 和付费 API worker 已归档，不再从 OumuQ 暴露注册或上传入口。
