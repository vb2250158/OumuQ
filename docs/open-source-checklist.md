# 开源发布检查清单

发布仓库前，先确认下面几类内容没有进入 git。

## 不应提交

- `.venv/`
- `runs/`
- `outputs/`
- worker 日志
- 模型权重
- 模型缓存
- 真实参考音频
- 个人录音
- 第三方版权音频
- API key、cookie、token、密码
- 个人机器绝对路径

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
  --glob '!.venv/**' `
  --glob '!**/__pycache__/**'
```

搜索个人路径时，请根据自己的环境补充关键词。

## 文档策略

当前阶段文档先统一使用中文。英文文档后续可以作为单独版本补充，例如：

- `README.en.md`
- `docs/en/`

在英文版完成前，不要混写大段英文说明，避免维护两套不一致的文档。
