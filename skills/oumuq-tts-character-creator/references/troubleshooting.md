# 排障与防复发清单

本文件只保存可复用的现象、根因、正确做法和验证门禁。不要写真实密钥、voice ID、Data URL、签名 URL、私人音频路径或用户内容。

## 记录模板

每次新增条目使用：

- 现象：
- 根因：
- 正确做法：
- 验证门禁：
- 适用范围：

## 已知问题

### OumuQ worker 名不等于真实模型

- 现象：把 `Qwen-TTS-API` 的 CosyVoice 请求误报成“Qwen3-TTS 创建”。
- 根因：把本地兼容 worker、云服务商和实际合成模型混为一层。
- 正确做法：分别记录 provider、API、OumuQ engine、enrollment model、synthesis model 和 voice creation method。
- 验证门禁：完成报告必须包含真实模型 ID；`cosyvoice-*`、`qwen3-tts-vc-*` 与 `qwen3-tts-vd-*` 分开命名。

### GitHub/公网发布禁令不能阻止本地提取与受控克隆

- 现象：用户说明个人非商业使用并要求克隆，同时要求参考音频不要上传 GitHub/公网；工作流却停止本地下载或停止百炼 API 克隆。
- 根因：把公开发布与受控 API 提交混为一谈，也忽略了声音克隆必须先有本地参考音频。
- 正确做法：先把参考音频提取到本机私有目录；千问克隆优先用 Qwen3-TTS-VC Data URL 直接提交百炼 API，不创建公开 URL。skill、代码和脱敏模板可正常发布，真实 TTS 参考音频不得公开。
- 验证门禁：个人非商业克隆 fixture 必须产生本地 `audio_file` 并进入 `qwen-voice-enrollment`；Git staged/publication fixture 可包含 skill 与测试，但必须拒绝音频后缀、Data URL、真实 voice ID 和私有音频路径。

### 克隆需求被静默替换为 Voice Design

- 现象：用户要求还原角色声音并提供含语音的 Wiki；工作流没有先把音频提取到本机，反而直接创建 Qwen Voice Design 原创音色，最终并非克隆。
- 根因：把“当前还没有本地样本”当成“应改做原创声音”，并为了尽快得到可用 TTS 跳过了声音克隆的必要输入。
- 正确做法：先提取并整理本地参考音频；用户说明个人非商业用途并要求千问版时，用 Qwen3-TTS-VC Data URL 直接提交百炼 API。来源确实没有音频时报告缺少样本，不得自行改成 Voice Design。
- 验证门禁：含 Wiki 音频且要求克隆的 fixture 必须生成本地 `audio_file` 并调用 `qwen-voice-enrollment`；provider 请求不得变成 `qwen-voice-design`。只有用户明确说“原创声音设计”时才允许 Voice Design。
- 适用范围：角色 Wiki 提取、游戏/动漫角色、声优素材、Qwen Voice Design/Cloning 和任何需要上传参考音频的云端 TTS。

### 把“不上传 GitHub”误解为“不提取本地音频”

- 现象：用户要求角色声音克隆，并说明音频人格不要上传 GitHub；工作流却停止下载和本地保存，只生成纯文字人格包，导致没有参考音频可供本地或千问克隆。
- 根因：没有区分三个目的地：本机私有 `voice-references`、阿里云百炼克隆接口、GitHub 公开仓库；把 GitHub 发布禁令错误扩张成所有音频 I/O 禁令。
- 正确做法：角色 TTS/克隆任务先把可用参考音频提取到本机，建立转写和 `voice-index.json`；千问克隆按用户要求从本地选择样本，以 Data URL 直接提交百炼。skill、代码、测试和脱敏模板可以上传 GitHub，但真实 TTS 参考音频不得进入 Git、公开 URL 或公网对象存储。
- 验证门禁：含 Wiki 音频且要求克隆的 fixture 必须产生本地私有音频记录和非空 `audio_file`，并可进入克隆注册；“不要上传 GitHub/公网”不得让下载、本地提取或 Data URL 克隆调用变成 0。发布扫描必须允许 skill 文件，同时阻止音频后缀、Data URL、私有音频路径和真实 voice ID 进入 Git staged files。
- 适用范围：本地声音克隆、Qwen/DashScope 声音复刻、voice-references、GitHub 提交与任何同时涉及私有素材和公开代码仓库的任务。

### Qwen 声音设计与声音复刻请求体不同

- 现象：非 CosyVoice 分支仍发送 `action=create_voice`、`prefix` 或字符串形式 `audio`，被服务商拒绝。
- 根因：沿用了 CosyVoice `voice-enrollment` 协议。
- 正确做法：声音设计使用 `qwen-voice-design / action=create / preferred_name / voice_prompt / preview_text`；声音复刻使用 `qwen-voice-enrollment / action=create / preferred_name / audio.data`。
- 验证门禁：dry-run 单测逐字段断言官方请求体；返回音色读取 `output.voice`，CosyVoice 才读取 `output.voice_id`。

### Qwen3-TTS-VC/VD 不接收 CosyVoice 控制字段

- 现象：真正 Qwen VC/VD 合成因 volume、speech rate、pitch 或 instructions 字段失败。
- 根因：把 CosyVoice 或 Instruct 模型的控制字段无条件转发。
- 正确做法：Qwen VC/VD 仅发送其支持的 text、voice 和可选 language type；按模型家族白名单转发控制字段。
- 验证门禁：单测断言 VC/VD payload 不含 unsupported controls 与 instructions。

