#!/usr/bin/env python
import argparse
import base64
import hashlib
import json
import mimetypes
import os
import queue
import re
import threading
import time
import traceback
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"
TTS_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
VOICE_ENROLLMENT_PATH = "/api/v1/services/audio/tts/customization"
URL_PATTERN = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)
DATA_URL_PATTERN = re.compile(r"data:[^\s\"']+", re.IGNORECASE)


def parse_args():
    parser = argparse.ArgumentParser(description="HTTP worker for Qwen Cloud / DashScope TTS API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--cache-dir", default=".qwen-tts-api-cache")
    parser.add_argument("--output-dir", default="qwen-tts-api-output")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key-env", default="DASHSCOPE_API_KEY,QWEN_API_KEY")
    parser.add_argument("--character-id", default=None)
    parser.add_argument("--model", default="qwen3-tts-flash")
    parser.add_argument("--voice", default="Cherry")
    parser.add_argument("--voice-id", default=None)
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--instructions", default=None)
    parser.add_argument("--send-instructions", action="store_true")
    parser.add_argument("--optimize-instructions", action="store_true")
    parser.add_argument("--clone-audio-url", default=None)
    parser.add_argument("--clone-audio-path", default=None)
    parser.add_argument("--clone-prefix", default="voice")
    parser.add_argument("--clone-target-model", default="cosyvoice-v3-plus")
    parser.add_argument("--clone-enrollment-model", default=None)
    parser.add_argument("--clone-language-hint", default="zh")
    parser.add_argument("--clone-reference-text", default=None)
    parser.add_argument("--voice-prompt", default=None)
    parser.add_argument("--preview-text", default=None)
    parser.add_argument("--max-prompt-audio-length", type=int, default=15)
    parser.add_argument("--enable-preprocess", action="store_true")
    parser.add_argument("--no-play", action="store_true")
    parser.add_argument("--app-name", default="OumuQ Qwen TTS Worker")
    return parser.parse_args()


def register_windows_app_identity(app_name):
    if os.name != "nt":
        return
    try:
        import ctypes

        app_id = re.sub(r"[^A-Za-z0-9.]+", ".", str(app_name).strip()).strip(".") or "OumuQ.QwenTTSWorker"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(str(app_name))
    except Exception:
        pass


def load_character_api_config(workdir, character_id):
    if not character_id:
        return {}
    registry_path = Path(workdir) / "voice-references" / "reference-index.json"
    if not registry_path.exists():
        raise FileNotFoundError(f"Voice reference registry not found: {registry_path}")
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    for character in registry.get("characters", []):
        if str(character.get("id", "")).lower() == str(character_id).lower():
            return character
    raise ValueError(f"Character id not found in registry: {character_id}")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def split_sentences(text, max_chunk_chars=500):
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = re.findall(r".+?[.!?\u3002\uff01\uff1f\uff1b;]+[\"')\]\u300d\u300f]*|.+$", text)
    chunks = []
    current = ""
    for sentence in (part.strip() for part in parts if part.strip()):
        candidate = f"{current}{sentence}" if current else sentence
        if current and len(candidate) > max_chunk_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def language_hint_for(language, fallback=None):
    value = str(language or "").strip().lower()
    if value.startswith(("japanese", "ja", "jp")):
        return "ja"
    if value.startswith(("chinese", "zh", "cn")):
        return "zh"
    if value.startswith(("english", "en")):
        return "en"
    return fallback


def cache_key(sentence, settings):
    encoded = json.dumps({"sentence": sentence, "settings": settings}, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def safe_qwen_voice_name(value, fallback="voice"):
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(value).strip()).strip("_")[:16]
    return cleaned or fallback


def safe_cosyvoice_prefix(value, fallback="voice"):
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(value).strip())[:10]
    return cleaned or fallback


def is_qwen_instruct_model(model):
    return str(model or "").strip().lower().startswith("qwen3-tts-instruct-")


