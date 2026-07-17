from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_cloud_voice_endpoints_are_gone() -> None:
    assert client.get("/api/voice-clone/requests").status_code == 410
    assert client.post("/api/voice-clone/enroll", json={"dry_run": True}).status_code == 410
    assert client.post("/api/audio/upload-public", json={"audio_path": "unused.wav"}).status_code == 410


def test_capabilities_only_advertise_local_models() -> None:
    payload = client.get("/api/tts-model-capabilities").json()
    assert set(payload["models"]) == {"onnx-vits-split", "qwen3-tts-local", "indextts2"}
    assert {model["provider"] for model in payload["models"].values()} == {"Local"}