### 共享云 worker 串用启动角色音色

- 现象：会话 B 请求角色 B，却继承 worker 启动时角色 A 的 voice ID、模型或说明。
- 根因：把进程默认角色当成全局当前角色，或只在启动时加载注册表。
- 正确做法：每次请求显式发送 `session_id + character_id`；提交时重新解析角色并把 voice/model/language 快照进 job。显式角色配置不完整时立即报错。
- 验证门禁：A/B/A 交错并发测试必须得到 A/B/A 三个独立快照；不得因 status 显示不同角色而重启共享 worker。

### 显式角色仍接受客户端残留的 voice/model/folder

- 现象：请求声明角色 B，却同时带着旧会话角色 A 的 `voice_id`、model 或 `character_folder`，最终显示 B 身份却使用 A 云端音色/本地参考音频，或音色与模型不兼容。
- 根因：把 `character_id` 只当查默认值；请求字段仍高于角色注册表，而且 Pydantic extra/旧客户端会真实携带残留字段。
- 正确做法：显式 `character_id` 时，私有注册表中的 `api_voice_id`、规范 `api_target_model` 和存在的 `character_folder` 是不可变角色绑定，OumuQ/云 worker 必须覆盖或移除请求残留。只有无显式角色的 legacy 路径允许请求 override；语言和明确的发声情绪控制仍可按请求变化。
- 验证门禁：A/B/A 并发测试故意给 B 请求塞入 A 的伪音色、模型和目录，下游内存 job 仍必须使用 B 配置，公共响应与落盘文件均不得回显任一真实值。

### 不同 worker 各自播放会发生叠音

- 现象：本地与云端生成同时完成后一起播放。
- 根因：每个 worker 只有自己的 FIFO，没有跨进程播放仲裁。
- 正确做法：单一 OumuQ 进程按路由提交顺序分配序号，强制下游 `play=false`，等待生成后进入唯一阻塞式播放队列；实际播放前再取得主机级文件锁，避免多个 OumuQ 进程同时占用扬声器。进程间只保证不叠音，不保证统一 FIFO 顺序。
- 验证门禁：进程内并发测试中播放器最大 active 数必须为 1；后提交先生成也不能越过前序；失败任务必须释放后续序号；跨进程锁测试必须证明临界区不重叠。状态应写 `process-fifo+host-lock`、`ordering_scope=process`、`playback_mutex_scope=host`，不得虚报跨进程全局 FIFO。

### 预留播放序号后的非网络异常会永久卡住队列

- 现象：请求已经取得播放序号，但写运行记录、解析 JSON、调度监控或其他非 `httpx` 步骤抛错；后续已生成音频一直等待。
- 根因：异常处理只覆盖网络请求，没有保证每个已预留序号最终进入 ready 或 generation_error。
- 正确做法：预留后把写日志、请求、响应解析和调度全部放进同一 `try`；取消和任意异常都先 `mark_failed`，错误日志采用 best-effort，日志失败不得遮蔽原错误或再次卡队列。
- 验证门禁：注入 `write_json`/JSON 解析异常，首序号必须变为 `generation_error`，后续序号仍能进入播放队列。

### 角色切换与异步响应会污染另一个会话

- 现象：旧角色的 route/infer 响应覆盖新角色；prompt audio、参考文本或情绪字段跨角色残留。
- 根因：页面共用全局表单状态，刷新时仍信任过期的 saved role，异步请求只校验 epoch/角色而没有校验用户编辑版本。
- 正确做法：每个页面使用独立 session ID；草稿按“会话 × 角色”保存；刷新优先保留仍存在的 active role 并同步 active/saved；切换时 abort 旧请求。路由响应额外校验 worker URL override revision，参数推断额外校验 form revision 与原始文本。
- 验证门禁：两个标签页分别选择不同角色并重载；字段和 worker URL 必须保持独立。角色 A→B→A 时 A 草稿恢复、B 看不到 A 字段；等待路由/推断响应时手工编辑地址或文本，旧响应不得覆盖新值。

### 注册表更新后“刷新”未出现新角色

- 现象：后端已经新增角色，WebGUI 点击刷新仍显示旧数量。
- 根因：刷新按钮只更新 worker、播放和运行记录，没有重新请求 `/api/characters`。
- 正确做法：显式刷新时先保存当前角色草稿并重新加载角色列表，再刷新状态。
- 验证门禁：新增注册表条目后无需整页重载，点击刷新即可看到新角色且当前草稿不丢失。

### Qwen Voice Design 预览 WAV 的 RIFF 长度是占位值

- 现象：预览文件只有数秒，却被 WAV 解析器识别成数小时。
- 根因：服务商返回的流式 WAV 头把 RIFF/data 长度保留为 `0x7fffffff`。
- 正确做法：保存预览后按实际文件长度重写 RIFF size 与 data size，再做 wave 解码。
- 验证门禁：测试使用占位头样本；修复后帧数、时长、采样率与文件大小一致。

### 可见 API 或错误信息泄露云端音色信息

