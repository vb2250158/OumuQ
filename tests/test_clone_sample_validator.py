from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
import wave
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills" / "oumuq-tts-character-creator" / "scripts" / "validate_clone_sample.py"


def write_wav(path: Path, seconds: float = 12.0) -> None:
    rate = 16000
    frames = [int(12000 * math.sin(2 * math.pi * 220 * index / rate)) for index in range(int(rate * seconds))]
    path.parent.mkdir(parents=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack(f"<{len(frames)}h", *frames))


def run_validator(
    tmp_path: Path,
    *,
    components: list[str],
    transcript: str = "这是逐字核验后的中文参考文本。",
    language: str = "zh",
) -> subprocess.CompletedProcess[str]:
    audio = tmp_path / "voice-references" / "characters" / "demo" / "audio" / "sample.wav"
    write_wav(audio)
    entry = {
        "api_voice_creation_method": "voice_cloning",
        "api_enrollment_model": "qwen-voice-enrollment",
        "api_clone_audio_path": "voice-references/characters/demo/audio/sample.wav",
        "api_clone_reference_text": transcript,
        "api_clone_reference_language": language,
        "reference_audio_source": {
            "language": language,
            "continuous_recording": True,
            "component_files": components,
            "transcript_verified": True,
            "transcript_verification": "manual-listening-plus-asr-alignment",
        },
    }
    entry_file = tmp_path / "entry.json"
    entry_file.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--workspace",
            str(tmp_path),
            "--entry-file",
            str(entry_file),
            "--expected-language",
            "zh",
        ],
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def test_accepts_single_continuous_verified_chinese_sample(tmp_path: Path) -> None:
    result = run_validator(tmp_path, components=["sample.wav"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_rejects_composite_sample(tmp_path: Path) -> None:
    result = run_validator(tmp_path, components=["one.wav", "two.wav"])
    assert result.returncode == 1
    assert "composite samples" in result.stdout


def test_rejects_missing_verified_transcript(tmp_path: Path) -> None:
    result = run_validator(tmp_path, components=["sample.wav"], transcript="")
    assert result.returncode == 1
    assert "verbatim transcript" in result.stdout


def test_rejects_foreign_language_for_chinese_clone(tmp_path: Path) -> None:
    result = run_validator(tmp_path, components=["sample.wav"], language="ja")
    assert result.returncode == 1
    assert "reference language must be zh" in result.stdout
