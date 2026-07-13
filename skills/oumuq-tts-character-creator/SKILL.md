---
name: oumuq-tts-character-creator
description: 从中文 Wiki、网页、本地资料、角色设定或参考音频中提取角色人格、语言风格和 TTS 参数，创建或更新 OumuQ 的 voice-references 角色条目。角色 TTS 或声音克隆任务应先把可用参考音频提取到本机私有目录，再按用户选择使用本地或千问克隆；skill、代码和脱敏模板可以发布，但真实 TTS 参考音频不得放到 GitHub 或公网地址。用户要求创建、添加、注册、提取或还原角色，制作中文角色提示词、语音角色、音色克隆配置或对话模式角色时使用。
---

# OumuQ 角色提取与 TTS 创建

根据 Wiki、网页或用户资料提炼可执行的中文角色提示词，并把可用且获准私用的参考音频提取到本机私有 `voice-references`。声音克隆必须以真实本地参考音频为输入；只有另行执行并观察到真实播放时才报告扬声器试听。

## 输入信息

收集或合理推断：

- 角色名与资料来源：中文 Wiki 链接、网页、本地文档或用户提供的文本。
- `character_id`：稳定的小写英文标识，例如 `jp_companion`。
- `name`、`display_name`、`display_name_zh`。
- 角色性格、语气、情绪范围、称呼、口头禅和对话边界。
- `speech_language`：TTS 实际说出的语言。
- `visible_language`：屏幕显示语言，默认中文。
- `tts_engine`：通常为 `Qwen-TTS-API`、`Qwen3-TTS` 或 `IndexTTS2`。
- 音色来源：本地个人非商业参考音频、已有 `api_voice_id`、待克隆 URL，或仅占位。
- 写入目标：本机私有 `voice-references`。skill、代码、测试和脱敏占位模板可以进入公开仓库；真实 TTS 参考音频必须留在本机私有目录。

用户提供角色 Wiki/资料并要求角色 TTS、声音还原、声音克隆或“千问版”时，先提取人格和台词，再把页面中可用且获准私用的参考音频下载到本机私有角色目录。若明确只要文字人格，才省略音频提取。

## 本地提取、云端克隆与 GitHub 发布边界

“保存到本机”“提交给阿里云百炼做克隆”和“上传到 GitHub”是三件不同的事，必须分别处理，不能把其中一个禁止项扩张到另外两个。

> 我会先把参考音频提取到本机私有目录，用于参考和克隆；skill 可以提交 GitHub，但真实 TTS 参考音频不会放到 GitHub、公开 URL 或其他公网可访问位置。若使用千问声音克隆，优先把本地样本通过 Data URL 直接提交给阿里云百炼 API，不先公开托管音频。

按目标执行：

- **本地参考音频提取**：角色 TTS、声音还原或克隆任务中，只要来源含可用音频且用户说明用于个人非商业用途，就下载到本机私有角色目录，转写并写入 `voice-index.json`。这是克隆前置步骤，不是 GitHub 发布。
- **声音克隆**：用户要求克隆或“千问版”且来源含参考音频时，优先走 `qwen-voice-enrollment`，从本地样本中选择干净片段提交给阿里云百炼；不得改成 Voice Design 冒充克隆。
- **原创声音设计**：只有用户明确要求原创音色时，才可调用 `qwen-voice-design`；必须说明它不还原原声。
- **仅人格**：只有用户明确只要文字人格，或资料确实没有可用音频时，才创建纯文字人格包并报告缺少克隆样本。
- **已有云端音色**：用户提供已注册的私有 voice ID 时，只配置该音色，不重新创建。
- **GitHub 发布**：skill、实现代码、测试和脱敏占位模板可以 stage、commit 或 push；真实 TTS 参考音频、voice ID、签名 URL、密钥和含私有路径的运行产物不得提交。角色文字资料是否发布按用户指定范围和隐私扫描处理，不与音频禁令混为一谈。

用户说“不上传”时必须确认目标或结合上下文判定：如果明确说 GitHub/公网，继续本地提取，并可按已选路线通过百炼 API 直接提交 Data URL，但不得创建公开音频 URL；如果明确说不提交给阿里云百炼，才只保留本地参考音频。不得把任何克隆需求静默降级为 Voice Design。