- 现象：`/api/characters` 已脱敏，但 route、speak、runs、worker status、job status、启动日志、错误字符串或 provider response 仍包含真实 voice ID、clone URL、Data URL 或参考路径。
- 根因：只给单一端点做脱敏，内部请求快照又被直接持久化和返回；worker 的状态对象与错误路径没有共用公开视图。
- 正确做法：内部请求仍可短暂携带真实值发给 worker，但落盘前和所有公共边界统一递归脱敏，只返回 `voice_configured` / `reference_audio_configured` 布尔值；worker job、status、POST、启动日志与错误也使用同一规则。原始 voice ID 只留本机私有注册表。
- 验证门禁：对 characters、route、speak、runs、worker status/job 和完成报告做整棵 JSON 字符串扫描；不得出现 `voice_id`、真实音色值、参考 URL、Data URL 或私有音频路径。

### 脱敏只删键名，秘密仍嵌在错误字符串中

- 现象：对象中的 `voice_id` 字段已删除，但同一值还出现在 `error`、`message`、provider response 或 URL 中，公共 JSON 仍泄露。
- 根因：逐键删除没有先收集整棵对象的秘密值，也没有处理错误文本里的 Data URL/HTTP URL。
- 正确做法：先从整棵内部对象收集 voice、voice_id、参考路径/URL 等秘密字符串，再递归生成公开副本；所有兄弟字段字符串都替换这些值，error/message/detail 中额外清理 Data URL 与远端 URL。
- 验证门禁：用伪音色同时填入 `voice_id` 和错误文本，公开 route/speak/status/runs 的整棵序列化结果中不得出现伪值、URL 或 Base64 片段。

### worker API 已脱敏但运行期缓存仍落盘真实音色

- 现象：`/status` 和 POST 响应只显示 `voice_configured`，但 `job.json`、分段 metadata 的 settings/provider response 仍保存真实 voice、参考音频 data/url。
- 根因：内存 job 为合成保留秘密是必要的，却直接把同一对象传给 `write_json`；公共视图没有复用于持久化边界。
- 正确做法：内存保留私有 job，仅在调用 provider 时使用；所有 job/cache/metadata 落盘统一通过持久化安全视图，voice 改布尔值，provider response 递归删除 voice/voice_id/audio.data/audio.url 和私有 URL。
- 验证门禁：创建带伪 voice 与伪音频 URL 的任务后，逐个读取新写的 job/metadata JSON 并做字符串扫描；内存请求可用，磁盘文件必须零命中。历史私有缓存不自动删除，清理需用户单独授权。

### 参考音频文件列表使用了未覆盖的字段名

- 现象：`prompt_audio` 已脱敏，但 IndexTTS2 状态里的 `prompt_audio_files` 仍经 OumuQ 代理到公开 API 和验收报告。
- 根因：敏感字段名单只覆盖单数/输入字段，没有覆盖 worker 产出的文件列表与 source/reference 变体。
- 正确做法：把 `prompt_audio_file(s)`、`reference_audio_file(s)`、`source_audio_path(s)` 纳入统一递归脱敏，只返回 `prompt_audio_configured` 与可选 count，不返回路径列表。
- 验证门禁：status/speak/runs 使用伪私有路径，整棵 JSON 不得包含文件名；只允许布尔配置状态和数量。

### 自定义注册端点或任意本地路径可造成密钥与文件外传

- 现象：调用方把 enroll endpoint 指向第三方主机即可带走 DashScope API Key，或把本机任意文件路径伪装成参考音频上传/编码后外传。
- 根因：把请求提供的 endpoint、request JSON path 和 audio path 当成可信配置，没有做主机、协议、目录、后缀与大小边界。
- 正确做法：注册端点只允许官方 DashScope HTTPS customization 路径和受支持的专属域名；禁止凭据、查询串与片段。请求 JSON 必须位于规定的 `voice-clone-requests` 目录；参考音频必须解析真实路径后位于授权音频根目录，并限制音频后缀与大小。公开音频上传另设显式允许根目录。
- 验证门禁：恶意 endpoint、目录穿越、符号链接逃逸、非音频文件和超限文件均在发起网络请求前返回 400；dry-run 也不得回显原始 URL/Data URL。显式 path 与“按角色自动发现”两条分支都必须在 `resolve(strict=True)` 后重新校验真实路径，列表阶段也要丢弃越界链接。

### 共享 worker 在 `/speak` 中自动注册音色

- 现象：首次合成超过 OumuQ 请求超时、再次调用重复付费，云端出现孤立音色；worker 重启后缓存音色又丢失。
- 根因：把一次性、可能收费且耗时的音色注册隐式塞进普通合成请求，只缓存于进程内存，没有原子写回私有注册表。
- 正确做法：显式角色缺少 `api_voice_id` 时立即失败并提示先走 OumuQ enroll；注册成功后持久化私有注册表，再允许 `/speak`。只有无显式角色的旧兼容流程可保留受控的 legacy helper，不能作为正常角色路径。
- 验证门禁：显式角色缺音色的 `/speak` 测试必须断言 enroll 调用次数为 0；完成注册并重载注册表后才允许合成。

### 新旧模型字段并存导致实际模型选择漂移

