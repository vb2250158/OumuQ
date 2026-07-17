from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from app.workers.onnx_vits.engine import SynthesisResult
from app.workers.onnx_vits.server import OnnxVitsWorker, WorkerSettings, create_app


class FakeEngine:
    providers = ["FakeExecutionProvider"]
    sample_rate = 22050
    speakers = {"fast voice": 7}

    def synthesize(self, text: str, **kwargs):
        assert text == "你好"
        assert kwargs["speaker"] == "fast voice"
        return SynthesisResult(
            audio=np.zeros(2205, dtype=np.float32),
            sample_rate=22050,
            metadata={"engine": "ONNX-VITS", "duration_seconds": 0.1, "speaker_id": 7},
        )


def test_worker_queues_and_finishes_wav(tmp_path: Path) -> None:
    settings = WorkerSettings(
        model_dir=tmp_path,
        config_path=tmp_path / "config.json",
        output_root=tmp_path / "outputs",
        default_speaker="fast voice",
    )
    worker = OnnxVitsWorker(settings, engine_factory=lambda _: FakeEngine())
    app = create_app(worker)

    with TestClient(app) as client:
        health = client.get("/health").json()
        assert health["ok"] is True
        assert health["speaker_count"] == 1

        queued = client.post("/speak", json={"text": "你好", "language": "Chinese"}).json()
        assert queued["status"] == "queued"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            job = client.get(f"/status/{queued['id']}").json()
            if job["status"] in {"done", "error"}:
                break
            time.sleep(0.01)

        assert job["status"] == "done", job
        output = Path(job["output"])
        assert output.is_file()
        with wave.open(str(output), "rb") as handle:
            assert handle.getnframes() == 2205
        assert client.get("/speakers").json()["speakers"] == [{"name": "fast voice", "speaker_id": 7}]


def test_worker_reports_missing_configuration() -> None:
    settings = WorkerSettings(model_dir=None, config_path=None, output_root=Path.cwd())
    app = create_app(OnnxVitsWorker(settings))

    with TestClient(app) as client:
        assert client.get("/health").json()["ok"] is False
        response = client.post("/speak", json={"text": "hello"})
        assert response.status_code == 503
