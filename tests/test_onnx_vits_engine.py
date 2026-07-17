from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.workers.onnx_vits.engine import OnnxVitsEngine, duration_path, write_pcm16_wav
from app.workers.onnx_vits.frontend import CjkeTextFrontend


class Input:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeSession:
    def __init__(self, name: str, inputs: set[str]) -> None:
        self.name = name
        self.inputs = inputs

    def get_inputs(self) -> list[Input]:
        return [Input(name) for name in self.inputs]

    def get_providers(self) -> list[str]:
        return ["FakeExecutionProvider"]

    def run(self, _: Any, values: dict[str, np.ndarray]) -> list[np.ndarray]:
        if self.name == "enc_p":
            token_count = values["x"].shape[1]
            xout = np.zeros((1, 192, token_count), dtype=np.float32)
            mean = np.zeros((1, 192, token_count), dtype=np.float32)
            logs = np.full((1, 192, token_count), -8.0, dtype=np.float32)
            mask = np.ones((1, 1, token_count), dtype=np.float32)
            return [xout, mean, logs, mask]
        if self.name == "emb_g":
            return [np.zeros((1, 256), dtype=np.float32)]
        if self.name == "dp":
            return [np.zeros((1, 1, values["x"].shape[2]), dtype=np.float32)]
        if self.name == "flow":
            return [values["z_p"]]
        if self.name == "dec":
            return [np.tanh(values["z_in"].mean(axis=1, keepdims=True))]
        raise AssertionError(self.name)


def fake_sessions() -> dict[str, FakeSession]:
    return {
        "enc_p": FakeSession("enc_p", {"x", "x_lengths"}),
        "emb_g": FakeSession("emb_g", {"sid"}),
        "dp": FakeSession("dp", {"x", "x_mask", "g"}),
        "flow": FakeSession("flow", {"z_p", "y_mask", "g"}),
        "dec": FakeSession("dec", {"z_in", "g"}),
    }


def write_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "symbols": ["_", ".", "a"],
                "speakers": {"fast voice": 7},
                "data": {
                    "sampling_rate": 22050,
                    "hop_length": 256,
                    "n_speakers": 8,
                    "text_cleaners": ["cjke_cleaners2"],
                    "add_blank": False,
                },
            }
        ),
        encoding="utf-8",
    )


def test_duration_path_is_monotonic() -> None:
    path = duration_path(np.asarray([[[2, 0, 3]]]))
    assert path.shape == (1, 1, 5, 3)
    assert path[0, 0].argmax(axis=1).tolist() == [0, 0, 2, 2, 2]


def test_split_graph_engine_runs_with_cached_sessions(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    write_config(config)
    frontend = CjkeTextFrontend(["_", ".", "a"], add_blank=False, cleaner=lambda _: "a.")
    engine = OnnxVitsEngine(
        tmp_path,
        config,
        sessions=fake_sessions(),
        frontend=frontend,
        max_seconds=10,
    )

    result = engine.synthesize("hello", speaker="FAST VOICE", language="English", seed=3)

    assert result.audio.shape == (2,)
    assert result.metadata["speaker_id"] == 7
    assert result.metadata["providers"] == ["FakeExecutionProvider"]
    assert result.metadata["latent_frames"] == 2


def test_character_speaker_name_and_id_must_agree(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    write_config(config)
    engine = OnnxVitsEngine(
        tmp_path,
        config,
        sessions=fake_sessions(),
        frontend=CjkeTextFrontend(["_", ".", "a"], add_blank=False, cleaner=lambda _: "a"),
    )

    with pytest.raises(ValueError, match="not requested speaker_id"):
        engine.resolve_speaker("fast voice", 6)


def test_wav_writer_creates_pcm16_audio(tmp_path: Path) -> None:
    output = write_pcm16_wav(tmp_path / "result.wav", np.asarray([-1.0, 0.0, 1.0]), 22050)

    with wave.open(str(output), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == 22050
        assert handle.getnframes() == 3