- 现象：角色明明配置新模型，worker 或验收报告仍使用旧 clone target；不同组件解析出不同模型。
- 根因：有的代码只读旧字段 `api_clone_target_model`，有的写新字段 `api_target_model`，优先级未统一；enroll 请求允许临时覆盖 target，却只把 voice ID 写回注册表，导致用模型 X 注册、模型 Y 合成。
- 正确做法：`api_target_model` 是规范字段，读取时优先；`api_clone_target_model` 只作旧数据兼容。注册成功必须把实际 payload 的 target/enrollment model、creation method 与 voice ID 一起原子写回私有角色条目；存在旧兼容字段时同步为相同值。
- 验证门禁：同时给出两个不同值时，OumuQ、worker job 快照和验收报告都必须选择 `api_target_model`；enroll 临时覆盖 pending target 后，registry、route 和 worker 必须全部使用新 target；仅旧字段的数据仍可兼容运行。

### 请求文件角色与 API character_id 不一致导致错绑音色

- 现象：显式传入角色 A 的 pending JSON 路径，同时把 API `character_id` 写成 B；系统用 A 的音频/prompt/model 注册，却把结果写到 B。
- 根因：显式 path 分支只校验目录，不校验文件内 `character.id` 与请求角色；自动匹配和写回又混用大小写敏感/不敏感比较，可能追加重复角色。
- 正确做法：角色 ID 采用稳定小写格式；显式 request path 与 character_id 同时出现时必须在任何网络/注册表写入前精确按规范 ID 校验一致。自动发现、registry 更新和 clone URL 更新统一使用大小写归一比较，并把写回 ID 规范化为小写。
- 验证门禁：path=A + character_id=B 必须返回 400，provider 调用次数为 0 且 registry 未变化；大写或非法 ID 在 Pydantic 边界返回 422；legacy registry 比较不得产生大小写重复项。

### 状态轮询一次失败就释放任务

- 现象：worker 已正常生成，但一次连接重置或短暂 404 让播放任务直接标记失败，音频不再播放。
- 根因：状态轮询把任何瞬时异常当作终态。
- 正确做法：对连续轮询故障设置可配置宽限窗口；任一次成功就重置窗口，只有连续失败超过宽限或总等待超时才标记 generation_error。错误记录只保存异常类型，不回显私有响应。
- 验证门禁：模拟失败→成功必须继续完成；模拟连续失败超过宽限必须释放后续序号。

### queued 不等于 TTS 已验证

- 现象：worker 返回 queued 就宣称角色语音完成。
- 根因：没有轮询最终 job、核对任务身份或解码输出；并且用 `play=false` 提交后仍把策略检查写成“实际播放已测试”。
- 正确做法：等待 done/error，核对最终 job 的 character ID 与实际模型，确认输出不在参考库、WAV 可解码、有正时长并记录采样率。`play=false` 只能写 `playback_policy_verified=true` 与 `playback_audio_tested=false`；只有真实播放请求和可观察播放结果才能声称扬声器播放已测试。
- 验证门禁：验收必须达到 `character_visible → route_ready → tts_queued → job_identity_verified → tts_completed → tts_verified`；角色/模型错配立即失败，完成元数据不得把策略验证冒充实际播放。

### WAV 解码验证被文案写成实际扬声器试听

- 现象：`verify_tts.py` 固定使用 `play=false`，报告也写 `playback_audio_tested=false`，但 skill 最终状态仍说“已试听验证/试听完成”。
- 根因：把“生成了可解码 WAV”与“扬声器确实播放且可观察”混成一个完成状态。
- 正确做法：完成状态拆成“WAV 已验证”和“实际播放已验证”。`tts_verified` 只证明 WAV 生成、身份、模型、解码与时长；只有额外 `play=true` 并记录可观察播放证据时才可写 `playback_audio_tested=true` 或声称听过。
- 验证门禁：默认 verify 报告必须始终为 `playback_audio_tested=false`；skill 与最终回复不得出现“已试听”措辞，除非存在单独真实播放证据。

### 路由脱敏后固定参考音频被验收脚本误判为不存在

- 现象：route 把固定 `prompt_audio` 脱敏为 `prompt_audio_configured=true`，验收脚本仍只检查原始 path 键，因而把固定音频路由误报为动态角色目录路由。
- 根因：隐私契约升级后，消费者没有同时识别新的布尔配置字段。
- 正确做法：需要拒绝固定参考音频的验收同时检查旧响应 `prompt_audio` 与新响应 `prompt_audio_configured`；报告只记录布尔状态，不恢复或显示路径。
- 验证门禁：构造只有 `character_folder + prompt_audio_configured=true` 的脱敏 route，`route_ready` 必须失败且不能继续调用合成。

### 仓库 skill 与已安装 skill 不一致

- 现象：仓库已修复，但新 Codex 会话仍使用旧提示词或旧 worker。
- 根因：只改源码，没有同步用户 skills 目录或重启常驻 worker。
- 正确做法：修改仓库作为单一来源，运行安装脚本，再比较关键文件哈希并重启对应 worker。
- 验证门禁：仓库/安装版哈希一致，`quick_validate.py` 通过，`/status` 显示动态角色能力与正确播放策略。

### Windows 补丁工具在沙箱初始化阶段失败

