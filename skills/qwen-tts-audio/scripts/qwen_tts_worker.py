#!/usr/bin/env python
import argparse
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
import uuid
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

WORKER_SCRIPTS = Path(__file__).resolve().parent
if str(WORKER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(WORKER_SCRIPTS))
from voice_reference import VoiceReferenceResolver  # noqa: E402


DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def parse_args():
    parser = argparse.ArgumentParser(description="Persistent local HTTP worker for Qwen3-TTS voice clone generation.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--cache-dir", default=".qwen-tts-cache")
    parser.add_argument("--output-dir", default="qwen-tts-output")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-audio", default="BB语音.mp3")
    parser.add_argument("--ref-text", default=None)
    parser.add_argument("--language", default="Japanese")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--min-prompt-duration", type=float, default=6.0)
    parser.add_argument("--target-prompt-duration", type=float, default=10.0)
    parser.add_argument("--prompt-gap-seconds", type=float, default=0.12)
    parser.add_argument("--no-play", action="store_true")
    return parser.parse_args()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def split_sentences(text, max_chunk_chars=90):
    text = re.sub(r"\s+", " ", text.strip())
    if not text:
        return []
    parts = re.findall(r".+?[.!?\u3002\uff01\uff1f\uff1b;]+[\"'”’）】』」]*|.+$", text)
    sentences = []
    for part in (part.strip() for part in parts if part.strip()):
        if re.fullmatch(r"[\"'“”‘’（）()【】『』「」]+", part) and sentences:
            sentences[-1] += part
        else:
            sentences.append(part)

    merged = []
    current = ""
    for sentence in sentences:
        candidate = current + sentence if current else sentence
        if current and len(candidate) > max_chunk_chars:
            merged.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        merged.append(current)
    return merged


