from __future__ import annotations

from typing import Any

from app import main


def test_onnx_vits_character_owns_fixed_speaker(monkeypatch: Any) -> None:
    character = {
        "id": "fast_local",
        "tts_engine": "ONNX-VITS",
        "speech_language": "Chinese",
        "onnx_vits_speaker": "registry voice",
        "onnx_vits_speed": 1.15,
    }
    monkeypatch.setattr(main, "load_characters", lambda: ([character], None))

    resolved = main.resolved_worker_request(
        main.SpeakRequest(
            text="你好",
            character_id="fast_local",
            speaker="stale client voice",
            speaker_id=999,
            prompt_audio="stale.wav",
        )
    )

    assert resolved["worker_url"] == "http://127.0.0.1:8764"
    assert resolved["payload"]["speaker"] == "registry voice"
    assert "speaker_id" not in resolved["payload"]
    assert resolved["payload"]["speed"] == 1.15
    assert "prompt_audio" not in resolved["payload"]
