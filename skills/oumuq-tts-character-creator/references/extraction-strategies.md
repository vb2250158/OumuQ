# 角色资料提取策略

## 降级顺序

对每个来源依次尝试，成功后仍检查是否缺少关键区域：

1. 直接读取用户给出的正文或本地文件。
2. 站点公开 API：MediaWiki `api.php?action=parse/query`、站点 JSON、页面嵌入数据。
3. 直接 HTML：正文、JSON-LD、`data-*`、脚本内初始化状态、媒体 URL。
4. 浏览器渲染：使用已有 Chrome 会话加载页面，读取最终 DOM；必要时保存完整 HTML。
5. 浏览器网络记录：寻找 XHR/fetch、JSON、音频清单和分页接口。
6. 搜索站内相关页、角色档案、语音页、剧情页；记录每个来源，不混淆官方与社区推断。
7. 用户提供截图时做 OCR；用户提供音视频时提取转写与元数据。

不要以一次 HTTP 403、空正文或动态占位 DOM 结束任务。只有降级链均失败，才报告具体缺失证据。

## BWIKI / czn

- 优先调用 MediaWiki parse API，角色语音通常位于渲染 HTML 的 `.voice-player-root` 元素中。
- 读取 `data-entries` JSON；常见字段为 `type/key`、`id`、`cn/ja/ko`、`urlCn/urlJa/urlKo`。
- 若 API 被 EdgeOne 拦截，在浏览器打开原页并保存最终 HTML，再传给 `extract_bwiki_voice.py --html-file`。
- 页面有语音区域而条目为零时视为提取失败，不能创建空索引后结束。

## 库街区 / Kurobbs

- `wiki.kurobbs.com/mc/item/<id>` 是 SPA；HTTP 200、正确标题或几十字兼容提示都不代表正文提取成功。
- 优先调用官方条目接口：`POST https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail`，请求头 `wiki_type: 9`，表单字段 `id=<id>`。
- 只白名单提取“基础资料、角色档案、角色语音”的文字字段；明确丢弃 `playUrl`、图片 URL、头像、创建者和其他媒体元数据。
- 若官方接口失败，再进入浏览器最终 DOM/XHR 回退。直接 HTML 只有“浏览器版本过低”、需要 JavaScript 等提示，或正文极短时，必须判定为不足而不是 `success`。

## 证据与推断

- 客观事实优先来自角色档案或明确自述。
- 人格特征至少引用一条台词；稳定人格优先引用两条以上不同场景。
- 单条战斗喊话只能说明该场景的表达，不能单独证明长期人格。
- “未证实”内容放入 `confidence: unverified`，不要伪造 `evidence_ids`。
- README 是可执行提示词；`character-profile.json` 是结构化结论；`character-evidence.json` 是原始证据映射。

## 音频

- 下载只用于用户工作区的本机私有参考库；保留来源 URL、哈希和条目 ID。
- 不把页面上的声优名或可播放按钮自动等同于训练、再分发或公开克隆授权。
- 优先选择 6 至 20 秒、单人、干净、语义自然的片段作为回退参考；短片段可由 worker 在缓存中组合，不改写参考库原件。
