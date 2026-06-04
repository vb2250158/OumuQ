from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
DEFAULT_WORKSPACE = Path(os.environ.get("LOCAL_TTS_WORKSPACE", PROJECT_DIR)).resolve()
DEFAULT_WORKER_URL = os.environ.get("LOCAL_TTS_WORKER_URL", "http://127.0.0.1:8765")


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1)
    worker_url: str = DEFAULT_WORKER_URL
    play: bool = True
    language: str | None = None
    character_id: str | None = None
    character_folder: str | None = None
    emotion_tags: list[str] = Field(default_factory=list)
    emotion_vector: list[float] | None = None
    match_patterns: list[str] = Field(default_factory=list)
    prompt_audio: str | None = None
    prompt_audios: list[str] | None = None
    max_new_tokens: int | None = None


class BatchRequest(BaseModel):
    lines: list[str]
    worker_url: str = DEFAULT_WORKER_URL
    play: bool = True
    language: str | None = None
    character_id: str | None = None
    character_folder: str | None = None
    emotion_tags: list[str] = Field(default_factory=list)
    emotion_vector: list[float] | None = None
    match_patterns: list[str] = Field(default_factory=list)
    max_new_tokens: int | None = None


app = FastAPI(title="OumuQ")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def workspace_path(*parts: str) -> Path:
    return DEFAULT_WORKSPACE.joinpath(*parts)


def run_dir() -> Path:
    now = datetime.now()
    safe_id = uuid.uuid4().hex[:8]
    return workspace_path("runs", now.strftime("%Y-%m-%d"), f"{now.strftime('%H%M%S')}-{safe_id}")


def clean_worker_url(worker_url: str) -> str:
    worker_url = worker_url.strip().rstrip("/")
    if not re.match(r"^https?://", worker_url):
        raise HTTPException(status_code=400, detail="worker_url must start with http:// or https://")
    return worker_url


def payload_from_request(req: SpeakRequest | BatchRequest, text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "text": text,
        "play": req.play,
    }
    for key in (
        "language",
        "character_id",
        "character_folder",
        "emotion_tags",
        "emotion_vector",
        "match_patterns",
        "max_new_tokens",
    ):
        value = getattr(req, key)
        if value not in (None, [], ""):
            payload[key] = value
    if isinstance(req, SpeakRequest):
        if req.prompt_audio:
            payload["prompt_audio"] = req.prompt_audio
        if req.prompt_audios:
            payload["prompt_audios"] = req.prompt_audios
    return payload


def model_data(model: BaseModel, **kwargs: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    return model.dict(**kwargs)


async def submit_to_worker(req: SpeakRequest, text: str | None = None) -> dict[str, Any]:
    worker_url = clean_worker_url(req.worker_url)
    speech_text = text if text is not None else req.text
    payload = payload_from_request(req, speech_text)
    folder = run_dir()
    write_json(folder / "request.json", {"worker_url": worker_url, "payload": payload})
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{worker_url}/speak", json=payload)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        write_json(folder / "error.json", {"error": str(exc)})
        raise HTTPException(status_code=502, detail=f"Worker request failed: {exc}") from exc
    data = response.json()
    write_json(folder / "response.json", data)
    return {"run_dir": str(folder), "worker_response": data}


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "workspace": str(DEFAULT_WORKSPACE),
        "default_worker_url": DEFAULT_WORKER_URL,
        "registry_exists": workspace_path("voice-references", "reference-index.json").exists(),
    }


@app.get("/api/characters")
async def characters() -> dict[str, Any]:
    registry_path = workspace_path("voice-references", "reference-index.json")
    if not registry_path.exists():
        registry_path = PROJECT_DIR / "voice-references.example" / "reference-index.json"
    if not registry_path.exists():
        return {"characters": [], "source": None}
    registry = read_json(registry_path)
    return {"characters": registry.get("characters", []), "source": str(registry_path)}


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


@app.get("/api/worker/status")
async def worker_status(worker_url: str = DEFAULT_WORKER_URL) -> dict[str, Any]:
    worker_url = clean_worker_url(worker_url)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{worker_url}/status")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Worker status failed: {exc}") from exc


@app.get("/api/runs")
async def runs(limit: int = 30) -> dict[str, Any]:
    root = workspace_path("runs")
    items = []
    if root.exists():
        for response_path in sorted(root.glob("*/*/response.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
            try:
                response = read_json(response_path)
                request_path = response_path.parent / "request.json"
                request = read_json(request_path) if request_path.exists() else {}
                items.append(
                    {
                        "run_dir": str(response_path.parent),
                        "created_at": datetime.fromtimestamp(response_path.stat().st_mtime).isoformat(timespec="seconds"),
                        "request": request,
                        "response": response,
                    }
                )
            except Exception:
                continue
    return {"runs": items}
