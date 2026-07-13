# 证据化角色模型

`character-profile.json` 必须包含：

```json
{
  "schema_version": 1,
  "character_id": "example",
  "display_name_zh": "角色名",
  "identity_facts": [],
  "persona_traits": [],
  "speech_patterns": [],
  "address_terms": [],
  "emotional_modes": [],
  "preferences": [],
  "boundaries": []
}
```

每条事实或推断使用：

```json
{
  "trait": "积极可靠",
  "description": "主动提供帮助并承担任务。",
  "evidence_ids": ["voice_line_001", "voice_line_014"],
  "confidence": "high"
}
```

字段名可按章节使用 `claim`、`trait`、`pattern`、`term`、`mode` 或 `rule`，但必须有 `evidence_ids` 与 `confidence`。

置信度：

- `high`：多个独立证据或一条明确自述。
- `medium`：单条可信证据，或多条间接一致证据。
- `low`：弱推断，仅用于提醒后续补证。
- `unverified`：工作流/安全边界或尚未证实的信息；允许无证据 ID。