- 现象：补丁命令在读取文件前因 Windows writable-root/sandbox 初始化失败。
- 根因：工具环境无法组合当前写根，不是补丁内容冲突。
- 正确做法：权限调整后重试；仍失败时使用带“原文断言 + 临时文件 + 原子替换”的 UTF-8 结构化脚本，并立即运行 diff、语法检查和测试。中文 JSON 必须结构化解析。
- 验证门禁：每个替换断言只命中一次；无临时文件残留；`git diff --check`、JSON 解析和相关测试全部通过。

### PowerShell 生成 skill 元数据时吞掉 `$skill-name`

- 现象：`agents/openai.yaml` 的 `default_prompt` 从“使用 `$oumuq-tts-character-creator`”变成“使用 `-tts-character-creator`”。
- 根因：把含 `$` 的 `--interface default_prompt=...` 放进 PowerShell 双引号，Shell 在 Python 收到参数前先做变量展开。
- 正确做法：在 PowerShell 中用单引号包住包含 `$skill-name` 的整个参数，或用停止解析/结构化脚本传参；生成后立即读取 YAML 核对完整 skill 名。
- 验证门禁：`quick_validate.py` 通过之外，还必须断言 `agents/openai.yaml` 精确包含 `$oumuq-tts-character-creator`；只做 YAML 语法校验不够。

### 字段迁移后 JSON 示例出现重复键

- 现象：把旧 `api_clone_target_model` 机械替换为 `api_target_model` 后，示例中已有的新字段与替换结果并存，形成两个同名键。
- 根因：文本替换只保证旧字段消失，没有结构化解析每个 JSON code block 或检查重复键；普通 JSON 解析器还会静默保留最后一个值。
- 正确做法：模型字段迁移后逐个检查示例；新增/更新 JSON 时使用拒绝重复键的解析器或专门测试，规范字段只出现一次。
- 验证门禁：skill 测试必须统计声音设计与声音复刻示例中的 `api_target_model`，每个对象恰好一次；不能只运行允许重复键的默认 `json.loads`。

### HTTP 200 的动态 Wiki 空壳被误判为正文

- 现象：`extract_sources.py` 返回 `success`，但 source bundle 只有页面标题和“浏览器版本过低”等几十字提示，后续仍据此创建角色。
- 根因：只检查请求是否成功和提取文本是否非空，没有正文质量门；库街区角色页实际由 SPA 调用官方接口渲染。
- 正确做法：直连 HTML 命中兼容/JavaScript 提示或正文极短时判为不足并进入回退。对 `wiki.kurobbs.com/mc/item/<id>` 优先调用官方 `getEntryDetail` 接口，只白名单保存基础资料、角色档案和角色语音文字，丢弃 `playUrl`、图片 URL、创建者等媒体字段。
- 验证门禁：壳页 fixture 必须失败且不能生成 `success`；库街区 API fixture 必须提取角色名、档案和语音文字，同时输出中不得出现 `playUrl`、媒体域名或“角色养成”数值。
- 适用范围：SPA Wiki、JavaScript 动态资料页、正文由 XHR/fetch 加载的角色站点。

### 动态 Wiki 语音文字已提取但 voice-index 仍为空

- 现象：source bundle 已包含角色语音标题和台词文字，`character-evidence.json` 却仍写 `voice_entry_count: 0`，`voice-index.json` 也是空数组。
- 根因：通用资料准备脚本只把正文切成证据句，没有识别库街区接口输出的“角色语音 / 个性语音 / 战斗语音”结构。
- 正确做法：对受控的库街区接口文本格式解析中文语音标题与台词，建立无 `audio_file`、无媒体 URL 的纯文字索引，并同步来源/索引计数；已有非空索引不自动覆盖。
- 验证门禁：fixture 同时包含个性语音和战斗语音时，必须生成稳定且不重复的两类 ID，严格模式计数一致；序列化结果不得出现 `playUrl`、音频 URL 或本地参考路径。
- 适用范围：网页提供语音文字但没有音频授权，或只需 Voice Design 人格证据的角色包。

### 站点适配完整性门硬编码当前角色名

- 现象：守岸人测试能通过，但换成同站点其他角色时，官方接口已返回完整正文仍被判“正文不足”。
- 根因：完整性判断直接搜索当前角色常量，而不是读取接口返回的条目标题。
- 正确做法：以接口 `content.title` 作为动态期望值，并结合正文长度检查；站点适配器不得写死某个角色名。
- 验证门禁：同一 fixture 把标题和角色名替换为任意其他值仍能通过；标题缺失或未出现在提取结果中才失败。
- 适用范围：所有复用同一 API 的多角色 Wiki 适配器。

### 没有本地参考音频被误报为云端音色无法验证

- 现象：证据包和 Qwen Voice Design 配置都完整，严格校验仍提示“无法完成音色试听”，容易被误认为云端原创音色流程受阻。
- 根因：校验器把“没有本地参考音频”与“任何 TTS 都无法验证”混为一谈，也沿用了未区分 WAV/实际播放的旧“试听”措辞。
- 正确做法：只说明本地参考音色未验证；仅当角色记录了用户已明确选择云端 Voice Design，才继续显式注册并做云端 WAV 身份、模型和解码验证。旧配置或仅人格包不得据此触发注册。实际扬声器播放仍需独立证据。
- 验证门禁：无 `audio_file` 的云端角色只产生非阻塞提醒，校验结果仍可 `ok: true`；提示中不得出现“无法完成音色试听”，最终报告继续区分 `WAV 已验证` 与 `实际播放未测试`。
- 适用范围：用户已明确选择的 Qwen Voice Design，以及其他无需参考音频的云端原创音色。

