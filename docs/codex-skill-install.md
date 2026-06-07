# 在 Codex 中安装 OumuQ 工作流

这份说明面向刚克隆 OumuQ 的用户。目标是把公开版角色语音工作流安装到自己的 Codex 里，然后能用同一套 `voice-references`、worker contract 和 Agent skill 模板开始实验。

公开仓库安装的是工作流，不是私有模型、私有音色、API key 或参考音频。真实音色和密钥需要用户在自己的本地环境里配置。

## 1. 克隆项目

```powershell
git clone https://github.com/<owner>/OumuQ.git
cd OumuQ
```

如果已经在本地有项目，直接进入仓库目录即可。

## 2. 安装 Codex skills

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\install_codex_skills.ps1 -Force
```

脚本会把 `skills/` 下带 `SKILL.md` 的公开 skill 复制到：

```text
%USERPROFILE%\.codex\skills
```

如果用户设置了 `CODEX_HOME`，脚本会改用：

```text
$env:CODEX_HOME\skills
```

也可以手动复制：

```powershell
Copy-Item -Recurse -Force .\skills\character-dialogue-workflow $HOME\.codex\skills\
Copy-Item -Recurse -Force .\skills\oumuq-character-creator $HOME\.codex\skills\
Copy-Item -Recurse -Force .\skills\tts-router-workflow $HOME\.codex\skills\
Copy-Item -Recurse -Force .\skills\qwen-api-tts-worker $HOME\.codex\skills\
Copy-Item -Recurse -Force .\skills\qwen-voice-language-training $HOME\.codex\skills\
```

安装后重启 Codex，或打开一个新的 Codex 会话，让 skill 列表重新加载。

## 3. 准备本地角色配置

复制示例目录：

```powershell
Copy-Item -Recurse voice-references.example voice-references
```

公开示例里有一个云端 API 角色：

```text
cloud_zh_voice
```

它只包含占位字段。用户可以在本地 `voice-references/reference-index.json` 填入自己的真实值：

```json
{
  "api_voice_id": "<your-local-voice-id>",
  "api_clone_audio_url": "<your-public-or-signed-reference-audio-url>"
}
```

不要把本地真实值提交到公开仓库。

## 4. 配置 API key

如果使用 Qwen/DashScope API worker，在本机设置环境变量：

```powershell
setx DASHSCOPE_API_KEY "<your-api-key>"
```

重新打开终端后环境变量才会对新进程生效。

## 5. 启动 OumuQ Web GUI

```powershell
py -X utf8 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8780
```

打开：

```text
http://127.0.0.1:8780
```

开发和测试时可以先用 mock worker：

```powershell
py -X utf8 -m uvicorn tools.mock_worker:app --host 127.0.0.1 --port 8767
```

真实云端 worker 需要另行实现或接入兼容的 `GET /health`、`GET /status`、`GET /status/<job_id>`、`POST /speak` 接口。契约见 [worker-contract.md](worker-contract.md)。

## 6. 在 Codex 里启用角色语音模式

新会话里可以这样说：

```text
使用 character-dialogue-workflow、tts-router-workflow 和 qwen-api-tts-worker。
进入 OumuQ 角色语音模式，角色使用 cloud_zh_voice，worker 地址 http://127.0.0.1:8767。
之后每次回复都保持角色语气：先生成屏幕可见文本和语音文本，提交语音文本到 /speak，返回 queued 后再显示屏幕文本。
```

如果要先创建新角色，可以使用 `oumuq-character-creator` 生成或更新 `voice-references` 角色条目，再切换到对话模式。

如果需要克隆新音色或让外语参考音频改说另一种语言，再加上 `qwen-voice-language-training`。它会要求先确认目标语音语言；例如日语参考音频默认应生成日语语音，中文只作为可见回复或字幕，除非用户明确接受跨语种中文合成的口音风险。

如果只想测试路由，不想生成真实音频，可以先运行 mock worker，再用同一个提示词。

## 7. 绘画模式如何配套

绘画模式复用同一个 `character_id`，但只读取公开安全字段：

```json
{
  "visual_profile": {
    "id": "generic_companion_visual",
    "prompt_profile": "A public, original companion character design."
  }
}
```

不要把真实音色来源、私有角色名、私有参考图、服务器 URL 或签名 URL 写进绘画提示词。

## 8. 新用户应该得到什么

完成上面的步骤后，新用户应拥有：

- 安装到 Codex 的公开版角色对话 skill。
- 安装到 Codex 的 TTS router skill。
- 安装到 Codex 的 Qwen API worker skill。
- 安装到 Codex 的 Qwen 克隆音色语言规划 skill。
- 一个可复制修改的 `voice-references` 本地角色配置。
- 一个可跑的 OumuQ Web GUI。
- 一个可用 mock worker 验证的 `/speak` 工作流。

如果用户想用真实云端克隆音色，只需要在自己的本地副本里补 API key、`api_voice_id` 或 `api_clone_audio_url`。
