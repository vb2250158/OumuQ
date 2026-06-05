from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


class SpeakPayload(BaseModel):
    text: str = Field(min_length=1)
    play: bool = True
    language: str | None = None
    character_id: str | None = None
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


app = FastAPI(title="OumuQ Mock Worker")
jobs: dict[str, dict[str, Any]] = {}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/status")
async def status() -> dict[str, Any]:
    return {"engine": "MockTTS", "ready": True, "queued": 0, "jobs": len(jobs)}


@app.get("/status/{job_id}")
async def job_status(job_id: str) -> dict[str, Any]:
    return jobs.get(job_id, {"id": job_id, "status": "missing"})


@app.post("/speak")
async def speak(payload: SpeakPayload) -> dict[str, Any]:
    job_id = f"mock-{uuid.uuid4().hex[:8]}"
    job = {
        "id": job_id,
        "status": "done",
        "text": payload.text,
        "output": f"mock-outputs/{job_id}.wav",
        "play": payload.play,
        "language": payload.language,
        "character_id": payload.character_id,
        "character_folder": payload.character_folder,
        "emotion_tags": payload.emotion_tags,
        "emotion_vector": payload.emotion_vector,
        "match_patterns": payload.match_patterns,
        "prompt_audio": payload.prompt_audio,
        "prompt_audios": payload.prompt_audios,
        "ref_text": payload.ref_text,
        "emotion_mode": payload.emotion_mode,
        "emotion_alpha": payload.emotion_alpha,
        "emotion_text": payload.emotion_text,
        "instructions": payload.instructions,
        "send_instructions": payload.send_instructions,
        "max_new_tokens": payload.max_new_tokens,
    }
    jobs[job_id] = job
    return job