## 完成定义

先区分两级完成状态。

独立角色包完成必须满足：

1. 已保存规范化来源或 BWIKI 原始提取包。
2. 已生成 `character-evidence.json` 和带证据引用的 `character-profile.json`。
3. 已根据证据写成可执行的中文 `README.md`，而不是生平摘抄。
4. 来源含语音时，`voice-index.json` 不为空；可用且允许本机保存的音频已建立私有参考记录。
5. `validate_character.py --character-dir ... --strict --skip-registry` 通过。

只有用户明确选择了 TTS 音色路线，才进入“注册并可用的 TTS 角色”阶段，并满足：

1. 角色在 `reference-index.json` 中恰好出现一次，所有路径真实存在。
2. `validate_character.py --workspace ... --strict` 通过。
3. OumuQ `/api/characters` 可见，参数推理能读取 README 与语音索引，路由没有意外绕过动态匹配。
4. 用户要求 TTS 验证且 worker 可用时，`verify_tts.py` 达到 `tts_verified`，这只表示 WAV 生成与解码通过。用户要求实际扬声器试听时，还要另行以 `play=true` 执行并取得可观察播放证据。

Worker 未启动只表示“WAV 验证与实际播放未完成”，不能抹掉已经完成的资料、人格和索引工作；但不得声称音频或扬声器播放已验证。

## 完成后必须说明创建方式

无论全部完成还是只完成部分阶段，最终都要用中文明确汇报以下字段，不能只说“角色已创建”或“已做千问版”：

- 创建状态：`角色包完成`、`已注册`、`已创建云端音色`、`WAV 已验证`、`实际播放已验证`，或具体未完成项。后二者不得混用。
- 角色与变体：显示名、`character_id`；同一角色有本地版和云端版时分别列出。
- 资料来源：只概括来源类型和页面，不泄露私有文件、签名 URL 或音色 ID。
- 服务商与 API：例如“本机本地推理”，或“阿里云百炼 / DashScope”。
- OumuQ 引擎与 worker：例如 `IndexTTS2 :8766`、`Qwen-TTS-API :8767`。
- 实际合成模型：必须写真实模型 ID。`Qwen-TTS-API` 是 OumuQ worker 名，不等于实际模型名。
- 音色方式：本地零样本参考音频、已有云端音色、Qwen `qwen-voice-design` / `qwen-voice-enrollment`，或 CosyVoice `voice-enrollment`。
- 语言：参考音频语言、实际语音语言、屏幕语言。
- 验收结果：校验、路由、WAV 生成/解码与实际播放分别是否通过；`queued` 不等于 WAV 完成，`play=false` 不等于实际播放。
- 播放策略：经 OumuQ 播放时准确说明“单一 OumuQ 进程内按提交顺序 FIFO；主机级互斥保证多个进程也不叠音；不宣称跨进程 FIFO 顺序”。若验收请求使用 `play=false`，只能报告播放策略已验证，不能声称实际扬声器播放已测试。

云端音色 ID、API Key、完整私有路径和签名 URL 只保存到本机私有配置，不出现在可见完成报告中。若实际模型是 `cosyvoice-*`，必须写“CosyVoice”；只有 `qwen3-tts-vc-*` / `qwen3-tts-vd-*` 才分别写“Qwen3-TTS-VC / VD”，不得把 CosyVoice 混称为“千问模型”。

## 问题复盘与防复发

执行中一旦出现失败、误路由、串角色、叠音、协议差异、音频异常、隐私风险或工具环境问题，修复后必须阅读并更新 [排障与防复发清单](references/troubleshooting.md)：

1. 写清现象与最小复现，不只记录错误字符串。
2. 写清根因、正确做法、验证证据和防复发门禁。
3. 只沉淀可复用结论；删除 API Key、voice ID、Data URL、签名 URL、个人路径和真实私聊内容。
4. 若只是当前机器偶发现象，记录检测与安全降级，不把个人环境写死进公开 skill。
5. 最终回复增加“本次问题沉淀”：列出新增/命中的条目；没有问题也明确写“无新增问题”。

