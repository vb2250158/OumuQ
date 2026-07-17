from __future__ import annotations

import argparse
import audioop
import json
import math
import sys
import wave
from pathlib import Path


def normalized_language(value: object) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    return {"chinese": "zh", "zh-cn": "zh", "cmn": "zh"}.get(text, text)


def validate(workspace: Path, entry_file: Path, expected_language: str) -> dict[str, object]:
    errors: list[str] = []
    entry = json.loads(entry_file.read_text(encoding="utf-8-sig"))
    source = entry.get("reference_audio_source")
    if not isinstance(source, dict):
        source = {}
        errors.append("reference_audio_source must be an object")

    if entry.get("api_voice_creation_method") != "voice_cloning":
        errors.append("api_voice_creation_method must be voice_cloning")
    if entry.get("api_enrollment_model") != "qwen-voice-enrollment":
        errors.append("api_enrollment_model must be qwen-voice-enrollment")

    expected = normalized_language(expected_language)
    configured = normalized_language(
        entry.get("api_clone_reference_language") or entry.get("api_clone_language_hint")
    )
    source_language = normalized_language(source.get("language"))
    if configured != expected or source_language != expected:
        errors.append(f"reference language must be {expected} in both entry and source metadata")

    transcript = str(entry.get("api_clone_reference_text") or "").strip()
    if not transcript:
        errors.append("api_clone_reference_text must contain a verified verbatim transcript")
    if source.get("transcript_verified") is not True:
        errors.append("reference_audio_source.transcript_verified must be true")
    if not str(source.get("transcript_verification") or "").strip():
        errors.append("reference_audio_source.transcript_verification must describe the verification method")
    if source.get("continuous_recording") is not True:
        errors.append("reference_audio_source.continuous_recording must be true")
    components = source.get("component_files")
    if isinstance(components, list) and len(components) > 1:
        errors.append("composite samples from multiple clips are not allowed")

    path_value = str(entry.get("api_clone_audio_path") or "").strip()
    audio_path = (workspace / path_value).resolve() if path_value else None
    allowed_root = (workspace / "voice-references").resolve()
    metrics: dict[str, object] = {}
    if not audio_path or not audio_path.is_file() or allowed_root not in audio_path.parents:
        errors.append("api_clone_audio_path must resolve to a file inside voice-references")
    elif audio_path.suffix.lower() != ".wav":
        errors.append("strict clone validation currently requires WAV")
    else:
        with wave.open(str(audio_path), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.getnframes()
            raw = wav.readframes(frames)
        duration = frames / rate if rate else 0.0
        full_scale = float(2 ** (width * 8 - 1) - 1)
        peak = audioop.max(raw, width) if raw else 0
        peak_dbfs = 20 * math.log10(max(peak, 1) / full_scale)
        window_bytes = max(1, int(rate * 0.02)) * channels * width
        windows = [raw[index : index + window_bytes] for index in range(0, len(raw), window_bytes)]
        silent = sum(
            1 for chunk in windows if chunk and audioop.rms(chunk, width) / full_scale < 10 ** (-45 / 20)
        )
        silence_ratio = silent / len(windows) if windows else 1.0
        metrics = {
            "duration_seconds": round(duration, 3),
            "sample_rate": rate,
            "channels": channels,
            "sample_width_bits": width * 8,
            "peak_dbfs": round(peak_dbfs, 2),
            "silence_ratio": round(silence_ratio, 4),
        }
        if not 10.0 <= duration <= 20.0:
            errors.append("reference duration must be between 10 and 20 seconds")
        if channels != 1:
            errors.append("reference audio must be mono")
        if rate < 16000:
            errors.append("reference sample rate must be at least 16 kHz")
        if peak_dbfs > -0.5:
            errors.append("reference audio is too close to clipping; peak must be at most -0.5 dBFS")
        if silence_ratio > 0.35:
            errors.append("reference audio contains more than 35% near-silence")

    return {"ok": not errors, "errors": errors, "metrics": metrics}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a production Qwen voice-clone reference sample.")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--entry-file", required=True, type=Path)
    parser.add_argument("--expected-language", required=True)
    args = parser.parse_args()
    result = validate(args.workspace.resolve(), args.entry_file.resolve(), args.expected_language)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