### 浏览器渲染回退无法附加动态页面

- 现象：动态页需要最终 DOM，但新建的内置浏览器页在导航阶段超时，页面列表仍为空；反复新建页面也无法取得正文。
- 根因：当前浏览器承载面没有成功附加 webview，不代表来源失效，也不代表目标站点没有正文。
- 正确做法：先按浏览器控制说明完成故障判断；用户未指定浏览器时，可改用已经打开目标页的 Chrome 标签。若已识别站点官方 API，则优先回到 API，不为读取正文反复重试空白页面。
- 验证门禁：浏览器附加失败不得把空 DOM 写入 source bundle；切换表面或官方 API 后仍需执行正文质量门，并在结束前释放研究标签页。
- 适用范围：SPA 页面、内置浏览器暂不可用、Chrome 已有目标页或官方 XHR 可用的提取任务。

### 脱敏扫描用子串匹配误报安全布尔键

- 现象：公开 API 只包含 `voice_id_configured` / `api_voice_configured` 等安全布尔值，扫描却因搜索 `voice_id` 子串而报告泄露。
- 根因：检查的是任意字符串子串，不是敏感 JSON 键或已知秘密值；安全状态字段包含相同词根。
- 正确做法：秘密扫描同时使用两层门禁：精确匹配 `"voice_id":`、`"api_voice_id":` 等敏感键，并扫描从私有对象收集到的实际秘密值。安全的 `*_configured` 布尔键应明确允许。
- 验证门禁：公开响应含安全布尔键时扫描必须通过；注入伪 `api_voice_id` 键或把伪秘密嵌入错误字符串时必须失败。
- 适用范围：角色列表、route、speak、worker status、runs、验收报告和缓存隐私扫描。

### PowerShell foreach 结果直接接管道触发解析错误

- 现象：`foreach (...) { ... } | ConvertTo-Json` 在组合命令中报 `An empty pipe element is not allowed`，诊断尚未执行就失败。
- 根因：把 PowerShell 的 `foreach` 语句当成可直接接管道的表达式，且单行拼接让解析边界更模糊。
- 正确做法：先用 `$rows = @(foreach (...) { ... })` 收集结果，再单独执行 `$rows | ConvertTo-Json`；复杂诊断优先拆成可独立验证的语句。
- 验证门禁：服务重启脚本先以相同 PowerShell 版本做解析/小样本运行，输出必须是有效 JSON；解析失败不得继续停止或重启进程。
- 适用范围：Windows 服务诊断、批量端口/进程检查、结构化 JSON 输出。

### Get-NetTCPConnection 非终止错误被误判为服务离线

- 现象：服务 HTTP 健康检查正常，`Get-NetTCPConnection` 却打印非终止错误并让结果对象中的 PID 变成空值，命令最终仍可能退出 0。
- 根因：单一系统 cmdlet 的瞬时/WMI 错误被当成服务权威状态；PowerShell 非终止错误没有被 `$ErrorActionPreference` 或 `-ErrorAction Stop` 提升。
- 正确做法：端口检查使用 `-ErrorAction Stop` 并捕获失败；失败时交叉检查本地健康端点、已启动 PID 的 `Get-Process` 和只读 `netstat -ano`。只有多个独立信号一致失败才判服务离线。
- 验证门禁：注入端口 cmdlet 失败时，若健康端点和进程仍正常，最终状态必须为“诊断降级、服务在线”；不得输出空 PID 后宣称重启失败。
- 适用范围：Windows 上的 OumuQ、TTS worker 和其他 localhost 常驻服务。

### 并行只读检查中 rg 无匹配导致整批失败

- 现象：并行执行哈希、校验和文件搜索时，某个 `rg` 因“无匹配”返回 1，编排层把整批视为失败，其他已完成结果没有显示。
- 根因：把 `rg` 的退出码 1（正常无匹配）当成执行错误，并与必须成功的校验放在同一个 fail-fast 批次。
- 正确做法：预期允许无匹配的搜索单独运行，或显式把退出码 1 转成空结果；哈希、测试、安装等强校验保留 fail-fast，不与探索性搜索耦合。
- 验证门禁：无匹配 fixture 必须返回空列表且不遮蔽并行的哈希/校验输出；退出码大于 1 仍按真实错误处理。
- 适用范围：skill 同步审计、可选启动脚本搜索、隐私扫描和仓库调查。

### ASCII Base64 携带中文迁移内容导致字符损坏

- 现象：为绕开 PowerShell 中文转义而把迁移内容编码为 Base64，但解码后的中文策略字符串已损坏，原文断言无法命中或即将写入乱码。
- 根因：编码端先把中文按 ASCII 处理，字符在 Base64 之前就已不可逆丢失；Base64 本身不会修复错误的字符编码。
- 正确做法：编码和解码两端都显式使用 UTF-8，并在写入前断言解码文本包含预期中文、JSON 可解析且原文只命中一次。更优先使用结构化 JSON 读写，避免传递整段中文替换脚本。
- 验证门禁：包含中文标点和路径的 round-trip fixture 必须逐字节一致；任何替换断言失败时不得写目标文件。
- 适用范围：中文 JSON、验收报告、角色提示词和 PowerShell/脚本间参数传递。