遇到云端 Qwen、动态多角色、串行播放、WAV 解码或 skill 安装问题时，开始操作前先读该清单。修复代码但没有更新清单，任务不算完成。

## 从 Wiki 或资料提取角色

1. 用户提供网页链接时，读取指定页面；角色信息分散时，仅检索必要的相关页面。
2. 区分资料中的客观设定、角色原话和推断，避免把同人观点或编辑者描述当作官方设定。
3. 优先提取会直接影响对话和语音的特征：
   - 核心性格与价值取向。
   - 对不同对象的称呼和关系距离。
   - 句长、节奏、礼貌程度、常用句式和口头禅。
   - 平静、开心、悲伤、生气、紧张等状态下的表达变化。
   - 不应说、不应做或不应透露的边界。
4. 用中文生成简洁、可执行的角色提示词，不堆砌生平资料。
5. 不大段复制受版权保护的 Wiki 或台词；以概括和短例句表达风格。
6. 资料不足时明确标记“资料未证实”或使用中性占位，不编造剧情事实。

先用规范化脚本保存一般网页和本地资料：

```powershell
py -3.10 -X utf8 scripts\extract_sources.py <链接或文件...> --output "<角色目录>\source-bundle.json"
```

一般资料提取完成后，把正文切成带来源哈希、行号和字符区间的证据：

```powershell
py -3.10 -X utf8 scripts\prepare_material_evidence.py --source-bundle "<角色目录>\source-bundle.json" --character-dir "<角色目录>" --character-id <id> --backup
```

随后依据证据 ID 写 `character-profile.json` 和 README。不要让摘要结论只指向整份文档；尽量引用精确句段。

遇到动态页、反爬或正文缺失时，读取 [提取策略](references/extraction-strategies.md) 并走完降级链，不能因第一次请求失败就结束。

### BWIKI 强制提取流程

遇到 `wiki.biligame.com/czn` 角色页时，必须先运行：

```powershell
py -3.10 -X utf8 scripts\extract_bwiki_voice.py --title "<角色名>" --verify-audio-metadata --output "<角色目录>\bwiki-voice-extract.json"
```

脚本从页面的 `voice-player-root data-entries` 提取中文、日文、韩文台词和音频 URL。API 被站点防护拦截时，用浏览器打开页面并保存完整渲染 HTML，再运行：

```powershell
py -3.10 -X utf8 scripts\extract_bwiki_voice.py --title "<角色名>" --html-file "<渲染页.html>" --output "<角色目录>\bwiki-voice-extract.json"
```

如果页面存在语音区但提取结果为零，任务判定为失败：不得写入空 `voice-index.json` 并宣称角色创建完成。先完成浏览器渲染页降级提取，再生成角色人格、语音索引和 TTS 配置。

脚本默认使用结构化链路：SMW `askargs` 获取稳定 `combatant_id` 与角色档案，再用 `expandtemplates` 直接展开 `Module:Voice/<id>`。页面改名时优先用稳定 ID 恢复规范名称；输出必须记录页面与 Voice 模块修订号，并校验 `data-total`、唯一 ID、`data-types` 合计和三语覆盖数。

提取成功后生成语音索引和证据包：

```powershell
py -3.10 -X utf8 scripts\prepare_bwiki_character.py --extract "<角色目录>\bwiki-voice-extract.json" --character-dir "<角色目录>" --character-id <id> --language cn --download --rights-status user-requested-private-use --backup
```

只有用户明确要求不在本机保存页面音频时才省略 `--download`，并仍保留台词、语言和来源 URL 元数据；个人非商业克隆任务默认执行本地提取。

## 中文角色提示词结构

在角色 `README.md` 中至少写入：

- 角色定位：一句话说明身份和对话用途。
- 核心性格：3 至 6 条稳定特征。
- 语言风格：句式、节奏、用词、礼貌程度和称呼。
- 情绪表现：不同情绪下如何调整表达和 TTS 风格。
- 对话规则：保持角色身份，同时以事实准确和用户安全为优先。
- 禁止事项：不伪造资料、不泄露隐私、不声称真实角色或声优本人发言。
- `speech_language`、`visible_language`、TTS 引擎和音色状态。
- 资料来源及提取日期，避免复制长段原文。

