from __future__ import annotations

import asyncio
import json
import os
import uuid
import mimetypes
import base64
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.core.llm_inference import (
    build_parameter_prompt,
    character_context,
    extract_json_object,
    heuristic_parameters,
    sanitize_parameters,
)
from app.core.playback_queue import GlobalPlaybackCoordinator, PlaybackStatusPollGrace


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_WORKSPACE = Path(os.environ.get("LOCAL_TTS_WORKSPACE", PROJECT_DIR)).resolve()
DEFAULT_WORKER_URL = os.environ.get("LOCAL_TTS_WORKER_URL", "http://127.0.0.1:8765")
PARAMETER_PROMPT_TEMPLATE = APP_DIR / "prompts" / "parameter_inference.zh.md"
TTS_MODEL_CAPABILITIES_PATH = APP_DIR / "tts_model_capabilities.json"
LLM_BASE_URL = os.environ.get("OUMUQ_LLM_BASE_URL", "").strip().rstrip("/")
LLM_API_KEY = os.environ.get("OUMUQ_LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("OUMUQ_LLM_MODEL", "").strip()
DEFAULT_ALLOWED_WORKER_HOSTS = {"127.0.0.1", "localhost", "::1"}
ALLOWED_WORKER_HOSTS = DEFAULT_ALLOWED_WORKER_HOSTS | {
    host.strip().lower()
    for host in os.environ.get("OUMUQ_ALLOWED_WORKER_HOSTS", "").split(",")
    if host.strip()
}
ENGINE_WORKER_URLS = {
    "qwen3-tts": os.environ.get("OUMUQ_QWEN3_TTS_WORKER_URL", "http://127.0.0.1:8765"),
    "qwen3_tts": os.environ.get("OUMUQ_QWEN3_TTS_WORKER_URL", "http://127.0.0.1:8765"),
    "qwen": os.environ.get("OUMUQ_QWEN3_TTS_WORKER_URL", "http://127.0.0.1:8765"),
    "qwen-tts-api": os.environ.get("OUMUQ_QWEN_TTS_API_WORKER_URL", "http://127.0.0.1:8767"),
    "qwen_tts_api": os.environ.get("OUMUQ_QWEN_TTS_API_WORKER_URL", "http://127.0.0.1:8767"),
    "qwen-api": os.environ.get("OUMUQ_QWEN_TTS_API_WORKER_URL", "http://127.0.0.1:8767"),
    "indextts2": os.environ.get("OUMUQ_INDEXTTS2_WORKER_URL", "http://127.0.0.1:8766"),
    "index-tts2": os.environ.get("OUMUQ_INDEXTTS2_WORKER_URL", "http://127.0.0.1:8766"),
    "index_tts2": os.environ.get("OUMUQ_INDEXTTS2_WORKER_URL", "http://127.0.0.1:8766"),
}
SESSION_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
CHARACTER_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"
GLOBAL_PLAYBACK_ENABLED = os.environ.get("OUMUQ_GLOBAL_PLAYBACK", "1").strip().lower() not in {"0", "false", "no", "off"}
GLOBAL_PLAYBACK_POLL_SECONDS = max(0.05, float(os.environ.get("OUMUQ_PLAYBACK_POLL_SECONDS", "0.25")))
GLOBAL_PLAYBACK_TIMEOUT_SECONDS = max(5.0, float(os.environ.get("OUMUQ_PLAYBACK_TIMEOUT_SECONDS", "900")))
GLOBAL_PLAYBACK_STATUS_ERROR_GRACE_SECONDS = max(
    0.0,
    float(os.environ.get("OUMUQ_PLAYBACK_STATUS_ERROR_GRACE_SECONDS", "15")),
)
PLAYBACK_COORDINATOR = GlobalPlaybackCoordinator()
PLAYBACK_MONITOR_TASKS: set[asyncio.Task[Any]] = set()


def infer_language_from_text(text: str, fallback: str | None = None) -> str | None:
    if any("\u3040" <= char <= "\u30ff" for char in text):
        return "Japanese"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return "Chinese"
    if any(char.isascii() and char.isalpha() for char in text):
        return "English"
    return fallback


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=SESSION_ID_PATTERN)
    worker_url: str | None = None
    model: str | None = None
    play: bool = True
    language: str | None = None
    language_hint: str | None = None
    character_id: str | None = Field(default=None, max_length=128, pattern=CHARACTER_ID_PATTERN)
    character_folder: str | None = None
    emotion_tags: list[str] = Field(default_factory=list)
    emotion_vector: list[float] | None = None
    match_patterns: list[str] = Field(default_factory=list)
    prompt_audio: str | None = None
    prompt_audios: list[str] | None = None
    ref_text: str | None = None
    emotion_mode: str | None = None
    emotion_alpha: float | None = None
    emotion_text: str | None = None
    instructions: str | None = None
    send_instructions: bool | None = None
    max_new_tokens: int | None = None

    class Config:
        extra = "allow"


class BatchRequest(BaseModel):
    lines: list[str]
    session_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=SESSION_ID_PATTERN)
    worker_url: str | None = None
    model: str | None = None
    play: bool = True
    language: str | None = None
    language_hint: str | None = None
    character_id: str | None = Field(default=None, max_length=128, pattern=CHARACTER_ID_PATTERN)
    character_folder: str | None = None
    emotion_tags: list[str] = Field(default_factory=list)
    emotion_vector: list[float] | None = None
    match_patterns: list[str] = Field(default_factory=list)
    prompt_audio: str | None = None
    prompt_audios: list[str] | None = None
    ref_text: str | None = None
    emotion_mode: str | None = None
    emotion_alpha: float | None = None
    emotion_text: str | None = None
    instructions: str | None = None
    send_instructions: bool | None = None
    max_new_tokens: int | None = None

    class Config:
        extra = "allow"


class ParameterInferenceRequest(BaseModel):
    text: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=SESSION_ID_PATTERN)
    character_id: str | None = Field(default=None, max_length=128, pattern=CHARACTER_ID_PATTERN)
    provider: str = "auto"
    include_prompt: bool = False


class RouteResolveRequest(BaseModel):
    character_id: str = Field(min_length=1, max_length=128, pattern=CHARACTER_ID_PATTERN)
    session_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=SESSION_ID_PATTERN)
    text: str = ""
    worker_url: str | None = None
    model: str | None = None
    play: bool = True
    language: str | None = None
    language_hint: str | None = None
    character_folder: str | None = None
    emotion_tags: list[str] = Field(default_factory=list)
    emotion_vector: list[float] | None = None
    match_patterns: list[str] = Field(default_factory=list)
    prompt_audio: str | None = None
    prompt_audios: list[str] | None = None
    ref_text: str | None = None
    emotion_mode: str | None = None
    emotion_alpha: float | None = None
    emotion_text: str | None = None
    instructions: str | None = None
    send_instructions: bool | None = None
    max_new_tokens: int | None = None

    class Config:
        extra = "allow"


class VoiceCloneEnrollRequest(BaseModel):
    request_path: str | None = None
    character_id: str | None = Field(default=None, max_length=128, pattern=CHARACTER_ID_PATTERN)
    reference_audio_url: str | None = None
    reference_audio_path: str | None = None
    reference_text: str | None = None
    reference_language: str | None = None
    voice_prompt: str | None = None
    preview_text: str | None = None
    sample_rate: int = Field(default=24000, ge=8000, le=48000)
    response_format: str = Field(default="wav", pattern=r"^(wav|mp3|pcm|opus)$")
    target_model: str | None = None
    prefix: str | None = None
    language_hints: list[str] | None = None
    endpoint: str | None = None
    enrollment_model: str | None = None
    dry_run: bool = False


class VoiceCloneUploadRequest(BaseModel):
    request_path: str | None = None
    character_id: str | None = Field(default=None, max_length=128, pattern=CHARACTER_ID_PATTERN)
    reference_audio_path: str | None = None
    profile: str = "default"
    server_ip: str | None = None
    username: str | None = None
    key_path: str | None = None
    remote_site_path: str | None = None
    public_base_url: str | None = None
    remote_subdir: str | None = None
    validate_url: bool = True


