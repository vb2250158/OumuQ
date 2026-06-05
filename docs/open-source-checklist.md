# 开源发布检查清单

发布仓库前，先确认下面几类内容没有进入 git。

## 不应提交

- `.venv/`
- `runs/`
- `outputs/`
- worker 日志
- worker 缓存，例如 `.qwen-tts-api-cache/`
- 模型权重
- 模型缓存
- 真实参考音频
- 个人录音
- 第三方版权音频
- API key、cookie、token、密码
- 个人机器绝对路径
- 真实云端 `voice_id`
- 真实克隆参考音频 URL 或签名 URL
- 服务器 IP、对象存储桶名、内部域名
- 私有角色名、私有称呼、不可公开的角色口癖
- 私有绘画参考图和不可公开的视觉提示词

## 推荐检查命令

```powershell
git status --short --ignored
```

确认真实音频没有被跟踪：

```powershell
Get-ChildItem -Recurse -Force -File -Include *.mp3,*.wav,*.m4a,*.flac |
  Where-Object { $_.FullName -notmatch '\\.venv\\|\\runs\\|\\outputs\\' }
```

搜索常见敏感信息：

```powershell
rg -n "access[_-]?token|api[_-]?key|cookie|secret|password|hf_|sk-" . `
  --glob '!runs/**' `
  --glob '!outputs/**' `
  --glob '!.qwen-tts-api-cache/**' `
  --glob '!.venv/**' `
  --glob '!**/__pycache__/**'
```

搜索个人路径时，请根据自己的环境补充关键词。

搜索云端音色和部署线索：

```powershell
rg -n "voice_id|api_voice_id|clone_audio_url|cosyvoice|dashscope|http://|https://|\\d+\\.\\d+\\.\\d+\\.\\d+" . `
  --glob '!runs/**' `
  --glob '!outputs/**' `
  --glob '!.qwen-tts-api-cache/**' `
  --glob '!voice-references.example/**'
```

如果公开示例里需要这些字段，只能使用 `<set-in-local-copy>`、`<public-or-signed-reference-audio-url>` 这类占位符。

## 文档策略

当前阶段文档先统一使用中文。英文文档后续可以作为单独版本补充，例如：

- `README.en.md`
- `docs/en/`

在英文版完成前，不要混写大段英文说明，避免维护两套不一致的文档。