屏幕文字与语音文字可以不同语言，但必须表达同一含义并保持同一角色口吻。

先按 [证据化角色模型](references/character-profile-schema.md) 写 `character-profile.json`。每项人格、语言习惯、称呼和情绪模式必须引用 `character-evidence.json` 中真实存在的 ID；不要用战斗机制或单条喊声过度推断稳定人格。

## 文件目标

```text
voice-references/reference-index.json
voice-references/characters/<character_id>/README.md
voice-references/characters/<character_id>/voice-index.json
voice-references/characters/<character_id>/character-evidence.json
voice-references/characters/<character_id>/character-profile.json
voice-references/characters/<character_id>/profile-evidence.json
voice-references/characters/<character_id>/audio/.gitkeep
```

若只有 `voice-references.example`，先询问是否创建本机私有副本。公开模板写入 `voice-references.example`。

## 创建流程

先完成本地角色包与参考音频提取：

1. 只读检查现有 `reference-index.json` 和角色目录，避免 `character_id` 冲突；此步骤不得写注册表。
2. 创建角色目录和私有 `audio/`；角色 TTS/克隆任务应把来源中的可用参考音频下载、规范化并保存在这里。
3. 将提取出的中文提示词写入 `README.md`，作为对话模式的主要角色指南。
4. 转写本地参考音频并写入非空 `voice-index.json`，每条记录包含真实 `audio_file`、准确文本、语言和情绪标签；只有明确只要文字人格或来源没有音频时才使用纯文字索引。
5. 校验所有 JSON，并运行 `validate_character.py --character-dir ... --strict --skip-registry`。

若用户明确只要文字人格，或来源确实没有可用音频，可在 package-only 校验后结束。用户要求角色 TTS、声音还原、克隆或“千问版”时，不得因为“参考音频不上传 GitHub/公网”而停止本地提取、角色注册和后续已选 TTS 路线。

只有用户明确选择了 TTS 音色路线，才继续注册与验证：

6. 把待写入角色条目保存为角色目录内的 `registry-entry.json`。
7. 结构化解析并原子更新 `reference-index.json` 的 `characters` 数组，禁止用正则替换 JSON。
8. OumuQ 正在运行时，刷新或重启后检查 `GET /api/characters`。
9. 仅在用户要求 TTS 验证时，根据角色配置路由 TTS 并生成一条中性中文验证语句；先验证 WAV，实际播放按用户要求另行验证。

显式选择 TTS 路线后，用以下命令原子更新注册表：

```powershell
py -3.10 -X utf8 scripts\upsert_character.py --workspace "<工作区>" --entry-file "<角色目录>\registry-entry.json" --backup
```

先用 `--dry-run` 检查 create/update 行为；脚本会拒绝缺字段、重复 ID、路径越界和不存在的角色目录/索引。

## TTS 引擎选择

- 中文本地音色克隆：优先 `IndexTTS2`，worker 通常为 `http://127.0.0.1:8766`。
- 日语或多语言本地语音：优先 `Qwen3-TTS`，worker 通常为 `http://127.0.0.1:8765`。
- 已有云端音色或本地参考样本：使用 `Qwen-TTS-API`，worker 通常为 `http://127.0.0.1:8767`。参考音频不得公开托管时优先 Qwen3-TTS-VC，把本地音频编码成 Data URL 直接提交 API；不要选择必须提供公网 URL 的 CosyVoice 路线。
- OumuQ 路由层通常为 `http://127.0.0.1:8780`。

通过 `tts-router` 读取角色注册表并选择引擎。对话模式复用常驻 worker，以本地 HTTP `/speak` 提交。直接 worker 的 `queued` 只表示已接收；OumuQ 外层通常返回 HTTP 200，并把真实状态放在 `worker_response`。生成音频写入工作区缓存或输出目录，不写进 `voice-references`。

本地动态索引角色优先只传 `character_folder`、文本和情绪，不在注册表强制注入固定 `fallback_prompt_audio`，否则会绕过 `voice-index.json` 的语义/情绪选择。只有 worker 不支持角色目录时才使用固定回退音频。