class PublicAudioUploadRequest(BaseModel):
    audio_path: str
    profile: str = "default"
    server_ip: str | None = None
    username: str | None = None
    key_path: str | None = None
    remote_site_path: str | None = None
    public_base_url: str | None = None
    remote_subdir: str | None = None
    validate_url: bool = True
    namespace: str = "fennenote-asr"


app = FastAPI(title="OumuQ")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def path_is_within(path: Path, roots: list[Path]) -> bool:
    resolved = path.resolve()
    return any(resolved == root.resolve() or resolved.is_relative_to(root.resolve()) for root in roots)


TTS_SECRET_FIELDS = {
    "voice",
    "voice_id",
    "api_voice_id",
    "api_clone_audio_url",
    "api_clone_audio_path",
    "api_clone_reference_text",
    "reference_audio_url",
    "reference_audio_path",
    "fallback_prompt_audio",
    "prompt_audio",
    "prompt_audios",
    "prompt_audio_file",
    "prompt_audio_files",
    "reference_audio_file",
    "reference_audio_files",
    "source_audio_path",
    "source_audio_paths",
    "resource_link",
    "authorization",
    "api_key",
    "token",
}
TTS_ERROR_TEXT_FIELDS = {"error", "message", "detail", "provider_error", "raw_response"}


def collect_tts_secret_strings(value: Any, *, secret_context: bool = False) -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for raw_key, item in value.items():
            lowered = str(raw_key).lower()
            secrets.update(
                collect_tts_secret_strings(
                    item,
                    secret_context=lowered in TTS_SECRET_FIELDS or lowered in {"url", "data"},
                )
            )
    elif isinstance(value, (list, tuple)):
        for item in value:
            secrets.update(collect_tts_secret_strings(item, secret_context=secret_context))
    elif secret_context and isinstance(value, str) and len(value) >= 4:
        secrets.add(value)
    return secrets


def redact_tts_string(value: str, secrets: set[str], *, field: str | None = None) -> str:
    if value.startswith("data:"):
        return "<redacted-data-url>"
    safe = value
    for secret in sorted(secrets, key=len, reverse=True):
        safe = safe.replace(secret, "<redacted-secret>")
    if field in TTS_ERROR_TEXT_FIELDS:
        safe = re.sub(r"data:[^\s\"'<>]+", "<redacted-data-url>", safe)
        safe = re.sub(r"https?://[^\s\"'<>]+", "<redacted-url>", safe)
    return safe


def redact_tts_value(value: Any, secrets: set[str], *, field: str | None = None) -> Any:
    if isinstance(value, list):
        return [redact_tts_value(item, secrets, field=field) for item in value]
    if isinstance(value, tuple):
        return [redact_tts_value(item, secrets, field=field) for item in value]
    if not isinstance(value, dict):
        return redact_tts_string(value, secrets, field=field) if isinstance(value, str) else value

    safe: dict[str, Any] = {}
    voice_configured = False
    reference_audio_configured = False
    prompt_audio_configured = False
    prompt_audio_count = 0
    for raw_key, item in value.items():
        key = str(raw_key)
        lowered = key.lower()
        if lowered in TTS_SECRET_FIELDS:
            configured = bool(item)
            if lowered in {"voice", "voice_id", "api_voice_id"}:
                voice_configured = voice_configured or configured
            elif lowered in {
                "prompt_audio",
                "prompt_audios",
                "prompt_audio_file",
                "prompt_audio_files",
                "fallback_prompt_audio",
            }:
                prompt_audio_configured = prompt_audio_configured or configured
                if isinstance(item, (list, tuple)):
                    prompt_audio_count = max(prompt_audio_count, sum(bool(entry) for entry in item))
                elif configured:
                    prompt_audio_count = max(prompt_audio_count, 1)
            else:
                reference_audio_configured = reference_audio_configured or configured
            continue
        if lowered == "data" and isinstance(item, str) and item:
            safe[key] = "<redacted-data>"
            reference_audio_configured = True
            continue
        if lowered == "url" and isinstance(item, str) and item:
            safe[key] = "<redacted-url>"
            reference_audio_configured = True
            continue
        safe[key] = redact_tts_value(item, secrets, field=lowered)
    if voice_configured:
        safe["voice_configured"] = True
    if reference_audio_configured:
        safe["reference_audio_configured"] = True
    if prompt_audio_configured:
        safe["prompt_audio_configured"] = True
        safe.setdefault("prompt_audio_count", prompt_audio_count)
    return safe


def redact_tts_secrets(value: Any) -> Any:
    """Return a public/log-safe copy without voice credentials or reference audio."""
    return redact_tts_value(value, collect_tts_secret_strings(value))


def workspace_path(*parts: str) -> Path:
    return DEFAULT_WORKSPACE.joinpath(*parts)


def parent_workspace_path(*parts: str) -> Path:
    return PROJECT_DIR.parent.joinpath(*parts)


def private_registry_paths() -> list[Path]:
    candidates = [
        workspace_path("voice-references", "reference-index.json"),
        parent_workspace_path("voice-references", "reference-index.json"),
        PROJECT_DIR / "voice-references" / "reference-index.json",
    ]
    unique: list[Path] = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return unique


def reference_path_candidates(value: str | Path) -> list[Path]:
    path = Path(str(value))
    if path.is_absolute():
        return [path]
    candidates = [DEFAULT_WORKSPACE / path, PROJECT_DIR.parent / path, PROJECT_DIR / path]
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def resolve_existing_reference_path(value: str | Path) -> Path:
    candidates = reference_path_candidates(value)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_tts_model_capabilities() -> dict[str, Any]:
    if not TTS_MODEL_CAPABILITIES_PATH.exists():
        return {"version": 1, "models": {}}
    data = read_json(TTS_MODEL_CAPABILITIES_PATH)
    return data if isinstance(data, dict) else {"version": 1, "models": {}}


def run_dir() -> Path:
    now = datetime.now()
    safe_id = uuid.uuid4().hex[:8]
    return workspace_path("runs", now.strftime("%Y-%m-%d"), f"{now.strftime('%H%M%S')}-{safe_id}")


def clean_worker_url(worker_url: str) -> str:
    worker_url = worker_url.strip().rstrip("/")
    parsed = urlparse(worker_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="worker_url must start with http:// or https://")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_WORKER_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_WORKER_HOSTS))
        raise HTTPException(status_code=400, detail=f"worker_url host is not allowed. Allowed hosts: {allowed}")
    return worker_url


def registry_path() -> Path | None:
    for path in private_registry_paths():
        if path.exists():
            return path
    example_path = PROJECT_DIR / "voice-references.example" / "reference-index.json"
    return example_path if example_path.exists() else None


def load_characters() -> tuple[list[dict[str, Any]], Path | None]:
    path = registry_path()
    if path is None:
        return [], None
    registry = read_json(path)
    return list(registry.get("characters", [])), path


def write_registry_characters(characters: list[dict[str, Any]], source: Path | None = None) -> Path:
    path = source or registry_path() or workspace_path("voice-references", "reference-index.json")
    if path.name != "reference-index.json":
        raise HTTPException(status_code=400, detail="Registry path must be reference-index.json")
    if path.exists():
        registry = read_json(path)
        if not isinstance(registry, dict):
            registry = {}
    else:
        registry = {"version": 1, "root": "voice-references"}
    registry["characters"] = characters
    registry.setdefault("version", 1)
    registry.setdefault("root", "voice-references")
    write_json(path, registry)
    return path


def public_character_view(character: dict[str, Any]) -> dict[str, Any]:
    public = dict(character)
    public["api_voice_configured"] = bool(public.get("api_voice_id"))
    for field in (
        "api_voice_id",
        "api_clone_audio_url",
        "api_clone_audio_path",
        "api_clone_reference_text",
        "fallback_prompt_audio",
    ):
        public.pop(field, None)
    public["resolved_worker_url"] = worker_url_for_character(character)
    return public


