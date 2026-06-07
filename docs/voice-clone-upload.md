# Voice Clone Reference Upload

OumuQ voice enrollment for DashScope / CosyVoice needs a provider-accessible reference audio URL. A local file path such as `<local-reference-audio-path>` is not enough because DashScope cannot fetch files from the user's PC.

This document describes the current private workflow used by FenneNote and OumuQ:

1. FenneNote records or imports a local voice sample.
2. FenneNote writes a pending request under `cache/voice-clone-requests`.
3. OumuQ uploads the local sample to a static HTTP server by SSH/SFTP.
4. OumuQ writes the returned public URL back to the pending request and `voice-references/reference-index.json`.
5. OumuQ calls DashScope voice enrollment.
6. DashScope returns `api_voice_id`; OumuQ stores it in `voice-references/reference-index.json`.

## Private Upload Profile

Upload settings are local-only and must not be committed. The profile file is:

```text
cache/reference-upload-profiles.json
```

Example shape:

```json
{
  "profiles": {
    "default": {
      "server_ip": "<upload-host>",
      "username": "<upload-username>",
      "key_path": "<ssh-key-path>",
      "remote_site_path": "<remote-static-site-path>",
      "public_base_url": "<public-base-url>",
      "remote_subdir": "<remote-reference-audio-subdir>"
    }
  }
}
```

The profile can point at any private Windows Server + OpenSSH + static HTTP site, uploading files with `sftp`.

## OumuQ API

Upload the pending reference audio:

```http
POST /api/voice-clone/upload-reference
Content-Type: application/json

{
  "character_id": "<character_id>",
  "profile": "default"
}
```

Response:

```json
{
  "ok": true,
  "character_id": "<character_id>",
  "reference_audio_url": "<public-base-url>/<remote-reference-audio-subdir>/<character_id>/<sample-file>.wav",
  "request_path": ".../cache/voice-clone-requests/<character_id>-....json",
  "registry": ".../voice-references/reference-index.json"
}
```

Then enroll with DashScope:

```http
POST /api/voice-clone/enroll
Content-Type: application/json

{
  "character_id": "<character_id>"
}
```

Dry-run enrollment payload:

```json
{
  "character_id": "<character_id>",
  "dry_run": true
}
```

## DashScope Notes

For `voice-enrollment`, OumuQ sends:

```json
{
  "model": "voice-enrollment",
  "input": {
    "action": "create_voice",
    "target_model": "cosyvoice-v3-plus",
    "prefix": "<voice-prefix>",
    "url": "<public-or-signed-reference-audio-url>",
    "language_hints": ["zh"],
    "max_prompt_audio_length": 20,
    "enable_preprocess": true
  }
}
```

For CosyVoice clone samples, keep the recording in the `15-20` second range. OumuQ caps `max_prompt_audio_length` at `20` so DashScope preprocessing follows the same rule as the FenneNote UI.

## FenneNote UI Flow

Recommended user flow:

1. Choose `千问 / DashScope CosyVoice`.
2. Record a clean 15-20 second sample.
3. Click `写入 OumuQ 角色`.
4. Upload the sample through OumuQ.
5. Click `执行千问克隆`.
6. Refresh OumuQ roles and use the returned `voice_id`.

The missing GUI piece is a direct FenneNote button:

```text
上传样本并填入 URL
```

It should call `POST /api/voice-clone/upload-reference`, then fill `参考音频 URL` with the returned `reference_audio_url`.

## Security Boundary

Do not commit:

- real `api_voice_id`
- real `api_clone_audio_url`
- SSH keys
- server-only upload profiles
- private voice samples
- generated cloned voice assets

The `cache/` directory is ignored by git for local upload profiles and pending runtime requests.