def redact_sensitive_text(value, voice_values=()):
    text = str(value or "")
    for voice in voice_values:
        secret = str(voice or "").strip()
        if secret:
            text = text.replace(secret, "<redacted-voice>")
    text = DATA_URL_PATTERN.sub("<redacted-data-url>", text)
    return URL_PATTERN.sub("<redacted-url>", text)


def public_job(job):
    result = dict(job)
    voice = result.pop("voice", None)
    result["voice_configured"] = bool(voice)
    if result.get("error"):
        result["error"] = redact_sensitive_text(result["error"], (voice,))
    return result


def public_settings(settings):
    result = dict(settings)
    voice = result.pop("voice", None)
    voice_id = result.pop("voice_id", None)
    result["voice_configured"] = bool(voice or voice_id)
    return result


def persisted_provider_response(response, voice_values=()):
    secrets = {str(value).strip() for value in voice_values if str(value or "").strip()}

    def collect_voice_values(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"voice", "voice_id"} and isinstance(child, (str, int, float)):
                    secret = str(child).strip()
                    if secret:
                        secrets.add(secret)
                collect_voice_values(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect_voice_values(child)

    def redact_text(value):
        text = str(value)
        for secret in secrets:
            text = text.replace(secret, "<redacted>")
        text = DATA_URL_PATTERN.sub("<redacted>", text)
        return URL_PATTERN.sub("<redacted>", text)

    def is_locator(value):
        return isinstance(value, str) and value.lstrip().lower().startswith(
            ("data:", "http://", "https://")
        )

    def sanitize(value, inside_audio=False):
        if isinstance(value, dict):
            result = {}
            voice_configured = False
            audio_available = False
            for key, child in value.items():
                normalized_key = str(key).lower()
                if normalized_key in {"voice", "voice_id"}:
                    voice_configured = voice_configured or bool(child)
                    continue
                child_is_audio_container = (
                    normalized_key in {"audio", "preview_audio"}
                    or normalized_key.endswith("_audio")
                )
                child_inside_audio = inside_audio or child_is_audio_container
                if (
                    normalized_key in {"data", "url"}
                    and (child_inside_audio or is_locator(child))
                ) or (normalized_key.endswith("_url") and is_locator(child)):
                    audio_available = audio_available or child_inside_audio
                    continue
                if child_is_audio_container and isinstance(child, str):
                    result[key] = "<redacted>"
                    audio_available = audio_available or bool(child)
                    continue
                result[key] = sanitize(child, child_inside_audio)
            if voice_configured:
                result["voice_configured"] = True
            if audio_available:
                result["audio_available"] = True
            return result
        if isinstance(value, (list, tuple)):
            return [sanitize(child, inside_audio) for child in value]
        if isinstance(value, str):
            return redact_text(value)
        return value

    collect_voice_values(response)
    return sanitize(response)


def provider_error_summary(payload, http_status=None):
    parsed = payload if isinstance(payload, dict) else {}
    provider_code = parsed.get("code")
    request_id = parsed.get("request_id") or parsed.get("requestId")
    output = parsed.get("output")
    output_keys = sorted(output) if isinstance(output, dict) else []
    fields = []
    if http_status is not None:
        fields.append(f"http_status={int(http_status)}")
    if provider_code:
        safe_code = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(provider_code))[:80]
        fields.append(f"provider_code={safe_code}")
    if request_id:
        safe_request_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(request_id))[:120]
        fields.append(f"request_id={safe_request_id}")
    if output_keys:
        fields.append(f"output_keys={output_keys}")
    return ", ".join(fields) or "no safe provider details"


def audio_data_for_source(workdir, source):
    value = str(source or "").strip()
    if value.startswith(("http://", "https://", "data:")):
        return value, "url" if not value.startswith("data:") else "data-url", hashlib.sha256(value.encode("utf-8")).hexdigest()
    path = Path(value)
    if not path.is_absolute():
        path = Path(workdir) / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Clone reference audio not found: {path}")
    mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    raw = path.read_bytes()
    return f"data:{mime_type};base64,{base64.b64encode(raw).decode('ascii')}", "local-file", hashlib.sha256(raw).hexdigest()