def cache_key(sentence, prompt_audio, settings):
    payload = {
        "sentence": sentence,
        "prompt_audio_sha256": sha256_file(prompt_audio),
        "settings": settings,
        "engine": "Qwen3-TTS",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def wav_duration(path):
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def concatenate_wavs(paths, out_path, gap_seconds=0.04):
    import numpy as np

    chunks = []
    target_sr = None
    for path in paths:
        data, sr = sf.read(str(path), dtype="float32")
        if target_sr is None:
            target_sr = sr
        elif sr != target_sr:
            raise RuntimeError(f"Cannot concatenate WAV files with different sample rates: {path}")
        if data.ndim > 1:
            data = data.mean(axis=1)
        chunks.append(data)
        chunks.append(np.zeros(int(target_sr * gap_seconds), dtype="float32"))
    if not chunks:
        raise RuntimeError("No audio chunks generated.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), np.concatenate(chunks), target_sr)


def normalize_tags(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip().lower() for part in re.split(r"[,，\s]+", value) if part.strip()]
    if isinstance(value, list):
        return [str(part).strip().lower() for part in value if str(part).strip()]
    return []


def parse_vector(value):
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        parts = value
    else:
        return None
    try:
        vector = [float(part) for part in parts]
    except (TypeError, ValueError):
        return None
    return vector if vector else None


class QwenTTSWorker:
    def __init__(self, args):
        self.args = args
        self.workdir = Path(args.workdir).resolve() if args.workdir else Path.cwd().resolve()
        self.cache_dir = Path(args.cache_dir)
        if not self.cache_dir.is_absolute():
            self.cache_dir = self.workdir / self.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.worker_cache_dir = self.cache_dir / "worker"
        self.worker_cache_dir.mkdir(parents=True, exist_ok=True)
        self.reference_cache_dir = self.cache_dir / "reference-audio"
        self.reference_cache_dir.mkdir(parents=True, exist_ok=True)

        self.output_dir = Path(args.output_dir)
        if not self.output_dir.is_absolute():
            self.output_dir = self.workdir / self.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.prompt_audio = Path(args.prompt_audio)
        if not self.prompt_audio.is_absolute():
            self.prompt_audio = self.workdir / self.prompt_audio
        self.prompt_audio = self.prompt_audio.resolve()
        if not self.prompt_audio.exists():
            raise FileNotFoundError(f"Prompt audio not found: {self.prompt_audio}")
        self.voice_refs = VoiceReferenceResolver(
            workdir=self.workdir,
            reference_cache_dir=self.reference_cache_dir,
            default_prompt_audio=self.prompt_audio,
            min_prompt_duration=args.min_prompt_duration,
            target_prompt_duration=args.target_prompt_duration,
            prompt_gap_seconds=args.prompt_gap_seconds,
        )

        self.settings = {
            "model": args.model,
            "language": args.language,
            "ref_text": args.ref_text,
            "max_new_tokens": args.max_new_tokens,
        }
        self.jobs = {}
        self.job_queue = queue.Queue()
        self.play_queue = queue.Queue()
        self.lock = threading.Lock()
        self.tts = None
        self.voice_prompt_cache = {}
        self.ready = False
        self.started_at = time.time()

    def start(self):
        threading.Thread(target=self._generator_loop, daemon=True).start()
        threading.Thread(target=self._playback_loop, daemon=True).start()

    def load_model(self):
        if self.tts is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        self.tts = Qwen3TTSModel.from_pretrained(
            self.args.model,
            device_map="cuda:0" if torch.cuda.is_available() else "cpu",
            dtype=dtype,
            attn_implementation="sdpa",
            local_files_only=True,
        )
        self.ready = True

    def submit(
        self,
        text,
        prompt_audio=None,
        prompt_audios=None,
        character_id=None,
        session_id=None,
        character_folder=None,
        emotion_tags=None,
        emotion_vector=None,
        match_patterns=None,
        language=None,
        ref_text=None,
        play=True,
        max_new_tokens=None,
    ):
        sentences = split_sentences(text)
        if not sentences:
            raise ValueError("No text to synthesize.")
        character_folder_path = self._resolve_character_folder(character_id, character_folder)
        prompt_files = self._resolve_prompt_files(
            prompt_audio,
            prompt_audios,
            text,
            character_folder_path,
            emotion_tags,
            emotion_vector,
            match_patterns,
        )
        prompt, prompt_source_files, prompt_was_augmented = self._prepare_prompt_audio(prompt_files)
        default_ref_text = None if character_id or character_folder else self.args.ref_text

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
            "prompt_audio": str(prompt),
            "prompt_audio_files": [str(path) for path in prompt_source_files],
            "prompt_audio_augmented": prompt_was_augmented,
            "character_id": character_id,
            "session_id": str(session_id or "").strip() or None,
            "character_folder": str(character_folder_path) if character_folder_path else None,
            "emotion_tags": normalize_tags(emotion_tags),
            "emotion_vector": parse_vector(emotion_vector),
            "match_patterns": match_patterns or [],
            "language": language or self.args.language,
            "ref_text": default_ref_text if ref_text is None else ref_text,
            "max_new_tokens": int(max_new_tokens or self.args.max_new_tokens),
        }
        with self.lock:
            self.jobs[job_id] = job
        write_json(job_cache_dir / "job.json", job)
        self.job_queue.put(job_id)
        return job

    def snapshot(self, job_id=None):
        with self.lock:
            if job_id:
                return dict(self.jobs[job_id])
            return {
                "ready": self.ready,
                "engine": "Qwen3-TTS",
                "uptime_seconds": round(time.time() - self.started_at, 2),
                "queued": self.job_queue.qsize(),
                "jobs": [dict(job) for job in self.jobs.values()],
            }

    def _set_job(self, job_id, **updates):
        with self.lock:
            job = self.jobs[job_id]
            job.update(updates)
            job["updated_at"] = time.time()
            current = dict(job)
        write_json(Path(current["cache_dir"]) / "job.json", current)
        return current

    def _resolve_character_folder(self, character_id=None, character_folder=None):
        return self.voice_refs.resolve_character_folder(character_id, character_folder)

    def _resolve_prompt_files(
        self,
        prompt_audio=None,
        prompt_audios=None,
        text="",
        character_folder=None,
        emotion_tags=None,
        emotion_vector=None,
        match_patterns=None,
    ):
        return self.voice_refs.resolve_prompt_files(
            prompt_audio=prompt_audio,
            prompt_audios=prompt_audios,
            text=text,
            character_folder=character_folder,
            emotion_tags=emotion_tags,
            emotion_vector=emotion_vector,
            match_patterns=match_patterns,
        )

    def _select_character_prompt_files(self, character_folder, text, emotion_tags=None, emotion_vector=None, match_patterns=None):
        return self.voice_refs.select_character_prompt_files(character_folder, text, emotion_tags, emotion_vector, match_patterns)

    def _prepare_prompt_audio(self, prompt_files):
        return self.voice_refs.prepare_prompt_audio(prompt_files)

    def _augment_short_prompt(self, primary):
        return self.voice_refs.augment_short_prompt(primary)

    def _find_related_prompt_candidates(self, primary):
        return self.voice_refs.find_related_prompt_candidates(primary)

    def _generator_loop(self):
        while True:
            job_id = self.job_queue.get()
            try:
                self._run_job(job_id)
            except Exception:
                self._set_job(job_id, status="error", error=traceback.format_exc())
            finally:
                self.job_queue.task_done()

    def _get_voice_prompt(self, prompt_audio, ref_text):
        key = (str(prompt_audio), ref_text or "", sha256_file(prompt_audio))
        if key not in self.voice_prompt_cache:
            self.voice_prompt_cache[key] = self.tts.create_voice_clone_prompt(
                ref_audio=str(prompt_audio),
                ref_text=ref_text,
                x_vector_only_mode=ref_text is None,
            )
        return self.voice_prompt_cache[key]

    def _run_job(self, job_id):
        self.load_model()
        job = self._set_job(job_id, status="running")
        job_cache_dir = Path(job["cache_dir"])
        prompt_audio = Path(job["prompt_audio"]).resolve()
        settings = {
            **self.settings,
            "language": job["language"],
            "ref_text": job["ref_text"],
            "max_new_tokens": job["max_new_tokens"],
        }
        voice_prompt = self._get_voice_prompt(prompt_audio, job["ref_text"])

        chunk_paths = []
        chunks = []
        for i, sentence in enumerate(job["sentences"], start=1):
            key = cache_key(sentence, prompt_audio, settings)
            sentence_wav = job_cache_dir / f"{i:03d}-{key[:16]}.wav"
            metadata_path = job_cache_dir / f"{i:03d}-{key[:16]}.json"
            reused = sentence_wav.exists()
            if not reused:
                wavs, sr = self.tts.generate_voice_clone(
                    text=sentence,
                    language=job["language"],
                    voice_clone_prompt=voice_prompt,
                    max_new_tokens=job["max_new_tokens"],
                )
                sf.write(str(sentence_wav), wavs[0], sr)

            chunk = {
                "index": i,
                "sentence": sentence,
                "wav": str(sentence_wav),
                "cache_key": key,
                "reused": reused,
                "duration_seconds": round(wav_duration(sentence_wav), 3),
                "language": job["language"],
            }
            write_json(metadata_path, {**chunk, "settings": settings, "prompt_audio": str(prompt_audio)})
            chunks.append(chunk)
            chunk_paths.append(sentence_wav)
            self._set_job(job_id, current=i, chunks=chunks)
            if job["play"]:
                self.play_queue.put(sentence_wav)

        out_path = Path(job["output"])
        concatenate_wavs(chunk_paths, out_path)
        self._set_job(job_id, status="done", current=len(chunk_paths), chunks=chunks, output=str(out_path))

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
                self._send_json(200, {"ok": True, "ready": worker.ready, "engine": "Qwen3-TTS"})
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
            try:
                payload = self._read_json()
                job = worker.submit(
                    text=payload.get("text", ""),
                    prompt_audio=payload.get("prompt_audio"),
                    prompt_audios=payload.get("prompt_audios"),
                    character_id=payload.get("character_id"),
                    session_id=payload.get("session_id"),
                    character_folder=payload.get("character_folder"),
                    emotion_tags=payload.get("emotion_tags"),
                    emotion_vector=payload.get("emotion_vector"),
                    match_patterns=payload.get("match_patterns"),
                    language=payload.get("language"),
                    ref_text=payload.get("ref_text"),
                    play=payload.get("play", True),
                    max_new_tokens=payload.get("max_new_tokens"),
                )
                self._send_json(202, job)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})

    return Handler


def main():
    args = parse_args()
    worker = QwenTTSWorker(args)
    worker.start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(worker))
    print(json.dumps({
        "event": "listening",
        "url": f"http://{args.host}:{args.port}",
        "engine": "Qwen3-TTS",
        "workdir": str(worker.workdir),
        "cache_dir": str(worker.cache_dir),
        "output_dir": str(worker.output_dir),
        "prompt_audio": str(worker.prompt_audio),
        "language": args.language,
    }, ensure_ascii=False))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