def find_character(character_id: str | None) -> dict[str, Any] | None:
    if not character_id:
        return None
    for character in load_characters()[0]:
        if str(character.get("id", "")).lower() == character_id.lower():
            return character
    raise HTTPException(status_code=404, detail=f"Unknown character_id: {character_id}")


def require_session_character(session_id: str | None, character_id: str | None) -> None:
    if session_id and not character_id:
        raise HTTPException(status_code=400, detail="character_id is required when session_id is provided")


def validated_character_id(value: str | None) -> str:
    character_id = str(value or "").strip()
    if not re.fullmatch(CHARACTER_ID_PATTERN, character_id):
        raise HTTPException(status_code=400, detail="character_id must be a stable lowercase identifier")
    return character_id


def voice_clone_request_dirs() -> list[Path]:
    roots = [
        DEFAULT_WORKSPACE / "cache" / "voice-clone-requests",
        PROJECT_DIR / "cache" / "voice-clone-requests",
        PROJECT_DIR.parent / "FenneNote" / "cache" / "voice-clone-requests",
        PROJECT_DIR.parent / "FenneNote" / "dist" / "FenneNote" / "cache" / "voice-clone-requests",
    ]
    return list(dict.fromkeys(path.resolve() for path in roots))


def list_voice_clone_request_files() -> list[Path]:
    files: list[Path] = []
    roots = voice_clone_request_dirs()
    for folder in roots:
        if folder.exists():
            for candidate in folder.glob("*.json"):
                try:
                    path = candidate.resolve(strict=True)
                except OSError:
                    continue
                if path.is_file() and path_is_within(path, roots):
                    files.append(path)
    return sorted(set(files), key=lambda path: path.stat().st_mtime, reverse=True)


def load_voice_clone_request(path_value: str | None = None, character_id: str | None = None) -> tuple[dict[str, Any], Path]:
    if path_value:
        path = Path(path_value)
        if not path.is_absolute():
            path = DEFAULT_WORKSPACE / path
        try:
            path = path.resolve(strict=True)
        except OSError as exc:
            raise HTTPException(status_code=404, detail="Voice clone request not found.") from exc
        if path.suffix.lower() != ".json" or not path.is_file() or not path_is_within(path, voice_clone_request_dirs()):
            raise HTTPException(status_code=400, detail="Voice clone request path is outside authorized request directories.")
        data = read_json(path)
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Voice clone request must be a JSON object")
        request_character = data.get("character", {})
        request_id = str(
            request_character.get("id", "") if isinstance(request_character, dict) else ""
        ).strip()
        if character_id and request_id.lower() != character_id.lower():
            raise HTTPException(
                status_code=400,
                detail="Voice clone request character_id does not match the requested character.",
            )
        return data, path
    for path in list_voice_clone_request_files():
        if not path_is_within(path, voice_clone_request_dirs()):
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        request_character = data.get("character", {})
        request_id = str(request_character.get("id", "") if isinstance(request_character, dict) else "").strip()
        if not character_id or request_id.lower() == character_id.lower():
            return data, path
    detail = f"No pending voice clone request for character_id: {character_id}" if character_id else "No pending voice clone request found"
    raise HTTPException(status_code=404, detail=detail)


def safe_path_part(value: str, fallback: str = "voice") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def safe_voice_prefix(value: str, fallback: str = "voice") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value.strip())[:10]
    return cleaned or fallback


def safe_qwen_voice_name(value: str, fallback: str = "voice") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value.strip()).strip("_")[:16]
    return cleaned or fallback


def upload_profile_path() -> Path:
    return DEFAULT_WORKSPACE / "cache" / "reference-upload-profiles.json"


def load_upload_profile(name: str) -> dict[str, Any]:
    path = upload_profile_path()
    if not path.exists():
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"Upload profile file must be a JSON object: {path}")
    profiles = data.get("profiles", data)
    if not isinstance(profiles, dict):
        raise HTTPException(status_code=400, detail=f"Upload profile file has invalid profiles: {path}")
    profile = profiles.get(name, {})
    if not isinstance(profile, dict):
        raise HTTPException(status_code=404, detail=f"Upload profile is not an object: {name}")
    return profile


def upload_setting(req: VoiceCloneUploadRequest, profile: dict[str, Any], key: str, env_name: str) -> str:
    value = getattr(req, key, None) or profile.get(key) or os.environ.get(env_name, "")
    value = str(value).strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"Missing upload setting: {key} or {env_name}")
    return value


def to_sftp_remote_path(remote_windows_path: str) -> str:
    normalized = remote_windows_path.replace("\\", "/")
    drive_match = re.match(r"^([A-Za-z]):/(.*)$", normalized)
    if drive_match:
        return f"/{drive_match.group(1).upper()}:/{drive_match.group(2)}"
    return normalized


def run_upload_command(command: list[str], detail: str) -> None:
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        error_text = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        raise HTTPException(status_code=502, detail=f"{detail}: {error_text[:1000]}")


def update_character_clone_audio_url(character_id: str, audio_url: str, request_data: dict[str, Any]) -> Path:
    character_id = character_id.lower()
    characters, source = load_characters()
    pending_character = request_data.get("character", {}) if isinstance(request_data.get("character"), dict) else {}
    updated_character = {
        **pending_character,
        "id": character_id,
        "api_clone_audio_url": audio_url,
        "updated_at": datetime.now().isoformat(),
    }
    for index, character in enumerate(characters):
        if str(character.get("id", "")).strip().lower() == character_id:
            characters[index] = {**character, **updated_character}
            break
    else:
        characters.append(updated_character)
    return write_registry_characters(characters, source)


async def validate_public_audio_url(audio_url: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            response = await client.head(audio_url)
            if response.status_code == 405:
                response = await client.get(audio_url, headers={"Range": "bytes=0-0"})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Uploaded audio URL is not reachable: {exc}") from exc


ALLOWED_REFERENCE_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".mp4"}


def voice_reference_roots() -> list[Path]:
    roots = [
        DEFAULT_WORKSPACE / "voice-references",
        PROJECT_DIR.parent / "voice-references",
        PROJECT_DIR / "voice-references",
    ]
    return list(dict.fromkeys(root.resolve() for root in roots))


def public_audio_upload_roots() -> list[Path]:
    configured = [
        Path(item.strip()).expanduser()
        for item in os.environ.get("OUMUQ_PUBLIC_AUDIO_UPLOAD_ROOTS", "").split(os.pathsep)
        if item.strip()
    ]
    roots = [
        *voice_reference_roots(),
        DEFAULT_WORKSPACE / "cache",
        PROJECT_DIR.parent / "FenneNote" / "cache",
        PROJECT_DIR.parent / "FenneNote" / "recordings",
        *configured,
    ]
    return list(dict.fromkeys(root.resolve() for root in roots))


def authorized_audio_path(path_value: str, roots: list[Path], max_bytes: int) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        candidates = reference_path_candidates(path)
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Audio file does not exist.") from exc
    if not path.is_file() or not path_is_within(path, roots):
        raise HTTPException(status_code=400, detail="Audio path is outside authorized audio directories.")
    if path.suffix.lower() not in ALLOWED_REFERENCE_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="Audio file type is not allowed.")
    size = path.stat().st_size
    if size <= 0 or size > max_bytes:
        raise HTTPException(status_code=400, detail=f"Audio file must be between 1 and {max_bytes} bytes.")
    return path


def validated_public_reference_audio_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="reference_audio_url must be an HTTPS URL without credentials.")
    return value