def wav_duration(path):
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def normalize_wav_header(path):
    path = Path(path)
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with wave.open(str(tmp_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(raw)
    tmp_path.replace(path)


def fix_wav_sizes(path):
    path = Path(path)
    data = bytearray(path.read_bytes())
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return
    data_index = data.find(b"data")
    if data_index < 0 or data_index + 8 > len(data):
        return
    data[4:8] = (len(data) - 8).to_bytes(4, "little")
    data[data_index + 4:data_index + 8] = (len(data) - (data_index + 8)).to_bytes(4, "little")
    path.write_bytes(data)


class CosyVoiceFileWriter:
    def __init__(self, output_path):
        from dashscope.audio.tts_v2 import ResultCallback

        class Writer(ResultCallback):
            def __init__(self, path):
                self.output_path = Path(path)
                self.output_path.parent.mkdir(parents=True, exist_ok=True)
                self.file = open(self.output_path, "wb")
                self.error = None
                self.completed = False

            def on_data(self, data: bytes):
                self.file.write(data)

            def on_error(self, message):
                self.error = message

            def on_complete(self):
                self.completed = True

            def on_close(self):
                if not self.file.closed:
                    self.file.close()

        self.inner = Writer(output_path)


def concatenate_wavs(paths, out_path):
    frames = []
    params = None
    for path in paths:
        with wave.open(str(path), "rb") as wf:
            current = wf.getparams()
            if params is None:
                params = current
            elif current[:3] != params[:3]:
                raise RuntimeError(f"Cannot concatenate WAV files with different formats: {path}")
            frames.append(wf.readframes(wf.getnframes()))
    if params is None:
        raise RuntimeError("No audio chunks generated.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setparams(params)
        for frame in frames:
            wf.writeframes(frame)


def get_api_key(env_names):
    for name in [item.strip() for item in env_names.split(",") if item.strip()]:
        value = os.environ.get(name)
        if value:
            return value
        value = get_windows_user_env(name)
        if value:
            return value
    raise RuntimeError(f"Missing API key. Set one of: {env_names}")


def get_windows_user_env(name):
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


class QwenTTSApiWorker:
    def __init__(self, args):
        self.args = args
        self.workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd().resolve()
        self.cache_dir = Path(args.cache_dir)
        if not self.cache_dir.is_absolute():
            self.cache_dir = self.workdir / self.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.worker_cache_dir = self.cache_dir / "worker"
        self.worker_cache_dir.mkdir(parents=True, exist_ok=True)
        self.voice_cache_path = self.cache_dir / "voices.json"

        self.output_dir = Path(args.output_dir)
        if not self.output_dir.is_absolute():
            self.output_dir = self.workdir / self.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.api_key = get_api_key(args.api_key_env)
        self.base_url = args.base_url.rstrip("/")
        # --character-id is a legacy/default route only. Every /speak request may select
        # another character and gets a fresh immutable job snapshot.
        self.character_config = load_character_api_config(self.workdir, args.character_id)
        self.default_model = (
            self.character_config.get("api_target_model")
            or self.character_config.get("api_clone_target_model")
            or args.model
        )
        self.default_voice = self.character_config.get("api_voice_id") or args.voice_id or args.voice
        self.default_language = self.character_config.get("speech_language") or args.language
        self.default_language_hint = self.character_config.get("api_clone_language_hint") or args.clone_language_hint
        self.default_instructions = self.character_config.get("api_voice_instructions") or args.instructions
        self.jobs = {}
        self.job_queue = queue.Queue()
        self.play_queue = queue.Queue()
        self.lock = threading.Lock()
        self.enrollment_lock = threading.Lock()
        self.ready = True
        self.started_at = time.time()
        self.voice_id = self.character_config.get("api_voice_id") or args.voice_id

    def start(self):
        register_windows_app_identity(self.args.app_name)
        threading.Thread(target=self._generator_loop, daemon=True).start()
        threading.Thread(target=self._playback_loop, daemon=True).start()

    def submit(
        self,
        text,
        character_id=None,
        session_id=None,
        voice=None,
        voice_id=None,
        language=None,
        language_hint=None,
        instructions=None,
        send_instructions=None,
        optimize_instructions=None,
        volume=None,
        speech_rate=None,
        pitch_rate=None,
        play=True,
        model=None,
    ):
        sentences = split_sentences(text)
        if not sentences:
            raise ValueError("No text to synthesize.")

        requested_character_id = str(character_id or "").strip() or None
        effective_character_id = requested_character_id or self.args.character_id
        character_config = load_character_api_config(self.workdir, effective_character_id)

        configured_model = (
            character_config.get("api_target_model")
            or character_config.get("api_clone_target_model")
        )
        if requested_character_id:
            # An explicit character makes its private registry entry authoritative.
            # Ignore stale or malicious per-request voice/model overrides.
            resolved_model = configured_model or self.args.model
            resolved_voice = character_config.get("api_voice_id")
        else:
            resolved_model = model or configured_model or self.args.model
            resolved_voice = voice_id or voice or character_config.get("api_voice_id")
        if not resolved_voice and requested_character_id:
            raise ValueError(
                f"Character {requested_character_id!r} has no configured api_voice_id. "
                "Register it explicitly through OumuQ before calling /speak; "
                "automatic enrollment is disabled for explicit character requests."
            )
        if not resolved_voice:
            resolved_voice = self._ensure_voice_id(character_config)
        if not resolved_voice:
            resolved_voice = self.voice_id or self.default_voice

        resolved_language = language or character_config.get("speech_language") or self.args.language
        resolved_language_hint = language_hint or language_hint_for(
            resolved_language,
            character_config.get("api_clone_language_hint") or self.args.clone_language_hint,
        )
        if instructions is None:
            resolved_instructions = character_config.get("api_voice_instructions")
            if resolved_instructions is None and not requested_character_id:
                resolved_instructions = self.args.instructions
        else:
            resolved_instructions = instructions
        if send_instructions is None:
            if "send_instructions_by_default" in character_config:
                resolved_send_instructions = bool(character_config.get("send_instructions_by_default"))
            else:
                resolved_send_instructions = bool(self.args.send_instructions and not requested_character_id)
        else:
            resolved_send_instructions = bool(send_instructions)

        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        out_path = self.output_dir / f"{job_id}.wav"
        job_cache_dir = self.worker_cache_dir / job_id
        job_cache_dir.mkdir(parents=True, exist_ok=True)
        job = {
            "id": job_id,
            "text": text,
            "sentences": sentences,
            "status": "queued",
            "created_at": time.time(),
            "updated_at": time.time(),
            "output": str(out_path),
            "cache_dir": str(job_cache_dir),
            "play": bool(play and not self.args.no_play),
            "current": 0,
            "total": len(sentences),
            "chunks": [],
            "error": None,
            "engine": "Qwen-TTS-API",
            "provider": character_config.get("tts_provider") or "Alibaba Cloud Model Studio (DashScope)",
            "enrollment_model": character_config.get("api_enrollment_model"),
            "voice_mode": character_config.get("voice_mode") or (
                "cloud-voice-clone" if character_config.get("api_voice_id") else "provider-preset"
            ),
            "character_id": effective_character_id,
            "session_id": str(session_id or "").strip() or None,
            "model": resolved_model,
            "voice": resolved_voice,
            "language": resolved_language,
            "language_hint": resolved_language_hint,
            "instructions": resolved_instructions,
            "send_instructions": resolved_send_instructions,
            "optimize_instructions": self.args.optimize_instructions if optimize_instructions is None else bool(optimize_instructions),
            "volume": 50 if volume is None else int(volume),
            "speech_rate": 1.0 if speech_rate is None else float(speech_rate),
            "pitch_rate": 1.0 if pitch_rate is None else float(pitch_rate),
        }
        with self.lock:
            self.jobs[job_id] = job
        write_json(job_cache_dir / "job.json", public_job(job))
        self.job_queue.put(job_id)
        return job

    def snapshot(self, job_id=None):
        with self.lock:
            if job_id:
                return public_job(self.jobs[job_id])
            return {
                "ready": self.ready,
                "engine": "Qwen-TTS-API",
                "provider": "Alibaba Cloud Model Studio (DashScope)",
                "character_id": self.args.character_id,
                "default_character_id": self.args.character_id,
                "dynamic_character_routing": True,
                "model": self.default_model,
                "voice_configured": bool(self.voice_id or self.default_voice),
                "playback_host": self.args.app_name,
                "windows_volume_process": self.args.app_name,
                "windows_volume_hint": "This worker is the audio playback process. In Windows Volume Mixer it may appear as OumuQ Qwen TTS Worker, or as Python when launched from python.exe.",
                "playback_enabled": not self.args.no_play,
                "has_default_instructions": bool(self.default_instructions),
                "uptime_seconds": round(time.time() - self.started_at, 2),
                "queued": self.job_queue.qsize(),
                "jobs": [public_job(job) for job in self.jobs.values()],
            }

    def _set_job(self, job_id, **updates):
        with self.lock:
            job = self.jobs[job_id]
            job.update(updates)
            job["updated_at"] = time.time()
            current = dict(job)
        write_json(Path(current["cache_dir"]) / "job.json", public_job(current))
        return current

    def _api_post(self, path, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(
            self.base_url + path,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=120) as resp:
                data = resp.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            try:
                parsed_detail = json.loads(detail)
            except (TypeError, ValueError):
                parsed_detail = {}
            summary = provider_error_summary(parsed_detail, http_status=exc.code)
            raise RuntimeError(f"Qwen TTS API request failed: {summary}") from exc
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise RuntimeError("Qwen TTS API returned an invalid JSON object response.")
        status_code = parsed.get("status_code", 200)
        try:
            failed_status = int(status_code) >= 400
        except (TypeError, ValueError):
            failed_status = True
        if parsed.get("code") or failed_status:
            summary = provider_error_summary(parsed)
            raise RuntimeError(f"Qwen TTS API request failed: {summary}")
        return parsed

    def _ensure_voice_id(self, character_config=None, character_id=None):
        character_config = character_config or {}
        explicit_character = bool(character_id)
        configured_target = character_config.get("api_target_model") or character_config.get("api_clone_target_model")
        target_model = configured_target or self.args.clone_target_model
        enrollment_model = (
            character_config.get("api_enrollment_model")
            or getattr(self.args, "clone_enrollment_model", None)
        )
        if not enrollment_model:
            if str(target_model).startswith("qwen3-tts-vd-"):
                enrollment_model = "qwen-voice-design"
            elif str(target_model).startswith("qwen3-tts-vc-"):
                enrollment_model = "qwen-voice-enrollment"
            else:
                enrollment_model = "voice-enrollment"

        language_hint = (
            character_config.get("api_clone_reference_language")
            or character_config.get("api_voice_design_language")
            or character_config.get("api_clone_language_hint")
            or self.args.clone_language_hint
        )

        if enrollment_model == "qwen-voice-design":
            target_model = configured_target or "qwen3-tts-vd-2026-01-26"
            voice_prompt = character_config.get("api_voice_prompt") or (
                getattr(self.args, "voice_prompt", None) if not explicit_character else None
            )
            preview_text = character_config.get("api_voice_preview_text") or (
                getattr(self.args, "preview_text", None) if not explicit_character else None
            )
            if not voice_prompt or not preview_text:
                return None
            preferred_name = safe_qwen_voice_name(
                character_config.get("api_clone_preferred_name") or character_id or self.args.clone_prefix
            )
            payload = {
                "model": enrollment_model,
                "input": {
                    "action": "create",
                    "target_model": target_model,
                    "preferred_name": preferred_name,
                    "voice_prompt": str(voice_prompt),
                    "preview_text": str(preview_text),
                    "language": str(language_hint or "zh"),
                },
                "parameters": {"sample_rate": 24000, "response_format": "wav"},
            }
            request_summary = {
                "enrollment_model": enrollment_model,
                "target_model": target_model,
                "preferred_name": preferred_name,
                "voice_prompt_sha256": hashlib.sha256(str(voice_prompt).encode("utf-8")).hexdigest(),
                "preview_text_sha256": hashlib.sha256(str(preview_text).encode("utf-8")).hexdigest(),
                "language": language_hint or "zh",
            }
        else:
            clone_source = character_config.get("api_clone_audio_url") or character_config.get("api_clone_audio_path")
            if not clone_source and not explicit_character:
                clone_source = self.args.clone_audio_url or getattr(self.args, "clone_audio_path", None)
            if not clone_source:
                return None
            reference_text = (
                character_config.get("api_clone_reference_text")
                or (getattr(self.args, "clone_reference_text", None) if not explicit_character else None)
            )
            audio_data, source_kind, source_fingerprint = audio_data_for_source(self.workdir, clone_source)
            max_prompt_audio_length = int(
                character_config.get("api_clone_max_prompt_audio_length") or self.args.max_prompt_audio_length
            )
            enable_preprocess = bool(
                character_config.get("api_clone_enable_preprocess", self.args.enable_preprocess)
            )

            if enrollment_model == "qwen-voice-enrollment":
                target_model = configured_target or "qwen3-tts-vc-2026-01-22"
                preferred_name = safe_qwen_voice_name(
                    character_config.get("api_clone_preferred_name") or character_id or self.args.clone_prefix
                )
                input_payload = {
                    "action": "create",
                    "target_model": target_model,
                    "preferred_name": preferred_name,
                    "audio": {"data": audio_data},
                }
                if reference_text:
                    input_payload["text"] = str(reference_text)
                if language_hint:
                    input_payload["language"] = str(language_hint)
                payload = {"model": enrollment_model, "input": input_payload}
                request_summary = {
                    "enrollment_model": enrollment_model,
                    "target_model": target_model,
                    "preferred_name": preferred_name,
                    "source_kind": source_kind,
                    "source_sha256": source_fingerprint,
                    "reference_language": language_hint,
                    "has_reference_text": bool(reference_text),
                }
            elif enrollment_model == "voice-enrollment":
                if not str(clone_source).startswith(("http://", "https://")):
                    raise ValueError("CosyVoice voice-enrollment requires a provider-accessible HTTP(S) URL.")
                prefix = safe_cosyvoice_prefix(
                    character_config.get("api_clone_prefix") or character_id or self.args.clone_prefix
                )
                payload = {
                    "model": enrollment_model,
                    "input": {
                        "action": "create_voice",
                        "target_model": target_model,
                        "prefix": prefix,
                        "url": str(clone_source),
                        "language_hints": [language_hint] if language_hint else [],
                        "max_prompt_audio_length": max_prompt_audio_length,
                        "enable_preprocess": enable_preprocess,
                    },
                }
                request_summary = {
                    "enrollment_model": enrollment_model,
                    "target_model": target_model,
                    "prefix": prefix,
                    "source_kind": source_kind,
                    "source_sha256": source_fingerprint,
                    "reference_language": language_hint,
                    "max_prompt_audio_length": max_prompt_audio_length,
                    "enable_preprocess": enable_preprocess,
                }
            else:
                raise ValueError(f"Unsupported enrollment model: {enrollment_model}")

        key = hashlib.sha256(
            json.dumps(request_summary, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        # Enrollment and voices.json updates are process-global; serialize both.
        with self.enrollment_lock:
            cache = {}
            if self.voice_cache_path.exists():
                cache = json.loads(self.voice_cache_path.read_text(encoding="utf-8-sig"))
            if key in cache and cache[key].get("voice_id"):
                voice_id = cache[key]["voice_id"]
                if not explicit_character:
                    self.voice_id = voice_id
                return voice_id

            response = self._api_post(VOICE_ENROLLMENT_PATH, payload)
            output = response.get("output", {})
            voice_id = output.get("voice_id") or output.get("voice")
            if not voice_id:
                output_keys = sorted(output) if isinstance(output, dict) else []
                raise RuntimeError(
                    f"Voice enrollment response did not include voice_id/voice; output keys: {output_keys}"
                )
            safe_response = json.loads(json.dumps(response, ensure_ascii=False))
            preview = safe_response.get("output", {}).get("preview_audio")
            if isinstance(preview, dict) and preview.get("data"):
                preview["data"] = "<redacted>"
            cache[key] = {
                "voice_id": voice_id,
                "request": request_summary,
                "response": safe_response,
                "created_at": time.time(),
            }
            write_json(self.voice_cache_path, cache)
            if not explicit_character:
                self.voice_id = voice_id
            return voice_id

    def _generator_loop(self):
        while True:
            job_id = self.job_queue.get()
            try:
                self._run_job(job_id)
            except Exception:
                self._set_job(job_id, status="error", error=traceback.format_exc())
            finally:
                self.job_queue.task_done()

    def _run_job(self, job_id):
        job = self._set_job(job_id, status="running")
        job_cache_dir = Path(job["cache_dir"])
        chunk_paths = []
        chunks = []
        for i, sentence in enumerate(job["sentences"], start=1):
            settings = {
                "model": job["model"],
                "voice": job["voice"],
                "language": job["language"],
                "language_hint": job.get("language_hint"),
                "instructions": job["instructions"],
                "send_instructions": job["send_instructions"],
                "optimize_instructions": job["optimize_instructions"],
                "volume": job["volume"],
                "speech_rate": job["speech_rate"],
                "pitch_rate": job["pitch_rate"],
            }
            key = cache_key(sentence, settings)
            sentence_wav = job_cache_dir / f"{i:03d}-{key[:16]}.wav"
            metadata_path = job_cache_dir / f"{i:03d}-{key[:16]}.json"
            reused = sentence_wav.exists()
            response = None
            if not reused:
                response = self._synthesize(sentence, job, sentence_wav)

            chunk = {
                "index": i,
                "sentence": sentence,
                "wav": str(sentence_wav),
                "cache_key": key,
                "reused": reused,
                "duration_seconds": round(wav_duration(sentence_wav), 3),
                "language": job["language"],
            }
            write_json(
                metadata_path,
                {
                    **chunk,
                    "settings": public_settings(settings),
                    "response": persisted_provider_response(
                        response,
                        voice_values=(job.get("voice"),),
                    ),
                },
            )
            chunks.append(chunk)
            chunk_paths.append(sentence_wav)
            self._set_job(job_id, current=i, chunks=chunks)
            if job["play"]:
                self.play_queue.put(sentence_wav)

        out_path = Path(job["output"])
        concatenate_wavs(chunk_paths, out_path)
        self._set_job(job_id, status="done", current=len(chunk_paths), chunks=chunks, output=str(out_path))

    def _synthesize(self, sentence, job, out_path):
        if str(job["model"]).startswith("cosyvoice-"):
            return self._synthesize_cosyvoice(sentence, job, out_path)

        input_payload = {
            "text": sentence,
            "voice": job["voice"],
            "language_type": job["language"] or "Auto",
            "stream": False,
        }
        if (
            is_qwen_instruct_model(job["model"])
            and job.get("send_instructions")
            and job["instructions"]
        ):
            input_payload["instructions"] = job["instructions"]
            input_payload["optimize_instructions"] = bool(job["optimize_instructions"])
        payload = {"model": job["model"], "input": input_payload}
        response = self._api_post(TTS_PATH, payload)
        audio = response.get("output", {}).get("audio", {})
        if audio.get("data"):
            raw = base64.b64decode(audio["data"])
        elif audio.get("url"):
            with urlopen(audio["url"], timeout=120) as resp:
                raw = resp.read()
        else:
            output = response.get("output")
            output_keys = sorted(output) if isinstance(output, dict) else []
            request_id = response.get("request_id") or response.get("requestId")
            safe_request_id = (
                re.sub(r"[^A-Za-z0-9_.-]+", "_", str(request_id))[:120]
                if request_id
                else "unknown"
            )
            raise RuntimeError(
                "TTS response did not include audio data or URL; "
                f"request_id={safe_request_id}, output_keys={output_keys}"
            )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
        normalize_wav_header(out_path)
        return response

    def _synthesize_cosyvoice(self, sentence, job, out_path):
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

        dashscope.api_key = self.api_key
        writer = CosyVoiceFileWriter(out_path).inner
        synthesizer = SpeechSynthesizer(
            model=job["model"],
            voice=job["voice"],
            format=AudioFormat.WAV_24000HZ_MONO_16BIT,
            volume=job["volume"],
            speech_rate=job["speech_rate"],
            pitch_rate=job["pitch_rate"],
            language_hints=[job["language_hint"]] if job.get("language_hint") else None,
            callback=writer,
            url="wss://dashscope.aliyuncs.com/api-ws/v1/inference",
            instruction=job["instructions"] if job.get("send_instructions") else None,
        )
        synthesizer.async_call = False
        try:
            synthesizer.call(sentence, timeout_millis=120000)
            synthesizer.close()
        finally:
            writer.on_close()
        if writer.error:
            raise RuntimeError(writer.error)
        if not Path(out_path).exists() or Path(out_path).stat().st_size <= 0:
            raise RuntimeError(f"No CosyVoice audio written: {out_path}")
        fix_wav_sizes(out_path)
        return {
            "request_id": synthesizer.get_last_request_id(),
            "model": job["model"],
            "voice": job["voice"],
            "engine": "CosyVoice",
        }

    def _playback_loop(self):
        if self.args.no_play:
            return
        import winsound
        while True:
            path = self.play_queue.get()
            try:
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
            finally:
                self.play_queue.task_done()


def make_handler(worker):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            print(f"[http] {self.address_string()} {fmt % args}")

        def _send_json(self, status, data):
            encoded = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                self._send_json(200, {"ok": True, "ready": worker.ready, "engine": "Qwen-TTS-API"})
                return
            if parsed.path == "/status":
                self._send_json(200, worker.snapshot())
                return
            if parsed.path.startswith("/status/"):
                job_id = parsed.path.rsplit("/", 1)[-1]
                try:
                    self._send_json(200, worker.snapshot(job_id))
                except KeyError:
                    self._send_json(404, {"error": "job not found"})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/speak":
                self._send_json(404, {"error": "not found"})
                return
            payload = {}
            try:
                request_payload = self._read_json()
                if not isinstance(request_payload, dict):
                    raise ValueError("JSON body must be an object.")
                payload = request_payload
                job = worker.submit(
                    text=payload.get("text", ""),
                    character_id=payload.get("character_id"),
                    session_id=payload.get("session_id"),
                    voice=payload.get("voice"),
                    voice_id=payload.get("voice_id"),
                    language=payload.get("language"),
                    language_hint=payload.get("language_hint"),
                    instructions=payload.get("instructions"),
                    send_instructions=payload.get("send_instructions"),
                    optimize_instructions=payload.get("optimize_instructions"),
                    volume=payload.get("volume"),
                    speech_rate=payload.get("speech_rate"),
                    pitch_rate=payload.get("pitch_rate"),
                    play=payload.get("play", True),
                    model=payload.get("model"),
                )
                self._send_json(202, public_job(job))
            except Exception as exc:
                self._send_json(
                    400,
                    {
                        "error": redact_sensitive_text(
                            exc,
                            (payload.get("voice_id"), payload.get("voice")),
                        )
                    },
                )

    return Handler


def startup_event(worker, args):
    return {
        "event": "listening",
        "url": f"http://{args.host}:{args.port}",
        "engine": "Qwen-TTS-API",
        "character_id": args.character_id,
        "model": worker.default_model,
        "voice_configured": bool(worker.voice_id or worker.default_voice),
        "has_default_instructions": bool(worker.default_instructions),
        "workdir": str(worker.workdir),
        "cache_dir": str(worker.cache_dir),
        "output_dir": str(worker.output_dir),
    }


def main():
    args = parse_args()
    worker = QwenTTSApiWorker(args)
    worker.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(worker))
    print(json.dumps(startup_event(worker, args), ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
