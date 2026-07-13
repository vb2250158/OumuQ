# 技能说明

这个目录用于放置已脱敏、可公开的 Codex skill 说明。

开源项目里的 skill 应保持通用：

- 使用工作目录相对路径。
- 不写个人音频文件名。
- 不写死模型缓存路径。
- 指向 `docs/worker-contract.md` 和 `docs/voice-references.md`。

本地开发机可以有更丰富的私人 skill，但公开 skill 应描述通用契约，而不是依赖某个用户的本机环境。

角色对话类 skill 的关键约束：

- 屏幕可见文本也必须保持角色扮演语气。
- 先把语音文本提交给常驻 worker，拿到 queued 后再显示文字。
- 语音语言和屏幕语言不同时，屏幕文本应翻译语音含义并保留角色口吻，而不是改写成普通助手摘要。
- 安全、准确性和拒绝边界仍然生效，只是用角色语气表达。
- 当前角色属于各自会话；每次请求发送 `session_id + character_id`，不得重启共享 worker。
- 生成可以跨 worker 并行；单一 OumuQ 进程内按 FIFO 播放，主机级互斥锁保证多个进程也不叠音，但不宣称跨进程统一顺序。

## 安装到 Codex

在 OumuQ 仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_codex_skills.ps1 -Force
```

脚本会把公开 skill 复制到当前用户的 Codex skills 目录。安装后重启 Codex 或打开新会话。

手动安装时，把下面这些目录复制到 `%USERPROFILE%\.codex\skills` 或 `$env:CODEX_HOME\skills`：

- `character-tts-dialogue`
- `character-dialogue-workflow`
- `oumuq-tts-character-creator`
- `tts-router-workflow`
- `qwen-tts-api`
- `qwen-tts-audio`
- `qwen-api-tts-worker`
- `qwen-voice-language-training`

详细步骤见 [在 Codex 中安装 OumuQ 工作流](../docs/codex-skill-install.md)。

## 当前公开模板

- `character-tts-dialogue`：脱敏后的 Codex 对话入口 skill，要求可见文本和语音都保持同一角色语气，并在拿到 TTS worker 的 queued 后再显示文本。
- `character-dialogue-workflow`：角色对话时先把语音提交给常驻 worker，再显示同样角色化的屏幕文字。
- `oumuq-tts-character-creator`：从中文 Wiki 或资料提取角色提示词，创建或更新 OumuQ 角色条目，完成 TTS 试听与服务商/真实模型报告，并把执行问题沉淀为防复发门禁。
- `tts-router-workflow`：从 `voice-references` 路由角色、语言、worker、参考音频和云端音色字段。
- `qwen-tts-api`：可安装的动态多角色 Qwen/DashScope worker 源码与调用契约。
- `qwen-tts-audio`：可安装的本地 Qwen3-TTS worker，按请求解析不同角色参考音频。
- `qwen-api-tts-worker`：Qwen/DashScope 云端 API worker 的通用配置方式，真实 `voice_id` 和克隆 URL 只放本地私有副本。
- `qwen-voice-language-training`：规划 Qwen 云端克隆音色的参考语料语言、合成语言和跨语种口音取舍。

这些模板可以和 [Agent 与多模态工作流](../docs/agent-workflows.md) 配套使用。绘画模式只读取公开安全的 `visual_profile` 字段，不读取真实音色来源或私有参考音频。