def data_url_for_audio(path_value: str) -> str:
    path = authorized_audio_path(path_value, voice_reference_roots(), 10 * 1024 * 1024)
    mime_type = mimetypes.guess_type(path.name)[0] or "audio/wav"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def dashscope_headers() -> dict[str, str]:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="DASHSCOPE_API_KEY is not set")
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def build_dashscope_voice_payload(request: VoiceCloneEnrollRequest, pending: dict[str, Any]) -> dict[str, Any]:
    character = pending.get("character", {}) if isinstance(pending.get("character"), dict) else {}
    enrollment_model = request.enrollment_model or character.get("api_enrollment_model")
    configured_target_model = (
        request.target_model
        or character.get("api_target_model")
        or character.get("api_clone_target_model")
    )
    if not enrollment_model:
        if str(configured_target_model).startswith("qwen3-tts-vd-"):
            enrollment_model = "qwen-voice-design"
        elif str(configured_target_model).startswith("qwen3-tts-vc-"):
            enrollment_model = "qwen-voice-enrollment"
        else:
            enrollment_model = "voice-enrollment"
    target_model = configured_target_model or {
        "qwen-voice-design": "qwen3-tts-vd-2026-01-26",
        "qwen-voice-enrollment": "qwen3-tts-vc-2026-01-22",
    }.get(enrollment_model, "cosyvoice-v3-plus")
    audio_url = request.reference_audio_url or pending.get("reference_audio_url") or character.get("api_clone_audio_url")
    if audio_url:
        audio_url = validated_public_reference_audio_url(str(audio_url))
    audio_path = (
        request.reference_audio_path
        or pending.get("reference_audio_path")
        or character.get("api_clone_audio_path")
        or character.get("fallback_prompt_audio")
    )
    language_hint = (
        request.reference_language
        or character.get("api_clone_reference_language")
        or character.get("api_clone_language_hint")
    )
    language_hints = request.language_hints or ([str(language_hint)] if language_hint else [])

    if enrollment_model == "voice-enrollment":
        if not audio_url:
            raise HTTPException(
                status_code=400,
                detail="CosyVoice voice-enrollment needs reference_audio_url. Upload the sample to a provider-accessible URL first.",
            )
        prefix = safe_voice_prefix(str(request.prefix or character.get("api_clone_prefix") or character.get("id") or "voice"))
        return {
            "model": "voice-enrollment",
            "input": {
                "action": "create_voice",
                "target_model": target_model,
                "prefix": prefix,
                "url": audio_url,
                "language_hints": language_hints,
                "max_prompt_audio_length": 20,
                "enable_preprocess": True,
            },
        }

    if enrollment_model == "qwen-voice-enrollment":
        if audio_url:
            audio_data = str(audio_url)
        elif audio_path:
            audio_data = data_url_for_audio(str(resolve_existing_reference_path(str(audio_path))))
        else:
            raise HTTPException(
                status_code=400,
                detail="Qwen voice enrollment needs reference_audio_url or reference_audio_path.",
            )
        preferred_name = safe_qwen_voice_name(
            str(request.prefix or character.get("api_clone_preferred_name") or character.get("id") or "voice")
        )
        reference_text = (
            request.reference_text
            or pending.get("reference_text")
            or character.get("api_clone_reference_text")
        )
        reference_language = (
            request.reference_language
            or pending.get("reference_audio_language")
            or character.get("api_clone_reference_language")
            or (language_hints[0] if language_hints else None)
        )
        input_payload: dict[str, Any] = {
            "action": "create",
            "target_model": target_model,
            "preferred_name": preferred_name,
            "audio": {"data": audio_data},
        }
        if reference_text:
            input_payload["text"] = str(reference_text)
        if reference_language:
            input_payload["language"] = str(reference_language)
        return {"model": "qwen-voice-enrollment", "input": input_payload}

    if enrollment_model == "qwen-voice-design":
        voice_prompt = request.voice_prompt or character.get("api_voice_prompt")
        preview_text = request.preview_text or character.get("api_voice_preview_text")
        if not voice_prompt or not preview_text:
            raise HTTPException(
                status_code=400,
                detail="Qwen voice design needs voice_prompt and preview_text.",
            )
        preferred_name = safe_qwen_voice_name(
            str(request.prefix or character.get("api_clone_preferred_name") or character.get("id") or "voice")
        )
        language = request.reference_language or character.get("api_voice_design_language") or (
            language_hints[0] if language_hints else "zh"
        )
        return {
            "model": "qwen-voice-design",
            "input": {
                "action": "create",
                "target_model": target_model,
                "preferred_name": preferred_name,
                "voice_prompt": str(voice_prompt),
                "preview_text": str(preview_text),
                "language": str(language),
            },
            "parameters": {
                "sample_rate": request.sample_rate,
                "response_format": request.response_format,
            },
        }

    raise HTTPException(status_code=400, detail=f"Unsupported enrollment_model: {enrollment_model}")


def redacted_voice_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return redact_tts_secrets(payload)


def fix_wav_file_sizes(path: Path) -> None:
    data = bytearray(path.read_bytes())
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return
    data_index = data.find(b"data")
    if data_index < 0 or data_index + 8 > len(data):
        return
    data[4:8] = (len(data) - 8).to_bytes(4, "little")
    data[data_index + 4:data_index + 8] = (len(data) - (data_index + 8)).to_bytes(4, "little")
    path.write_bytes(data)