角色 TTS/克隆任务必须先寻找并提取真实本地参考音频；“不要上传 GitHub/公网”不等于“不要下载到本机”，也不等于“不要通过百炼 API 私下提交 Data URL”。只有来源确实没有音频或用户明确只要文字人格时，才使用纯文字索引并报告无法进行声音克隆。

云端音色注册必须通过 OumuQ 的显式 enroll 流程先完成并原子写入私有注册表。共享 worker 的 `/speak` 不得在发现缺少音色时临时自动注册：注册可能超过外层超时、产生重复费用、留下孤立音色，而且进程缓存不能代替持久注册表。模型字段以 `api_target_model` 为规范名；`api_clone_target_model` 只作为旧数据兼容读取，新增或迁移条目不得只写旧字段。

## 角色注册表示例

```json
{
  "id": "my_character",
  "name": "My Character",
  "display_name": "My Character",
  "display_name_zh": "我的角色",
  "character_folder": "voice-references/characters/my_character",
  "index_file": "voice-references/characters/my_character/voice-index.json",
  "fallback_prompt_audio": "voice-references/characters/my_character/audio/sample.wav",
  "tts_engine": "IndexTTS2",
  "worker_url": "http://127.0.0.1:8766",
  "speech_language": "Chinese",
  "visible_language": "Chinese",
  "style_summary": "Warm, clear, conversational delivery.",
  "style_summary_zh": "温和、清晰、自然，使用中文对话。"
}
```

音频文件尚不存在时，不写入虚假的 `fallback_prompt_audio`；可省略该字段或明确标记占位。

## 本地参考音频

仅使用用户有权使用的参考音频：

```json
[
  {
    "id": "warm_001",
    "audio_file": "voice-references/characters/my_character/audio/warm_001.wav",
    "text": "参考音频的准确转写文本。",
    "language": "Chinese",
    "mood": "warm",
    "emotion_tags": ["warm", "clear"],
    "emotion_vector": [0.35, 0, 0, 0, 0, 0, 0.02, 0.3],
    "match_patterns": ["你好|谢谢|温柔"],
    "style_notes": "用户个人非商业用途的本地参考音频。"
  }
]
```

无音频时使用空数组或不含 `audio_file` 的纯元数据示例。不要臆造文件路径。

## 云端音色

`Qwen-TTS-API` 可使用：

```json
{
  "api_voice_id": "<仅在本机私有副本中填写>",
  "api_clone_audio_path": "<仅在本机私有配置中填写参考音频路径>",
  "api_target_model": "<与注册模型一致的 qwen3-tts-vc-* 模型>",
  "api_clone_language_hint": "zh",
  "api_voice_instructions": "使用自然的中文对话语气，表达温和、清晰，保持角色设定。",
  "send_instructions_by_default": false
}
```

云端克隆样本优先使用约 10 至 20 秒、干净且单人说话的本地音频。Qwen3-TTS-VC 由受控脚本把本地文件编码为 Data URL 后直接提交，不需要公开 URL；在“参考音频不得上传公网”的边界下不要改走必须公开托管音频的 CosyVoice 路线。

真正的阿里云千问云端音色有两种方式；它们都不是仅提供 Wiki 链接时的默认动作：

1. 只有用户明确要求原创音色时，才使用 Qwen 声音设计：仅根据人格和语言风格生成原创音色，不提交参考音频。必须提前说明它不会还原角色原声。

```json
{
  "tts_engine": "Qwen-TTS-API",
  "tts_provider": "Alibaba Cloud Model Studio (DashScope)",
  "api_voice_creation_method": "voice_design",
  "api_enrollment_model": "qwen-voice-design",
  "api_target_model": "qwen3-tts-vd-2026-01-26",
  "api_voice_design_language": "zh",
  "voice_mode": "cloud-voice-design"
}
```

`api_voice_prompt` 要描述年龄感、音高、明暗、质感、节奏、力度、情绪范围和应避免的风格，不写“模仿某声优/某角色原声”。`api_voice_preview_text` 使用原创短句。

2. 用户说明个人非商业用途并要求千问声音克隆时，使用 `qwen-voice-enrollment`；把本地样本以 Data URL 直接提交给阿里云百炼，不先上传到 GitHub、公开对象存储或公网 URL。注册与合成必须使用完全相同的 Qwen3-TTS-VC 模型：

