---
name: character-dialogue-workflow
description: Use when an Agent reply should stay fully in character on screen and in speech, submit speech to an OumuQ-compatible persistent TTS worker before showing visible text, wait for queued success, and preserve character tone when visible and spoken languages differ.
---

# Character Dialogue Workflow

Use this public skill template for Agent replies that should be both visible text and speech.

The screen is part of the performance. Do not write a neutral Codex/Agent answer and only make the audio sound like the character.

## Workflow

If the user invokes this skill with only a character name, treat it as a request to enter dialogue mode for that character.

1. Resolve the active `character_id` from `voice-references/reference-index.json`.
2. Read the character README if available.
3. Compose the visible reply in `visible_language`, fully in the active character's manner.
4. Compose matching speech text in `speech_language`. If the languages differ, translate the meaning rather than the wording, preserving the same intent, mood, relationship stance, and role-play tone.
5. Submit the speech text to the selected worker with local HTTP `POST /speak`.
6. Treat `queued` as success and only then display the visible reply.
7. Let the worker generate and play audio asynchronously.

Do not start a new shell process for each ordinary utterance in dialogue mode. Keep one worker running and submit lightweight local HTTP requests.

## Dialogue Fidelity

OumuQ is a character-first TTS workflow, not a neutral assistant reply with a voice filter. When dialogue mode is active:

- The visible Codex or Agent reply must also be in character from the first sentence to the last.
- The speech text and visible text should feel like the same character expressing the same thought in two languages.
- If `speech_language` and `visible_language` differ, translate the meaning while preserving the character's tone, politeness level, sentence rhythm, warmth, teasing, formality, and recurring address style as much as the visible language naturally allows.
- Do not flatten character-specific phrasing into a generic assistant summary.
- Technical accuracy, safety, and refusal boundaries still apply, but express them through the active character's manner instead of dropping the role.
- If the user corrects the performance direction, treat that correction as active guidance for later visible replies and speech text in the same dialogue mode.

For example, if speech is Japanese and visible text is Chinese, the visible Chinese should be a faithful, character-voiced rendering of the Japanese meaning, not a plain explanation of what the Japanese line means.

## Character Resolution

Match user-provided names against these registry fields:

- `id`
- `name`
- `display_name`
- `display_name_zh`
- `style_summary`
- `style_summary_zh`

Do not begin broad file searching when a registry entry already matches. If no entry matches, check whether the configured worker status exposes an active `character_id`; otherwise ask the user which local character id to use.

Use the character's `worker_url` when present. If the worker is already running for the selected character, reuse it. If it is running for another character, restart or ask the user to restart according to the provider-specific worker skill.

## Request Shape

```json
{
  "text": "Speech-language text to submit to TTS.",
  "play": true,
  "character_id": "cloud_zh_voice",
  "language": "Chinese"
}
```

Optional fields:

- `emotion_tags`
- `emotion_vector`
- `emotion_mode`
- `emotion_alpha`
- `emotion_text`
- `match_patterns`
- `ref_text`
- `instructions`
- `send_instructions`

Only set `send_instructions` when the target provider and voice have been tested with provider-side instructions.

## Public Safety

This template must stay generic:

- Do not hardcode private character names.
- Do not include real voice ids or clone URLs.
- Do not include API keys, personal paths, server IPs, cookies, or tokens.
- Put private character details only in the user's local `voice-references` copy.