def save_voice_preview(character_id: str, response: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    safe_response = json.loads(json.dumps(response, ensure_ascii=False))
    preview = safe_response.get("output", {}).get("preview_audio")
    if not isinstance(preview, dict) or not preview.get("data"):
        return None, safe_response
    encoded = str(preview.get("data"))
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"DashScope preview audio is not valid Base64: {exc}") from exc
    suffix = safe_path_part(str(preview.get("response_format") or "wav"), "wav").lower()
    preview_dir = DEFAULT_WORKSPACE / "cache" / "voice-design-previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    output = preview_dir / f"{safe_path_part(character_id)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{suffix}"
    output.write_bytes(raw)
    if suffix == "wav":
        fix_wav_file_sizes(output)
    preview["data"] = "<redacted>"
    preview["bytes"] = len(raw)
    return str(output), safe_response


def validated_dashscope_customization_endpoint(value: str) -> str:
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    dedicated_host = bool(
        re.fullmatch(
            r"[a-z0-9-]+\.(?:cn-beijing|ap-southeast-1)\.maas\.aliyuncs\.com",
            host,
        )
    )
    if (
        parsed.scheme != "https"
        or not (host in {"dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"} or dedicated_host)
        or parsed.port not in {None, 443}
        or parsed.path.rstrip("/") != "/api/v1/services/audio/tts/customization"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="Invalid DashScope voice customization endpoint.")
    return value.rstrip("/")


def extract_voice_id(response: dict[str, Any]) -> str:
    output = response.get("output", {}) if isinstance(response, dict) else {}
    for key in ("voice_id", "voice"):
        value = output.get(key) if isinstance(output, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    output_keys = sorted(output) if isinstance(output, dict) else []
    raise HTTPException(
        status_code=502,
        detail=f"DashScope response did not include voice_id/voice; output keys: {output_keys}",
    )


def update_character_voice_id(
    character_id: str,
    voice_id: str,
    request_data: dict[str, Any],
    *,
    target_model: str | None = None,
    enrollment_model: str | None = None,
) -> Path:
    character_id = character_id.lower()
    characters, source = load_characters()
    pending_character = request_data.get("character", {}) if isinstance(request_data.get("character"), dict) else {}
    creation_method = {
        "qwen-voice-design": "voice_design",
        "qwen-voice-enrollment": "voice_cloning",
        "voice-enrollment": "voice_cloning",
    }.get(str(enrollment_model or ""))
    updated_character = {
        **pending_character,
        "id": character_id,
        "api_voice_id": voice_id,
        "updated_at": datetime.now().isoformat(),
    }
    if target_model:
        updated_character["api_target_model"] = target_model
        if "api_clone_target_model" in pending_character:
            updated_character["api_clone_target_model"] = target_model
    if enrollment_model:
        updated_character["api_enrollment_model"] = enrollment_model
    if creation_method:
        updated_character["api_voice_creation_method"] = creation_method
        updated_character["voice_mode"] = (
            "cloud-voice-design" if creation_method == "voice_design" else "cloud-voice-clone"
        )
    for index, character in enumerate(characters):
        if str(character.get("id", "")).strip().lower() == character_id:
            merged_character = {**character, **updated_character}
            if target_model and "api_clone_target_model" in merged_character:
                merged_character["api_clone_target_model"] = target_model
            characters[index] = merged_character
            break
    else:
        characters.append(updated_character)
    return write_registry_characters(characters, source)


def worker_url_for_character(character: dict[str, Any] | None, requested_url: str | None = None) -> str:
    if requested_url:
        return requested_url
    if character:
        character_url = str(character.get("worker_url") or "").strip()
        if character_url:
            return character_url
        engine_key = str(character.get("tts_engine") or "").strip().lower()
        if engine_key in ENGINE_WORKER_URLS:
            return ENGINE_WORKER_URLS[engine_key]
    return DEFAULT_WORKER_URL


def character_folder_exists(character: dict[str, Any]) -> bool:
    folder = character.get("character_folder")
    if not folder:
        return False
    return resolve_existing_reference_path(str(folder)).exists()


def fallback_prompt_audio(character: dict[str, Any]) -> str | None:
    prompt_audio = character.get("fallback_prompt_audio")
    if not prompt_audio:
        return None
    return str(prompt_audio) if resolve_existing_reference_path(str(prompt_audio)).exists() else None


def emotion_intent_to_controls(data: dict[str, Any], character: dict[str, Any] | None = None) -> None:
    if data.get("instructions"):
        return
    tags = [str(tag).lower() for tag in data.get("emotion_tags", []) if str(tag).strip()]
    vector = data.get("emotion_vector") if isinstance(data.get("emotion_vector"), list) else []
    emotion_text = str(data.get("emotion_text") or "").strip()
    alpha = float(data.get("emotion_alpha") or 0.55)
    labels = ["happy", "angry", "sad", "afraid", "disgusted", "melancholic", "surprised", "calm"]
    scores = {label: 0.0 for label in labels}
    for index, value in enumerate(vector[: len(labels)]):
        try:
            scores[labels[index]] = float(value)
        except (TypeError, ValueError):
            continue
    for tag in tags:
        if tag in scores:
            scores[tag] = max(scores[tag], alpha)
        elif tag in {"warm", "gentle", "soft"}:
            scores["calm"] = max(scores["calm"], alpha)
        elif tag in {"cheerful", "bright"}:
            scores["happy"] = max(scores["happy"], alpha)
    dominant = max(scores, key=scores.get) if any(value > 0 for value in scores.values()) else ""
    if not dominant and not emotion_text:
        return

    instruction_map = {
        "happy": ("语气明亮轻快，带一点笑意，像自然聊天，不要夸张。", 1.05, 1.02, 55),
        "angry": ("语气更坚定、有一点不满，但保持清晰克制，不要吼叫。", 1.02, 1.01, 56),
        "sad": ("语气低落一些，声音轻一点，语速稍慢，但仍然清楚自然。", 0.94, 0.97, 50),
        "afraid": ("语气带一点紧张和迟疑，音量稍轻，表达清楚。", 0.96, 1.02, 50),
        "disgusted": ("语气带一点嫌弃和抗拒，但保持自然，不要过度表演。", 0.98, 0.98, 52),
        "melancholic": ("语气有些怅然和疲惫，温柔、缓慢、克制。", 0.93, 0.96, 49),
        "surprised": ("语气带惊讶感，反应更轻快，句尾可以略微上扬。", 1.06, 1.05, 55),
        "calm": ("语气平稳自然，轻柔克制，像安静地陪伴聊天。", 0.98, 1.0, 52),
    }
    instruction, speech_rate, pitch_rate, volume = instruction_map.get(dominant, instruction_map["calm"])
    if emotion_text:
        instruction = f"{emotion_text}。{instruction}"
    data["instructions"] = instruction
    data.setdefault("send_instructions", True)
    data.setdefault("speech_rate", speech_rate)
    data.setdefault("pitch_rate", pitch_rate)
    data.setdefault("volume", volume)


def enrich_request(req: SpeakRequest | BatchRequest) -> dict[str, Any]:
    data = model_data(req)
    require_session_character(req.session_id, req.character_id)
    character = find_character(req.character_id)
    data["worker_url"] = worker_url_for_character(character, req.worker_url)
    requested_language = (req.language or "").strip()
    if requested_language.lower() == "auto":
        requested_language = ""
    fallback_language = character.get("speech_language") if character else None
    data["language"] = requested_language or infer_language_from_text(req.text if isinstance(req, SpeakRequest) else "", fallback_language)
    if character:
        has_api_voice = bool(character.get("api_voice_id"))
        # A named character owns its timbre and target model. Stale client
        # extras must never combine character B with character A's cloud voice.
        data.pop("voice", None)
        data.pop("voice_id", None)
        if character.get("api_voice_id"):
            data["voice_id"] = character.get("api_voice_id")
        target_model = character.get("api_target_model") or character.get("api_clone_target_model")
        if target_model:
            data["model"] = target_model
        if not data.get("language_hint") and character.get("api_clone_language_hint"):
            data["language_hint"] = character.get("api_clone_language_hint")
        if not data.get("instructions"):
            data["instructions"] = str(character.get("api_voice_instructions") or "")
        if data.get("send_instructions") is None and "send_instructions_by_default" in character:
            data["send_instructions"] = bool(character.get("send_instructions_by_default"))
        data.pop("character_folder", None)
        if character_folder_exists(character):
            data["character_folder"] = character.get("character_folder")
        if isinstance(req, SpeakRequest) and not has_api_voice and not req.prompt_audio and not req.prompt_audios:
            data["prompt_audio"] = fallback_prompt_audio(character)
    emotion_intent_to_controls(data, character)
    return {key: value for key, value in data.items() if value not in (None, [], "")}


def payload_from_request(req: SpeakRequest | BatchRequest, text: str) -> dict[str, Any]:
    data = model_data(req)
    data.pop("worker_url", None)
    data.pop("lines", None)
    data["text"] = text
    data["play"] = req.play
    return {key: value for key, value in data.items() if value not in (None, [], "")}


def resolved_worker_request(req: SpeakRequest, text: str | None = None) -> dict[str, Any]:
    enriched = enrich_request(req)
    worker_url = clean_worker_url(str(enriched.pop("worker_url")))
    session_id = str(enriched.pop("session_id", "")).strip() or None
    speech_text = text if text is not None else req.text
    enriched["text"] = speech_text
    enriched_req = SpeakRequest(**enriched)
    payload = payload_from_request(enriched_req, speech_text)
    route_id = str(payload.get("character_id") or "").strip()
    return {
        "worker_url": worker_url,
        "payload": payload,
        "hot_switch": bool(route_id),
        "switch_key": "character_id",
        "route_id": route_id or None,
        "session_id": session_id,
    }


async def call_llm_for_parameters(prompt: str) -> dict[str, Any]:
    if not LLM_BASE_URL or not LLM_MODEL:
        raise RuntimeError("LLM provider is not configured.")

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "You infer JSON-only TTS control parameters for OumuQ."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=body)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM parameter inference failed: {exc}") from exc

    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return extract_json_object(content)


def model_data(model: BaseModel, **kwargs: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


def resolved_output_path(output: str) -> Path:
    path = Path(output)
    if not path.is_absolute():
        path = DEFAULT_WORKSPACE / path
    return path.resolve()


def finish_playback_from_worker_status(sequence: int, data: dict[str, Any], job_id: str) -> bool:
    status = str(data.get("status") or "").lower()
    if status in {"error", "failed", "missing", "cancelled"}:
        PLAYBACK_COORDINATOR.mark_failed(sequence, str(data.get("error") or status), job_id=job_id)
        return True
    if status not in {"done", "completed", "success"}:
        return False
    output = str(data.get("output") or "").strip()
    if not output:
        PLAYBACK_COORDINATOR.mark_failed(sequence, "Worker completed without an output path.", job_id=job_id)
        return True
    PLAYBACK_COORDINATOR.mark_ready(sequence, resolved_output_path(output), job_id=job_id)
    return True


async def monitor_worker_for_playback(sequence: int, worker_url: str, job_id: str) -> None:
    try:
        deadline = asyncio.get_running_loop().time() + GLOBAL_PLAYBACK_TIMEOUT_SECONDS
        poll_grace = PlaybackStatusPollGrace(
            grace_seconds=GLOBAL_PLAYBACK_STATUS_ERROR_GRACE_SECONDS,
            clock=asyncio.get_running_loop().time,
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            while True:
                try:
                    response = await client.get(f"{worker_url}/status/{job_id}")
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, dict):
                        raise ValueError("Worker status must be a JSON object.")
                    poll_grace.note_success()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if poll_grace.note_failure(type(exc).__name__):
                        PLAYBACK_COORDINATOR.mark_failed(
                            sequence,
                            "Worker status remained unavailable after the polling grace period.",
                            job_id=job_id,
                        )
                        return
                    if asyncio.get_running_loop().time() >= deadline:
                        PLAYBACK_COORDINATOR.mark_failed(
                            sequence,
                            f"Timed out waiting for worker job {job_id}.",
                            job_id=job_id,
                        )
                        return
                    await asyncio.sleep(GLOBAL_PLAYBACK_POLL_SECONDS)
                    continue
                if finish_playback_from_worker_status(sequence, data, job_id):
                    return
                if asyncio.get_running_loop().time() >= deadline:
                    PLAYBACK_COORDINATOR.mark_failed(
                        sequence,
                        f"Timed out waiting for worker job {job_id}.",
                        job_id=job_id,
                    )
                    return
                await asyncio.sleep(GLOBAL_PLAYBACK_POLL_SECONDS)
    except asyncio.CancelledError:
        PLAYBACK_COORDINATOR.mark_failed(sequence, "Playback monitor was cancelled.", job_id=job_id)
        raise
    except Exception as exc:
        PLAYBACK_COORDINATOR.mark_failed(sequence, f"Playback monitor failed: {exc}", job_id=job_id)


def schedule_worker_playback(sequence: int, worker_url: str, data: dict[str, Any]) -> None:
    job_id = str(data.get("id") or "").strip()
    if not job_id:
        PLAYBACK_COORDINATOR.mark_failed(sequence, "Worker response did not include a job id.")
        return
    if finish_playback_from_worker_status(sequence, data, job_id):
        return
    task = asyncio.create_task(monitor_worker_for_playback(sequence, worker_url, job_id))
    PLAYBACK_MONITOR_TASKS.add(task)
    task.add_done_callback(PLAYBACK_MONITOR_TASKS.discard)


async def submit_to_worker(req: SpeakRequest, text: str | None = None) -> dict[str, Any]:
    resolved = resolved_worker_request(req, text)
    worker_url = resolved["worker_url"]
    payload = resolved["payload"]
    playback_sequence = None
    folder: Path | None = None
    if GLOBAL_PLAYBACK_ENABLED and bool(payload.get("play", True)):
        playback_sequence = PLAYBACK_COORDINATOR.reserve(
            session_id=resolved.get("session_id"),
            character_id=resolved.get("route_id"),
            worker_url=worker_url,
        )
        # Every worker generates silently. The coordinator owns playback order.
        payload["play"] = False
        resolved["playback"] = {
            "mode": "process-fifo+host-lock",
            "sequence": playback_sequence,
            "overlap_allowed": False,
        }

    try:
        folder = run_dir()
        safe_resolved = redact_tts_secrets(resolved)
        write_json(folder / "request.json", safe_resolved)
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{worker_url}/speak", json=payload)
            response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Worker response must be a JSON object.")
        safe_data = redact_tts_secrets(data)
        write_json(folder / "response.json", safe_data)
        if playback_sequence is not None:
            schedule_worker_playback(playback_sequence, worker_url, data)
    except asyncio.CancelledError:
        if playback_sequence is not None:
            PLAYBACK_COORDINATOR.mark_failed(playback_sequence, "Worker request was cancelled.")
        if folder is not None:
            try:
                write_json(folder / "error.json", {"error": "Worker request was cancelled."})
            except Exception:
                pass
        raise
    except Exception as exc:
        if playback_sequence is not None:
            PLAYBACK_COORDINATOR.mark_failed(
                playback_sequence,
                f"Worker submission failed ({type(exc).__name__}).",
            )
        if isinstance(exc, httpx.HTTPStatusError):
            detail = f"Worker returned HTTP {exc.response.status_code}."
        elif isinstance(exc, httpx.RequestError):
            detail = f"Worker transport failed ({type(exc).__name__})."
        else:
            detail = f"Worker submission failed ({type(exc).__name__})."
        if folder is not None:
            try:
                write_json(folder / "error.json", {"error": detail})
            except Exception:
                pass
        raise HTTPException(status_code=502, detail=detail) from exc

    result = {"run_dir": str(folder), "request": safe_resolved, "worker_response": safe_data}
    if playback_sequence is not None:
        result["playback"] = {
            "mode": "process-fifo+host-lock",
            "sequence": playback_sequence,
            "status": "waiting_generation",
            "overlap_allowed": False,
        }
    return result


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/api/config")
async def config() -> dict[str, Any]:
    capabilities = load_tts_model_capabilities()
    return {
        "workspace": str(DEFAULT_WORKSPACE),
        "default_worker_url": DEFAULT_WORKER_URL,
        "engine_worker_urls": ENGINE_WORKER_URLS,
        "session_routing": {
            "mode": "client-owned",
            "session_field": "session_id",
            "character_required_per_session_request": True,
        },
        "playback": {
            "mode": "process-fifo+host-lock" if GLOBAL_PLAYBACK_ENABLED else "worker-local",
            "ordering_scope": "process" if GLOBAL_PLAYBACK_ENABLED else None,
            "playback_mutex_scope": "host" if GLOBAL_PLAYBACK_ENABLED else None,
            "cross_process_fifo": False if GLOBAL_PLAYBACK_ENABLED else None,
            "overlap_allowed": False if GLOBAL_PLAYBACK_ENABLED else None,
            "status_endpoint": "/api/playback/status",
        },
        "tts_model_capabilities_version": capabilities.get("version"),
        "tts_model_capabilities": "/api/tts-model-capabilities",
        "allowed_worker_hosts": sorted(ALLOWED_WORKER_HOSTS),
        "llm_inference": {
            "configured": bool(LLM_BASE_URL and LLM_MODEL),
            "model": LLM_MODEL or None,
            "base_url": LLM_BASE_URL or None,
        },
        "registry_exists": any(path.exists() for path in private_registry_paths()),
    }


@app.get("/api/tts-model-capabilities")
async def tts_model_capabilities() -> dict[str, Any]:
    return load_tts_model_capabilities()


@app.get("/api/characters")
async def characters() -> dict[str, Any]:
    character_list, source = load_characters()
    return {
        "characters": [public_character_view(character) for character in character_list],
        "source": str(source) if source else None,
    }


@app.get("/api/voice-clone/requests")
async def voice_clone_requests() -> dict[str, Any]:
    requests = []
    for path in list_voice_clone_request_files():
        try:
            data = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        character = data.get("character", {}) if isinstance(data, dict) else {}
        requests.append(
            {
                "path": str(path),
                "status": data.get("status") if isinstance(data, dict) else "",
                "character_id": character.get("id") if isinstance(character, dict) else "",
                "display_name": character.get("display_name_zh") or character.get("display_name") or character.get("name") if isinstance(character, dict) else "",
                "reference_audio_configured": bool(data.get("reference_audio_path")) if isinstance(data, dict) else False,
                "reference_audio_url_configured": bool(data.get("reference_audio_url")) if isinstance(data, dict) else False,
                "created_at": data.get("created_at") if isinstance(data, dict) else "",
            }
        )
    return {"request_dirs": [str(path) for path in voice_clone_request_dirs()], "requests": requests}


@app.post("/api/voice-clone/upload-reference")
async def voice_clone_upload_reference(req: VoiceCloneUploadRequest) -> dict[str, Any]:
    pending, request_path = load_voice_clone_request(req.request_path, req.character_id)
    character = pending.get("character", {}) if isinstance(pending.get("character"), dict) else {}
    character_id = validated_character_id(req.character_id or str(character.get("id", "")).strip())
    audio_path_value = req.reference_audio_path or pending.get("reference_audio_path") or character.get("fallback_prompt_audio")
    if not audio_path_value:
        raise HTTPException(status_code=400, detail="reference_audio_path is required")
    audio_path = authorized_audio_path(
        str(audio_path_value),
        voice_reference_roots(),
        50 * 1024 * 1024,
    )

    profile = load_upload_profile(req.profile)
    server_ip = upload_setting(req, profile, "server_ip", "OUMUQ_REFERENCE_UPLOAD_HOST")
    username = upload_setting(req, profile, "username", "OUMUQ_REFERENCE_UPLOAD_USERNAME")
    key_path_value = str(req.key_path or profile.get("key_path") or os.environ.get("OUMUQ_REFERENCE_UPLOAD_KEY_PATH", "")).strip()
    key_path = Path(key_path_value).expanduser() if key_path_value else None
    remote_site_path = upload_setting(req, profile, "remote_site_path", "OUMUQ_REFERENCE_UPLOAD_REMOTE_SITE_PATH")
    public_base_url = upload_setting(req, profile, "public_base_url", "OUMUQ_REFERENCE_UPLOAD_PUBLIC_BASE_URL").rstrip("/")
    remote_subdir = req.remote_subdir or str(profile.get("remote_subdir") or os.environ.get("OUMUQ_REFERENCE_UPLOAD_REMOTE_SUBDIR", "voice-clone/references"))
    remote_subdir = remote_subdir.strip().strip("/\\")

    ssh_command = shutil.which("ssh")
    sftp_command = shutil.which("sftp")
    if not ssh_command or not sftp_command:
        raise HTTPException(status_code=500, detail="ssh and sftp commands are required")
    ssh_base_args = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if key_path:
        if not key_path.exists():
            raise HTTPException(status_code=400, detail=f"SSH key_path does not exist: {key_path}")
        ssh_base_args.extend(["-i", str(key_path)])
    ssh_target = f"{username}@{server_ip}"

    safe_character = safe_path_part(character_id)
    safe_file = safe_path_part(audio_path.stem, safe_character) + audio_path.suffix.lower()
    remote_subdir_url = remote_subdir.replace("\\", "/")
    remote_relative = f"{remote_subdir_url}/{safe_character}/{safe_file}"
    remote_windows_dir = str(Path(remote_site_path) / remote_subdir.replace("/", "\\") / safe_character)
    remote_windows_file = str(Path(remote_windows_dir) / safe_file)
    remote_script = f"$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Force -Path '{remote_windows_dir}' | Out-Null"
    encoded_script = base64.b64encode(remote_script.encode("utf-16le")).decode("ascii")
    run_upload_command(
        [ssh_command, *ssh_base_args, ssh_target, f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded_script}"],
        "remote directory creation failed",
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="oumuq-upload-"))
    temp_audio = temp_dir / safe_file
    batch_path = temp_dir / "upload.sftp"
    try:
        shutil.copy2(audio_path, temp_audio)
        local_sftp_path = str(temp_audio).replace("\\", "/")
        remote_sftp_path = to_sftp_remote_path(remote_windows_file)
        batch_path.write_text(
            f'put "{local_sftp_path}" "{remote_sftp_path}"\n',
            encoding="ascii",
        )
        run_upload_command([sftp_command, "-b", str(batch_path), *ssh_base_args, ssh_target], "sftp upload failed")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    audio_url = f"{public_base_url}/{remote_relative}"
    if req.validate_url:
        await validate_public_audio_url(audio_url)

    pending["reference_audio_url"] = audio_url
    pending["uploaded_at"] = datetime.now().isoformat()
    if isinstance(character, dict):
        character["api_clone_audio_url"] = audio_url
        character["updated_at"] = datetime.now().isoformat()
        pending["character"] = character
    write_json(request_path, pending)
    registry = update_character_clone_audio_url(character_id, audio_url, pending)
    return {
        "ok": True,
        "character_id": character_id,
        "reference_audio_url_configured": True,
        "request_path": str(request_path),
        "registry": str(registry),
    }


@app.post("/api/audio/upload-public")
async def audio_upload_public(req: PublicAudioUploadRequest) -> dict[str, Any]:
    audio_path = authorized_audio_path(
        str(req.audio_path),
        public_audio_upload_roots(),
        100 * 1024 * 1024,
    )

    profile = load_upload_profile(req.profile)
    server_ip = upload_setting(req, profile, "server_ip", "OUMUQ_REFERENCE_UPLOAD_HOST")
    username = upload_setting(req, profile, "username", "OUMUQ_REFERENCE_UPLOAD_USERNAME")
    key_path_value = str(req.key_path or profile.get("key_path") or os.environ.get("OUMUQ_REFERENCE_UPLOAD_KEY_PATH", "")).strip()
    key_path = Path(key_path_value).expanduser() if key_path_value else None
    remote_site_path = upload_setting(req, profile, "remote_site_path", "OUMUQ_REFERENCE_UPLOAD_REMOTE_SITE_PATH")
    public_base_url = upload_setting(req, profile, "public_base_url", "OUMUQ_REFERENCE_UPLOAD_PUBLIC_BASE_URL").rstrip("/")
    remote_subdir = req.remote_subdir or str(profile.get("remote_subdir") or os.environ.get("OUMUQ_REFERENCE_UPLOAD_REMOTE_SUBDIR", "voice-clone/references"))
    remote_subdir = remote_subdir.strip().strip("/\\")
    namespace = safe_path_part(req.namespace, "fennenote-asr")

    ssh_command = shutil.which("ssh")
    sftp_command = shutil.which("sftp")
    if not ssh_command or not sftp_command:
        raise HTTPException(status_code=500, detail="ssh and sftp commands are required")
    ssh_base_args = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    if key_path:
        if not key_path.exists():
            raise HTTPException(status_code=400, detail=f"SSH key_path does not exist: {key_path}")
        ssh_base_args.extend(["-i", str(key_path)])
    ssh_target = f"{username}@{server_ip}"

    safe_file = safe_path_part(audio_path.stem, namespace) + audio_path.suffix.lower()
    remote_subdir_url = remote_subdir.replace("\\", "/")
    remote_relative = f"{remote_subdir_url}/{namespace}/{safe_file}"
    remote_windows_dir = str(Path(remote_site_path) / remote_subdir.replace("/", "\\") / namespace)
    remote_windows_file = str(Path(remote_windows_dir) / safe_file)
    remote_script = f"$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Force -Path '{remote_windows_dir}' | Out-Null"
    encoded_script = base64.b64encode(remote_script.encode("utf-16le")).decode("ascii")
    run_upload_command(
        [ssh_command, *ssh_base_args, ssh_target, f"powershell -NoProfile -NonInteractive -EncodedCommand {encoded_script}"],
        "remote directory creation failed",
    )

    temp_dir = Path(tempfile.mkdtemp(prefix="oumuq-audio-upload-"))
    temp_audio = temp_dir / safe_file
    batch_path = temp_dir / "upload.sftp"
    try:
        shutil.copy2(audio_path, temp_audio)
        local_sftp_path = str(temp_audio).replace("\\", "/")
        remote_sftp_path = to_sftp_remote_path(remote_windows_file)
        batch_path.write_text(f'put "{local_sftp_path}" "{remote_sftp_path}"\n', encoding="ascii")
        run_upload_command([sftp_command, "-b", str(batch_path), *ssh_base_args, ssh_target], "sftp upload failed")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    audio_url = f"{public_base_url}/{remote_relative}"
    if req.validate_url:
        await validate_public_audio_url(audio_url)
    return {
        "ok": True,
        "audio_url": audio_url,
        "audio_path": str(audio_path),
    }


@app.post("/api/voice-clone/enroll")
async def voice_clone_enroll(req: VoiceCloneEnrollRequest) -> dict[str, Any]:
    pending, path = load_voice_clone_request(req.request_path, req.character_id)
    character = pending.get("character", {}) if isinstance(pending.get("character"), dict) else {}
    character_id = validated_character_id(req.character_id or str(character.get("id", "")).strip())
    payload = build_dashscope_voice_payload(req, pending)
    endpoint = (req.endpoint or os.environ.get("DASHSCOPE_VOICE_ENROLLMENT_URL", "")).strip()
    if not endpoint:
        endpoint = "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
    endpoint = validated_dashscope_customization_endpoint(endpoint)
    if req.dry_run:
        return {
            "dry_run": True,
            "request_path": str(path),
            "endpoint": endpoint,
            "payload": redacted_voice_payload(payload),
        }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(endpoint, headers=dashscope_headers(), json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        detail = f"DashScope voice enrollment failed with HTTP {status}." if status else "DashScope voice enrollment transport failed."
        raise HTTPException(status_code=502, detail=detail) from exc
    data = response.json()
    voice_id = extract_voice_id(data)
    preview_audio_path, safe_data = save_voice_preview(character_id, data)
    actual_enrollment_model = str(payload.get("model") or "") or None
    actual_target_model = str(payload.get("input", {}).get("target_model") or "") or None
    registry = update_character_voice_id(
        character_id,
        voice_id,
        pending,
        target_model=actual_target_model,
        enrollment_model=actual_enrollment_model,
    )
    public_provider_data = redact_tts_secrets(safe_data)
    pending["status"] = "voice_enrolled"
    pending.pop("api_voice_id", None)
    pending["api_voice_configured"] = True
    pending["enrollment_model"] = actual_enrollment_model
    pending["target_model"] = actual_target_model
    pending["enrolled_at"] = datetime.now().isoformat()
    pending["preview_audio_path"] = preview_audio_path
    pending["dashscope_response"] = public_provider_data
    write_json(path, pending)
    return {
        "ok": True,
        "character_id": character_id,
        "api_voice_configured": True,
        "request_path": str(path),
        "registry": str(registry),
        "preview_audio_path": preview_audio_path,
        "dashscope_response": public_provider_data,
    }


@app.post("/api/infer-parameters")
async def infer_parameters(req: ParameterInferenceRequest) -> dict[str, Any]:
    require_session_character(req.session_id, req.character_id)
    character = find_character(req.character_id)
    active_registry = registry_path()
    context_workspace = active_registry.parent.parent if active_registry and active_registry.parent.name == "voice-references" else DEFAULT_WORKSPACE
    context = character_context(context_workspace, character)
    prompt = build_parameter_prompt(
        PARAMETER_PROMPT_TEMPLATE,
        text=req.text,
        character=context["character"],
        character_readme=context["readme"],
        voice_index=context["voice_index"],
    )

    source = "heuristic"
    if req.provider == "llm" or (req.provider == "auto" and LLM_BASE_URL and LLM_MODEL):
        raw_parameters = await call_llm_for_parameters(prompt)
        source = "llm"
    else:
        raw_parameters = heuristic_parameters(req.text, character)

    parameters = sanitize_parameters(raw_parameters)
    response: dict[str, Any] = {"source": source, "parameters": parameters}
    if req.session_id:
        response["session_id"] = req.session_id
    if req.include_prompt:
        response["prompt"] = prompt
    return response


@app.post("/api/route/resolve")
async def route_resolve(req: RouteResolveRequest) -> dict[str, Any]:
    text = req.text.strip() or "route preview"
    route_data = model_data(req)
    route_data["text"] = text
    if not req.text.strip() and not route_data.get("language"):
        character_for_language = find_character(req.character_id)
        if character_for_language and character_for_language.get("speech_language"):
            route_data["language"] = character_for_language.get("speech_language")
    speak_req = SpeakRequest(**route_data)
    resolved = resolved_worker_request(speak_req)
    payload = dict(resolved["payload"])
    if not req.text.strip():
        payload.pop("text", None)
    character = find_character(req.character_id)
    public_resolved = redact_tts_secrets({**resolved, "payload": payload})
    return {
        **public_resolved,
        "character": {
            "id": character.get("id") if character else req.character_id,
            "name": character.get("name") if character else None,
            "display_name_zh": character.get("display_name_zh") if character else None,
            "tts_engine": character.get("tts_engine") if character else None,
            "speech_language": character.get("speech_language") if character else None,
        },
    }


@app.post("/api/speak")
async def speak(req: SpeakRequest) -> dict[str, Any]:
    return await submit_to_worker(req)


@app.post("/api/batch")
async def batch(req: BatchRequest) -> dict[str, Any]:
    clean_lines = [line.strip() for line in req.lines if line.strip()]
    if not clean_lines:
        raise HTTPException(status_code=400, detail="No non-empty lines to submit.")
    jobs = []
    for line in clean_lines:
        speak_req = SpeakRequest(**model_data(req, exclude={"lines"}), text=line)
        jobs.append(await submit_to_worker(speak_req))
    return {"submitted": len(jobs), "jobs": jobs}


@app.get("/api/playback/status")
async def playback_status(limit: int = 100) -> dict[str, Any]:
    status = PLAYBACK_COORDINATOR.snapshot(limit=max(1, min(limit, 500)))
    status["enabled"] = GLOBAL_PLAYBACK_ENABLED
    return status


@app.get("/api/worker/status")
async def worker_status(worker_url: str = DEFAULT_WORKER_URL) -> dict[str, Any]:
    worker_url = clean_worker_url(worker_url)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{worker_url}/status")
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                data.setdefault("worker_url", worker_url)
                data.setdefault("playback_host", data.get("engine") or "OumuQ worker")
                data.setdefault("windows_volume_process", data.get("playback_host") or "Python")
                data.setdefault(
                    "windows_volume_hint",
                    "This is the process that plays audio. In Windows Volume Mixer it may appear as the playback host, or as Python for Python-based workers."
                )
            return redact_tts_secrets(data)
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        detail = f"Worker status failed with HTTP {status}." if status else "Worker status transport failed."
        raise HTTPException(status_code=502, detail=detail) from exc


@app.get("/api/worker/status/{job_id}")
async def worker_job_status(job_id: str, worker_url: str = DEFAULT_WORKER_URL) -> dict[str, Any]:
    worker_url = clean_worker_url(worker_url)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{worker_url}/status/{job_id}")
            response.raise_for_status()
            return redact_tts_secrets(response.json())
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        detail = f"Worker job status failed with HTTP {status}." if status else "Worker job status transport failed."
        raise HTTPException(status_code=502, detail=detail) from exc


@app.get("/api/runs")
async def runs(limit: int = 30, session_id: str | None = None, character_id: str | None = None) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    root = workspace_path("runs")
    items = []
    if root.exists():
        response_paths = sorted(root.glob("*/*/response.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for response_path in response_paths:
            try:
                response = read_json(response_path)
                request_path = response_path.parent / "request.json"
                request = read_json(request_path) if request_path.exists() else {}
                payload = request.get("payload", {}) if isinstance(request, dict) else {}
                request_session_id = str(request.get("session_id") or payload.get("session_id") or "")
                request_character_id = str(request.get("route_id") or payload.get("character_id") or "")
                if session_id and request_session_id != session_id:
                    continue
                if character_id and request_character_id.lower() != character_id.lower():
                    continue
                items.append(
                    {
                        "run_dir": str(response_path.parent),
                        "created_at": datetime.fromtimestamp(response_path.stat().st_mtime).isoformat(timespec="seconds"),
                        "request": redact_tts_secrets(request),
                        "response": redact_tts_secrets(response),
                    }
                )
                if len(items) >= limit:
                    break
            except Exception:
                continue
    return {"runs": items, "filters": {"session_id": session_id, "character_id": character_id}}
