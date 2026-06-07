# TTS Model Capabilities

OumuQ is the normalization layer between AI clients and concrete TTS workers. AI clients should send rich intent fields when available; OumuQ keeps a canonical request shape and each worker adapts that shape to the current model.

The machine-readable capability file is:

```text
app/tts_model_capabilities.json
```

It is exposed at:

```http
GET /api/tts-model-capabilities
```

`GET /api/config` also returns the capability endpoint and capability version.

## Canonical Request Shape

AI clients should prefer this shape and send as much useful intent as they know:

```json
{
  "text": "你好，今天辛苦了。",
  "character_id": "<character_id>",
  "model": "cosyvoice-v3-plus",
  "language": "Chinese",
  "play": true,
  "emotion_mode": "vector",
  "emotion_alpha": 0.55,
  "emotion_tags": ["warm", "happy"],
  "emotion_vector": [0.6, 0.0, 0.0, 0.0, 0.0, 0.1, 0.1, 0.4],
  "emotion_text": "温和、轻快、带一点笑意",
  "instructions": "语气温和轻快，带一点笑意，像自然聊天，不要夸张。",
  "send_instructions": true,
  "speech_rate": 1.05,
  "pitch_rate": 1.02,
  "volume": 55
}
```

OumuQ should not require every client to know every provider's exact parameter names. The client sends intent; OumuQ and the selected worker decide how to use it.

## Normalization Policy

- `character_id` resolves local registry defaults such as `api_voice_id`, `worker_url`, `speech_language`, and `api_voice_instructions`.
- `language` is normalized into model-specific language hints when the worker supports them.
- `emotion_vector`, `emotion_tags`, and `emotion_text` are canonical intent fields. They are not guaranteed to map to a native provider field.
- `instructions`, `speech_rate`, `pitch_rate`, and `volume` are provider-facing controls when the selected model supports them.
- Unsupported fields should be ignored or degraded, not treated as fatal, unless the field is required for the selected workflow.

## DashScope CosyVoice

For `cosyvoice-v3-plus`, current official API behavior is:

- Supports cloned `voice_id`.
- Supports `language_hints`.
- Supports `instruction` in supported CosyVoice synthesis flows.
- Supports provider prosody controls such as `volume`, `speech_rate`, and `pitch_rate` where exposed by the worker/API.
- Does not expose a native `emotion_vector` field in the current CosyVoice API docs.

Therefore OumuQ should map high-level emotion intent into:

```json
{
  "instructions": "语气明亮轻快，带一点笑意，语速自然，不要夸张。",
  "speech_rate": 1.05,
  "pitch_rate": 1.02,
  "volume": 55,
  "send_instructions": true
}
```

Example degradation:

| Intent | Instruction | Prosody |
| --- | --- | --- |
| happy | 语气明亮轻快，带一点笑意 | speech_rate +, pitch_rate + |
| calm | 语气平稳自然，轻柔克制 | speech_rate neutral/slower |
| sad | 语气低落，声音轻一些，语速稍慢 | speech_rate -, pitch_rate - |
| surprised | 带惊讶感，句尾略上扬 | pitch_rate + |

## Voice Clone vs Emotion

Voice clone reference audio answers: **who is speaking**.

Emotion controls answer: **how this sentence is spoken**.

Do not use a new emotion reference audio as if it were a new voice enrollment sample unless the selected model explicitly supports that workflow. For CosyVoice cloud clone, enroll the voice once, store `api_voice_id`, then control delivery per request.

## Worker Responsibilities

Workers should:

- Accept the canonical OumuQ payload.
- Use all fields supported by the active model.
- Ignore unknown harmless fields.
- Return diagnostics in job metadata when a field is degraded or ignored.
- Keep provider-specific secrets and private URLs out of public examples.

## Current Capability Sources

- OumuQ local capability file: `app/tts_model_capabilities.json`
- DashScope / CosyVoice docs:
  - https://www.alibabacloud.com/help/en/model-studio/text-to-speech
  - https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide
  - https://www.alibabacloud.com/help/en/model-studio/cosyvoice-clone-design-api
