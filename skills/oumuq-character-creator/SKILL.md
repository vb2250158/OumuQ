---
name: oumuq-character-creator
description: Create or update OumuQ character entries in voice-references, including character folders, README.md, voice-index.json, reference-index.json records, local/private voice fields, cloud clone placeholders, worker routing, language settings, and public-safe visual_profile metadata. Use when the user asks to create/add/register/scaffold a new OumuQ role, character, voice character, persona, voice-reference entry, or dialogue-mode character.
---

# OumuQ Character Creator

Use this skill to create or update a character in an OumuQ workspace.

The goal is to produce a usable `voice-references` character entry without leaking private voice data into the public repository.

## Inputs

Collect or infer:

- `character_id`: stable lowercase id such as `cloud_zh_voice` or `jp_companion`.
- Display names: `name`, `display_name`, and/or `display_name_zh`.
- `tts_engine`: usually `Qwen-TTS-API`, `Qwen3-TTS`, or `IndexTTS2`.
- `speech_language`: language spoken by TTS.
- `visible_language`: language shown to the user.
- Character style: concise personality, tone, address terms, and dialogue boundaries.
- Worker URL: use the OumuQ conventions unless the user provides another local URL.
- Voice source state: local reference audio, existing cloud `api_voice_id`, pending clone URL, or placeholder only.
- Public/private target: whether the edit is for the public repo example or the user's local private `voice-references`.

If the user gives only a character concept, choose conservative defaults and create placeholders. Do not ask for secrets.

## File Targets

Use the local workspace paths:

```text
voice-references/reference-index.json
voice-references/characters/<character_id>/README.md
voice-references/characters/<character_id>/voice-index.json
voice-references/characters/<character_id>/audio/.gitkeep
```

If `voice-references` does not exist but `voice-references.example` does, ask whether the user wants a private local copy. For public templates, edit `voice-references.example`.

Keep generated audio, cache files, worker logs, and clone samples out of `voice-references` unless the user explicitly provides authorized reference audio for a private local copy.

## Workflow

1. Inspect existing `voice-references/reference-index.json` or `voice-references.example/reference-index.json`.
2. Ensure `character_id` is unique. If an entry exists, update it instead of duplicating it.
3. Create the character folder and `audio/.gitkeep`.
4. Write `README.md` as the primary style guide for dialogue mode.
5. Write `voice-index.json` with public metadata or local authorized reference metadata.
6. Update `reference-index.json` by parsing JSON, editing the `characters` array, and preserving valid JSON.
7. Run a JSON parser check on all edited JSON files.
8. If OumuQ is running, verify `GET /api/characters` can see the character after restart or refresh when applicable.
9. Install updated skills only if the skill itself changed; creating a character does not require reinstalling skills.

Use structured JSON parsing instead of regex edits for `reference-index.json`.

## Reference Entry Shape

Base character entry:

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
  "style_summary_zh": "温和、清晰、自然对话感。"
}
```

Recommended worker URLs:

- `Qwen3-TTS`: `http://127.0.0.1:8765`
- `IndexTTS2`: `http://127.0.0.1:8766`
- `Qwen-TTS-API`: `http://127.0.0.1:8767`
- OumuQ route layer: `http://127.0.0.1:8780`

## Cloud API Characters

For `tts_engine = "Qwen-TTS-API"`, add public-safe cloud fields:

```json
{
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "api_clone_target_model": "cosyvoice-v3-plus",
  "api_clone_language_hint": "zh",
  "api_voice_instructions": "Use a natural conversational delivery. Keep the tone warm and clear.",
  "send_instructions_by_default": false
}
```

In a private local copy, real `api_voice_id` and clone URLs may be stored if the user has chosen to keep them there. In a public repo, keep placeholders.

For CosyVoice clone samples, prefer 15-20 seconds and a provider-accessible URL. A local path such as `<local-reference-audio-path>` is not enough for cloud enrollment.

## Local Reference Audio Characters

For `IndexTTS2` or `Qwen3-TTS`, use local authorized reference audio:

```json
[
  {
    "id": "warm_001",
    "audio_file": "voice-references/characters/my_character/audio/warm_001.wav",
    "text": "Reference transcript.",
    "language": "Chinese",
    "mood": "warm",
    "emotion_tags": ["warm", "clear"],
    "emotion_vector": [0.35, 0, 0, 0, 0, 0, 0.02, 0.3],
    "match_patterns": ["hello|thanks|warm"],
    "style_notes": "Authorized local reference audio."
  }
]
```

If no audio is available yet, create `voice-index.json` as an empty array or with metadata-only examples that omit `audio_file`. Do not invent file paths to audio that does not exist unless the entry is clearly a placeholder.

## Character README

Keep `README.md` concise and useful for dialogue mode:

- Character purpose and public/private note.
- Speaking style and emotional range.
- Address terms and recurring phrasing, if safe.
- `speech_language` and `visible_language`.
- TTS engine and worker expectation.
- Voice/reference status.
- Safety boundaries: what not to imitate, reveal, or publish.

Do not include real speaker identity, private character names, copyrighted character provenance, API keys, cookies, tokens, private server URLs, or unapproved reference links.

## Visual Profile

If the user wants drawing mode too, add only public-safe visual fields:

```json
{
  "visual_profile": {
    "id": "generic_companion_visual",
    "prompt_profile": "A public, original companion character design.",
    "safety_note": "Do not reference private characters, private names, copyrighted characters, real voice owners, or private reference images."
  }
}
```

Do not turn voice provenance into visual identity.

## Public Safety

Public OumuQ examples may contain:

- Generic character ids.
- Placeholder cloud fields.
- Public-safe style summaries.
- Metadata-only voice-index examples.
- `.gitkeep` in `audio/`.

Public OumuQ examples must not contain:

- Real `api_voice_id`, API keys, cookies, or tokens.
- Real clone URLs or signed object-storage links.
- Personal machine paths.
- Private character names or private address terms.
- Unlicensed third-party audio, generated output audio, worker caches, or logs.
- Private visual references or prompts that reveal protected identity.

## Validation

After editing:

```powershell
Get-Content -Raw -Encoding utf8 voice-references\reference-index.json | ConvertFrom-Json | Out-Null
Get-Content -Raw -Encoding utf8 voice-references\characters\<character_id>\voice-index.json | ConvertFrom-Json | Out-Null
```

For public examples, run the same checks against `voice-references.example`.

If tests exist, run the focused OumuQ checks that cover character loading or route configuration.
