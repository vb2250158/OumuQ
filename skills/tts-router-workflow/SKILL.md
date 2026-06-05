---
name: tts-router-workflow
description: Use when an Agent needs to choose an OumuQ-compatible TTS worker, language, character, reference audio, cloud voice metadata, or playback behavior from voice-references.
---

# TTS Router Workflow

Use `voice-references/reference-index.json` as the single routing source.

## Route Selection

1. Find the requested character by `id`, `name`, or display fields.
2. Use `speech_language` for audio and `visible_language` for screen text.
3. Use `tts_engine` to choose the worker URL.
4. Prefer passing `character_id` to the worker rather than embedding resolved provider details in every request.
5. Keep generated audio, prompt composites, caches, and logs outside `voice-references`.

When used with `character-dialogue-workflow`, route two texts: the speech-language text sent to TTS and the visible-language text shown after `queued`. Both texts must keep the same character voice and intent.

Suggested engine keys:

- `Qwen3-TTS`: local multilingual worker.
- `IndexTTS2`: local Chinese/cloning worker.
- `Qwen-TTS-API`: cloud API worker, usually on `OUMUQ_QWEN_TTS_API_WORKER_URL`.

## Cloud Voice Fields

Cloud API characters may include:

- `api_voice_id`
- `api_clone_audio_url`
- `api_clone_target_model`
- `api_clone_language_hint`
- `api_voice_instructions`
- `send_instructions_by_default`

In the public repository these values should be placeholders. Real values belong in a local copy, deployment secret store, or private config.

## Drawing Mode

If an image-generation workflow uses the same character, read only public-safe visual fields such as:

- `visual_profile.id`
- `visual_profile.prompt_profile`
- `visual_profile.safety_note`

Do not convert voice provenance into visual identity. Voice source, real speaker identity, private reference files, and cloud URLs are not image prompt material.
