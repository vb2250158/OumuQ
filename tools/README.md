# 工具脚本

这个目录用于放置项目辅助脚本。

不要加入会自动再分发版权音频的脚本。

如果后续加入下载器，应明确标注为本地辅助工具，并保留来源署名和授权风险提示。

## ONNX-VITS

NAS/UNC 工作区里 Python `venv` 可能因映射盘与真实 UNC 路径不一致而拒绝 `ensurepip`。此时使用项目内、Git 已忽略的依赖目录：

```powershell
.\tools\install_onnx_vits_deps.ps1
.\tools\start_onnx_vits_worker.ps1 -ModelDir "<五段 ONNX 目录>" -Config "<模型配置.json>" -DefaultSpeaker "<固定声线名>"
```

安装脚本从 `pyproject.toml` 读取依赖列表，避免维护第二份版本真源。启动脚本只校验并读取外部本机模型，不下载或复制模型权重。