### 迁移脚本先备份后因错误相对路径半途失败

- 现象：脚本已创建 `pre-*` 备份，随后按错误的相对目录查找 worker job/report 而失败；目标文件未更新，却留下看似迁移完成的备份。
- 根因：相对路径的基准目录与脚本工作目录假设不一致，且依赖检查发生在备份之后。
- 正确做法：先解析并验证所有输入、job、报告和目标的绝对路径，再创建备份并执行原子写入；备份名称必须清楚标记为 `pre-migration`，不能作为成功标记。
- 验证门禁：缺少任一依赖时目标与备份数量都不变；完整依赖时只生成一个备份、一个临时文件并原子替换，完成后重新读取目标验证新字段。
- 适用范围：TTS 验收报告迁移、注册表升级、缓存/job 证据回填和跨目录脚本。

### 台词顺序号作为身份导致插入时 ID 漂移

- 现象：语音索引使用 `personality-001/002` 等位置号；Wiki 在中间插入一条台词后，后续所有 ID 改变，角色档案引用和手工标注失去对应关系。
- 根因：把当前数组顺序当成长期身份，而不是由条目自身的稳定内容生成受控身份。
- 正确做法：用“类别 + 语言 + 标题 + 文本”的 UTF-8 内容哈希自动生成稳定 ID；顺序只负责展示，不参与身份。刷新旧索引必须显式开启，并拒绝覆盖含 `audio_file` 或非库街区生成条目的索引。
- 验证门禁：同一组台词交换顺序后，按标题映射得到的 ID 完全一致；文本改变时 ID 改变；安全刷新遇到手工/音频条目必须在写入前失败并保留原文件。
- 适用范围：Wiki 台词索引、可增删排序的配置子项、需要长期证据引用的结构化条目。

### Windows 受限令牌阻止 multiprocessing 命名管道

- 现象：主机级播放锁的跨进程测试在 `multiprocessing.Queue()` 创建阶段报 `PermissionError: [WinError 5]`，而同一测试在非受限进程中通过。
- 根因：Windows 受限令牌/沙箱禁止创建测试所需的命名管道，失败发生在播放锁代码运行之前，不是互斥逻辑回归。
- 正确做法：测试仅在捕获到明确的命名管道 `PermissionError` 时标记环境跳过；随后在获准的非受限环境重跑同一测试/全量套件，确认跨进程临界区确实不重叠。
- 验证门禁：受限环境显示明确 skip 原因而非失败；非受限环境该测试必须通过，不能用 skip 代替真实跨进程验证。
- 适用范围：Windows `multiprocessing`、命名管道、跨进程文件锁与受限测试运行器。

### Windows PowerShell 5 把无 BOM 中文脚本读成乱码

- 现象：迁移包中的中文 `install.ps1` 内容本身完整，但用系统 `powershell.exe` 执行时中文变成乱码，并报字符串缺少结束引号。
- 根因：Windows PowerShell 5 对无 BOM UTF-8 脚本使用系统代码页解释；乱码字节可能改变引号附近的解析结果。PowerShell 7 的 UTF-8 默认行为不能代表目标电脑上的 Windows PowerShell 5。
- 正确做法：需要兼容 `powershell.exe` 的中文 `.ps1` 发布文件保存为 UTF-8 with BOM，或把可执行脚本文案限制为 ASCII；打包前分别做语法解析和一次隔离安装演练。
- 验证门禁：用 Windows PowerShell 5 的 parser/实际进程加载最终归档前的脚本，退出码必须为 0；只用编辑器、Python 或 PowerShell 7 读取成功不算通过。
- 适用范围：Windows 私人迁移包、中文安装脚本、`.ps1` 发布物和需要兼容 Windows PowerShell 5 的自动化。

### 迁移包把 Voice Design 版本当成声音克隆

- 现象：迁移包保留了角色的云端 voice ID，说明却把它称作“声音克隆”；实际注册表仍是 `voice_design / qwen-voice-design / qwen3-tts-vd-*`，没有本地克隆样本。
- 根因：打包验收只检查 voice ID 是否存在，没有核对创建方式、注册模型、合成模型和本地参考音频，导致“有云端音色”被错误等同于“已声音克隆”。
- 正确做法：迁移前逐角色核对 `api_voice_creation_method=voice_cloning`、`api_enrollment_model=qwen-voice-enrollment`、`api_target_model=qwen3-tts-vc-*`、本地 `audio_file` 与真实 voice ID；再走正式 OumuQ 链路验证 WAV。Voice Design 旧报告单独标记 legacy，不能作为克隆证据。
- 验证门禁：归档内对每个宣称克隆的角色断言上述字段、voice ID 和本地样本均存在，且 `tts-validation` 的实际模型与角色一致；只检查 `api_voice_id` 的测试必须失败。
- 适用范围：私人 TTS 迁移包、Qwen Voice Design/Cloning 迁移、角色变体和完成报告。

### 库街区文字提取丢弃 playUrl 后没有本地克隆样本

