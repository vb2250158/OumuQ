---
name: qwen-voice-language-training
description: Use when planning Qwen/DashScope cloned voice enrollment, language hints, or cross-language speech such as Japanese reference audio speaking Chinese, especially when the user has not yet clarified the desired speech language and accent tradeoff.
---

# Qwen Voice Language Training

Use this skill before enrolling or using a Qwen/DashScope cloned voice when reference-audio language, visible reply language, and desired spoken language may differ.

## First Decision

Separate these three values:

- `reference_audio_language`: the language actually spoken in the clone reference audio.
- `speech_language`: the language the TTS output should speak.
- `visible_language`: the language shown to the user as text/subtitles.

If the user has not clearly chosen `speech_language`, ask before cloning or synthesis when the target differs from the reference audio. Keep the question short:

```text
参考音频是日语。你希望生成语音也说日语，还是保留音色但改说中文？后者可能更容易有跨语种口音。
```

If asking is impractical and no target was confirmed, default to the reference-audio language. For Japanese reference audio, use Japanese speech and Chinese visible text/subtitles if needed.

## Qwen API Language Hints

For Qwen/DashScope cloned voices, pass language hints in both phases:

1. Voice enrollment / clone registration: set the reference audio language, for example `language_hints: ["ja"]`.
2. Speech synthesis: set the current text language on every request, for example `language_hints: ["ja"]` for Japanese speech or `language_hints: ["zh"]` for Chinese speech.

Do not assume that `speech_language: "Japanese"` in local metadata is enough. The worker should map it to the provider language hint (`ja`, `zh`, `en`) before calling the provider.

## Same-Language Clone

Use this when the user wants the character to speak in the same language as the reference audio.

Recommended setup:

```json
{
  "tts_engine": "Qwen-TTS-API",
  "speech_language": "Japanese",
  "visible_language": "Chinese",
  "api_clone_language_hint": "ja",
  "api_clone_target_model": "cosyvoice-v3-plus"
}
```

Runtime rule:

- Send Japanese speech text to `/speak`.
- Send or derive `language_hints: ["ja"]` during synthesis.
- Show Chinese text separately if the user wants Chinese-visible dialogue.

This is the safest default for Japanese-only reference audio.

## Cross-Language Clone

Use this when the reference audio is in one language but the user wants another spoken language, such as Japanese reference audio speaking Chinese.

Before proceeding, explain the tradeoff plainly:

- It may preserve some timbre and character feel.
- It may introduce cross-language accent or unstable pronunciation.
- Better results usually require clean reference audio in the target language from the same speaker/voice, or a model/provider that is proven strong at cross-lingual cloning.

Recommended options:

- Best: use target-language reference audio from the same authorized voice and enroll with that target language hint.
- Acceptable experiment: enroll with the reference language hint, synthesize with the target speech language hint, then listen for accent and pronunciation.
- Conservative fallback: keep speech in the reference language and use visible subtitles/translation for the user.

For Japanese reference audio speaking Chinese, do not silently switch to Chinese speech. Ask first unless the user already requested it.

## Worker Contract Guidance

The worker should store enough metadata to debug language issues:

```json
{
  "reference_audio_language": "Japanese",
  "speech_language": "Japanese",
  "visible_language": "Chinese",
  "api_clone_language_hint": "ja",
  "synthesis_language_hint": "ja"
}
```

For each generated job, persist the resolved synthesis hint in `job.json` and chunk metadata. This makes it obvious whether a bad accent came from clone enrollment, synthesis language routing, or the source material itself.

## Public Safety

Public OumuQ skills and docs may describe language strategy and placeholder fields, but must not publish:

- real voice IDs
- real clone audio URLs
- private character names
- third-party source pages
- downloaded reference audio
- personal server IPs, bucket names, or signed URLs