```json
{
  "tts_engine": "Qwen-TTS-API",
  "tts_provider": "Alibaba Cloud Model Studio (DashScope)",
  "api_voice_creation_method": "voice_cloning",
  "api_enrollment_model": "qwen-voice-enrollment",
  "api_target_model": "qwen3-tts-vc-2026-01-22",
  "api_clone_language_hint": "zh",
  "voice_mode": "cloud-voice-clone"
}
```

Qwen3-TTS-VC 支持把本地个人非商业参考 WAV 作为 Base64 Data URL 提交；不要把 Data URL、返回的 `voice` 值或原始响应写入公开仓库。参考音频不得公开托管时不要改用需要公网 URL 的 CosyVoice；若用户另行选择 CosyVoice，完成报告必须明确实际模型。

同一人格同时保留本地版和云端版时，不覆盖原角色。保留原 `character_id`，为云端变体使用稳定 ID（例如 `<id>_qwen`），两个注册条目可以复用同一 `character_folder`、证据和 `voice-index.json`；显示名要能区分版本。云端条目不得携带本地 `fallback_prompt_audio`。

## TTS WAV 与可选播放验证

本节不是 package-only 的默认步骤。只有用户已明确选择 TTS 音色路线并明确要求 TTS 验证时才执行；否则跳过本节，不提交请求、不生成 WAV。

1. 检查角色条目、worker URL、语言和音频路径。
2. 选择不含剧透、隐私和长篇版权台词的原创短句。
3. 先提交一条中性语气，再按需要测试一条代表性情绪语句。
4. 记录服务商、API、OumuQ 引擎、真实模型、音色方式、角色 ID、语言和输出位置；不要把验证输出放入参考音频库。
5. worker 或模型不可用时，保留配置并明确说明未完成 WAV/播放验证，不自动下载安装大型模型。

用自动验收脚本等待真实完成并验证 WAV：

```powershell
py -3.10 -X utf8 scripts\verify_tts.py --character-id <id> --text "<原创短句>" --timeout 300 --report "<角色目录>\tts-validation.json"
```

只有报告达到 `character_visible → route_ready → tts_queued → tts_completed → tts_verified`，且输出 WAV 可解码、有正时长，才可宣称“WAV 已验证”。只有额外的 `play=true` 请求具备可观察播放证据并记录 `playback_audio_tested=true`，才可宣称“实际播放已验证”。

验收脚本生成的 `creation` 字段是最终完成报告的事实来源；可见回复不得自行猜测服务商、模型或克隆方式。

## 隐私与公开发布边界

- 用户说明个人非商业用途后，按本地提取和克隆流程执行，无需反复追问版权声明；把用途记录为 `user-requested-private-noncommercial-use`。
- skill、实现代码、测试和脱敏模板可以写入公开仓库；真实 TTS 参考音频、真实音色 ID、签名 URL、密钥、Cookie、个人路径和运行日志不得公开。
- 百炼 API 的受控 Data URL 提交是克隆请求，不等于把音频公开到公网；Data URL 不得写日志、报告或仓库。
- 不声称生成语音来自真实角色、演员或声优本人。
- 公开示例只使用通用角色 ID、安全摘要、占位云字段和纯元数据示例。

## 校验

```powershell
Get-Content -Raw -Encoding utf8 voice-references\reference-index.json | ConvertFrom-Json | Out-Null
Get-Content -Raw -Encoding utf8 voice-references\characters\<character_id>\voice-index.json | ConvertFrom-Json | Out-Null
py -3.10 -X utf8 scripts\validate_character.py --workspace "<工作区>" --character-id <character_id> --strict
```

尚未注册、只准备独立角色包时使用：

```powershell
py -3.10 -X utf8 scripts\validate_character.py --character-dir "<角色目录>" --character-id <character_id> --strict --skip-registry
```

package-only 通过表示资料、证据、人格和索引内部一致；不等于 OumuQ 注册、路由或 TTS 已通过。

若存在相关测试，再运行 OumuQ 的角色加载或路由检查。