- 现象：守岸人已提取 60 条角色语音文字，`voice-index.json` 却没有任何 `audio_file`，因此无法进行声音克隆。
- 根因：公开安全的资料提取器故意丢弃 `playUrl`，但后续克隆流程没有进入独立的本机私有音频下载阶段。
- 正确做法：公开证据包继续丢弃媒体 URL；角色 TTS/克隆任务则从官方接口内存中读取 `playUrl`、直接下载到本机私有 `audio/kurobbs_cn/`，按标题和台词回填索引，私有结果仍不保存公网 URL。
- 验证门禁：接口含 N 条语音时必须下载 N 个可解码音频并匹配 N 条索引；本地路径全部存在、媒体 URL 不落盘。音频数为零时不得注册克隆或降级 Voice Design。
- 适用范围：库街区/Kurobbs SPA、公开证据与私有音频分流、角色 Wiki 声音克隆。

### 系统没有 ffprobe 时 WAV 时长被误报为零

- 现象：参考 WAV 文件正常，但 `ffprobe` 不在 PATH；批量检查继续把空输出转换成 `0.00` 秒，同时打印多条命令不存在错误。
- 根因：没有在运行前检查探针工具，也没有让失败成为终止错误。
- 正确做法：先检测 `ffprobe`；不存在时，对标准 PCM WAV 使用 Python `wave` 按帧数和采样率计算时长，其他格式再定位项目自带 ffprobe 或明确报告未验证，不能写成零秒。
- 验证门禁：缺少 ffprobe 的 WAV fixture 仍应得到真实正时长；非 WAV 且无可用探针时必须失败而不是返回 `0`。
- 适用范围：参考样本选择、迁移包音频检查和 Windows 未配置 ffmpeg PATH 的环境。

### Qwen 声音复刻注册成功但因参考文本 WER 过高而降级

- 现象：`qwen-voice-enrollment` 返回了可用音色，HTTP 和注册流程都成功，但响应同时包含 `fallback_mode: true` 与 `fallback_reason: wer_too_high`；后续合成可能出现音色、韵律或长句表现不稳定。
- 根因：人工填写的参考文本与音频中的真实发音不够一致，或把多条带表演停顿的角色语音拼接后仍按页面台词逐字提交；只检查 `voice_configured` 会漏掉服务端已经启用降级处理。
- 正确做法：优先使用逐字核验且连续、干净的 10 至 20 秒单人同语言样本；无法可靠取得逐字转写时停止生产注册并继续找样本，不得删除参考文本来绕过 WER。候选音色使用独立角色 ID 注册，保留旧生产绑定，直到同测试集 A/B 听审通过。
- 验证门禁：注册响应除了 `voice_configured=true`，还必须拒绝任何 `fallback_mode=true` 或非空 `fallback_reason`；随后至少覆盖短句、普通句、长句和代表性情绪句，逐一核对角色 ID、实际模型、WAV 解码、正时长与采样率。只有用户实际 A/B 听审确认后才允许切换生产绑定；解码通过与无 fallback 都不能替代听感确认。
- 适用范围：Qwen3-TTS-VC、游戏角色参考音频、Wiki 台词与任何可选提交参考文本的声音复刻流程。

### 云 TTS/ASR 归档后旧进程与测试仍可继续触发历史路径

- 现象：配置文件已经切为本地模型，但旧云 worker 仍监听端口；或 pytest 继续收集归档目录中的云端测试和实现。
- 根因：磁盘配置迁移不会替换已加载到内存的进程；pytest 默认递归发现也不会自动把名为 `archive` 的目录视为不可执行资料。
- 正确做法：停止云 worker，重启本地路由层；在项目 pytest 配置中把测试范围固定到活跃 `tests/` 并排除归档目录。云端 HTTP 入口返回明确的 `410 Gone`，不能只依赖“没有 API Key”。
- 验证门禁：云 worker 端口无监听；角色表只含本机 worker；能力表只列本地模型；云注册与公网音频上传端点返回 410；全量测试不收集归档目录。
- 适用范围：付费 TTS/ASR 下线、worker 迁移、功能归档和本地模型强制策略。

### NAS/UNC 工作区让本地 ONNX-VITS 前端依赖连续失效

- 现象：在映射盘或 UNC 工作区创建虚拟环境时 `ensurepip` 报实际路径与请求路径不一致；`pkg_resources` 扫描网络目录触发 Windows I/O 错误；`pyopenjtalk` 报 NumPy dtype size changed，或 MeCab 因字典路径指向父目录而初始化失败。
- 根因：网络工作区存在不同的路径身份；旧式包发现会递归扫描不可用的 NAS 条目；预编译 `pyopenjtalk` 扩展按 NumPy 1.x ABI 构建；OpenJTalk 需要实际包含字典文件的目录而不是下载包的上级目录。
- 正确做法：依赖安装到项目内已忽略的独立 target 目录，不把虚拟环境或模型提交 Git；固定 `numpy>=1.24,<2`；普通话前端避免为了拼音引入会触发全局包扫描的依赖；日语前端显式传入本地 OpenJTalk 实际字典目录，运行期不自动联网下载。常驻 worker 预加载并缓存 ONNX session。
- 验证门禁：中文、日文、英文三套前端都必须生成模型词表内的 token；worker 必须从 `queued` 到 `done`；输出 WAV 可解码、有正时长且 `play=false`；运行期无网络下载；依赖约束明确阻止 NumPy 2.x。
- 适用范围：Windows NAS/映射盘上的本地 split-ONNX VITS、pyopenjtalk、onnxruntime 和其他含预编译扩展的 TTS 前端。
