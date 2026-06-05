---
name: qwen-api-tts-worker
description: Use when running or documenting an OumuQ-compatible Qwen/DashScope cloud TTS API worker with optional cloned voices and public-safe placeholder configuration.
---

# Qwen API TTS Worker

Use this public template for cloud TTS workers that expose the OumuQ worker contract:

```text
GET  /health
GET  /status
GET  /status/<job_id>
POST /speak
```

## Required Runtime Pattern

Run one long-lived worker for the active character, then submit local HTTP requests:

```text
Agent -> http://127.0.0.1:8767/speak -> worker -> cloud TTS provider
```

`POST /speak` should return quickly with a queued job object. Generation and playback continue in the worker.

## Configuration

Use environment variables for secrets:

```powershell
$env:DASHSCOPE_API_KEY = "..."
```

Use local character metadata for non-secret routing:

```json
{
  "id": "cloud_zh_voice",
  "tts_engine": "Qwen-TTS-API",
  "api_voice_id": "<set-in-local-copy>",
  "api_clone_audio_url": "<public-or-signed-reference-audio-url>",
  "api_clone_target_model": "cosyvoice-v3-plus",
  "send_instructions_by_default": false
}
```

## Voice Cloning

Cloud voice enrollment usually needs a provider-accessible reference-audio URL. Local files under `voice-references` are not enough unless they are uploaded to a public or signed URL.

When enrolling a cloned voice, pass the reference audio language hint when the provider supports it, for example `language_hints: ["ja"]` for Japanese or `language_hints: ["zh"]` for Chinese. During synthesis, also pass the current speech language hint on every request. A clone registered with Japanese reference audio can still sound wrong if synthesis later omits `ja` and the provider guesses the language.

Do not publish:

- real API keys
- real `voice_id`
- real clone URLs
- server IPs or bucket names
- personal reference audio

## Instructions

Some cloned voices may fail or become unstable when provider-side `instructions` are sent. Keep `send_instructions_by_default` false until the specific provider, model, and voice have been tested. Agent text should still follow the character style before submission.
