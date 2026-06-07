from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app import main


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


class FakeAsyncClient:
    posts: list[tuple[str, dict[str, Any]]] = []
    gets: list[str] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, json: dict[str, Any], **kwargs: Any) -> FakeResponse:
        self.posts.append((url, json))
        if url.endswith("/chat/completions"):
            return FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"emotion_mode":"vector","emotion_alpha":0.6,'
                                    '"emotion_vector":[0.5,0,0,0,0,0,0.1,0.2],'
                                    '"emotion_tags":["cheerful"],"ref_text":"hello"}'
                                )
                            }
                        }
                    ]
                }
            )
        if url.endswith("/customization"):
            return FakeResponse({"output": {"voice_id": "cosyvoice-v3-plus-user-1234"}, "request_id": "voice-request"})
        return FakeResponse({"id": "mock-job", "status": "queued", "text": json["text"], "output": "mock.wav"})

    async def get(self, url: str) -> FakeResponse:
        self.gets.append(url)
        if "/status/mock-job" in url:
            return FakeResponse({"id": "mock-job", "status": "done", "output": "mock.wav"})
        return FakeResponse({"engine": "MockTTS", "ready": True, "queued": 0, "url": url})


def client(tmp_path: Path, monkeypatch: Any) -> TestClient:
    project_dir = tmp_path / "project"
    example_dir = project_dir / "voice-references.example"
    example_dir.mkdir(parents=True)
    (example_dir / "reference-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "root": "voice-references",
                "characters": [
                    {
                        "id": "jp_companion",
                        "tts_engine": "Qwen3-TTS",
                        "speech_language": "Japanese",
                    },
                    {
                        "id": "zh_reader",
                        "tts_engine": "IndexTTS2",
                        "speech_language": "Chinese",
                    },
                    {
                        "id": "cloud_zh_voice",
                        "tts_engine": "Qwen-TTS-API",
                        "speech_language": "Chinese",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "DEFAULT_WORKSPACE", tmp_path)
    monkeypatch.setattr(main, "PROJECT_DIR", project_dir)
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(main, "LLM_BASE_URL", "")
    monkeypatch.setattr(main, "LLM_MODEL", "")
    FakeAsyncClient.posts = []
    FakeAsyncClient.gets = []
    return TestClient(main.app)


def test_config_and_characters_use_example_registry(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    config = test_client.get("/api/config").json()
    characters = test_client.get("/api/characters").json()

    assert config["default_worker_url"] == "http://127.0.0.1:8765"
    assert "127.0.0.1" in config["allowed_worker_hosts"]
    assert config["registry_exists"] is False
    assert {item["id"] for item in characters["characters"]} == {"jp_companion", "zh_reader", "cloud_zh_voice"}
    assert next(item for item in characters["characters"] if item["id"] == "zh_reader")["resolved_worker_url"].endswith(
        ":8766"
    )


def test_characters_prefer_parent_voice_reference_registry(tmp_path: Path, monkeypatch: Any) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    registry_dir = tmp_path / "voice-references"
    audio_dir = registry_dir / "characters" / "bb" / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "sample.wav").write_bytes(b"fake")
    (registry_dir / "reference-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "root": "voice-references",
                "characters": [
                    {
                        "id": "bb",
                        "tts_engine": "Qwen3-TTS",
                        "worker_url": "http://127.0.0.1:8765",
                        "speech_language": "Japanese",
                        "character_folder": "voice-references/characters/bb",
                        "fallback_prompt_audio": "voice-references/characters/bb/audio/sample.wav",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "DEFAULT_WORKSPACE", project_dir)
    monkeypatch.setattr(main, "PROJECT_DIR", project_dir)
    monkeypatch.setattr(main.httpx, "AsyncClient", FakeAsyncClient)

    test_client = TestClient(main.app)
    characters = test_client.get("/api/characters").json()
    route = test_client.post("/api/route/resolve", json={"character_id": "bb"}).json()

    assert characters["source"] == str(registry_dir / "reference-index.json")
    assert [item["id"] for item in characters["characters"]] == ["bb"]
    assert route["payload"]["prompt_audio"] == "voice-references/characters/bb/audio/sample.wav"


def test_speak_routes_from_character_defaults(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post("/api/speak", json={"text": "晚上好", "character_id": "zh_reader"})

    assert response.status_code == 200
    assert FakeAsyncClient.posts[0][0] == "http://127.0.0.1:8766/speak"
    assert FakeAsyncClient.posts[0][1]["language"] == "Chinese"
    assert FakeAsyncClient.posts[0][1]["character_id"] == "zh_reader"
    assert response.json()["request"]["hot_switch"] is True
    assert response.json()["request"]["switch_key"] == "character_id"
    assert response.json()["request"]["route_id"] == "zh_reader"


def test_route_resolve_hot_switches_by_character_id_without_worker_submit(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post("/api/route/resolve", json={"character_id": "cloud_zh_voice"})

    assert response.status_code == 200
    body = response.json()
    assert body["hot_switch"] is True
    assert body["switch_key"] == "character_id"
    assert body["route_id"] == "cloud_zh_voice"
    assert body["worker_url"] == "http://127.0.0.1:8767"
    assert body["payload"]["character_id"] == "cloud_zh_voice"
    assert body["payload"]["language"] == "Chinese"
    assert "text" not in body["payload"]
    assert FakeAsyncClient.posts == []


def test_qwen_tts_api_engine_routes_to_api_worker(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post("/api/speak", json={"text": "云端语音测试", "character_id": "cloud_zh_voice"})

    assert response.status_code == 200
    assert FakeAsyncClient.posts[0][0] == "http://127.0.0.1:8767/speak"
    assert FakeAsyncClient.posts[0][1]["language"] == "Chinese"
    assert FakeAsyncClient.posts[0][1]["character_id"] == "cloud_zh_voice"


def test_batch_preserves_order_and_worker_override(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post(
        "/api/batch",
        json={"lines": ["a", "", "b"], "character_id": "jp_companion", "worker_url": "http://127.0.0.1:9999"},
    )

    assert response.status_code == 200
    assert response.json()["submitted"] == 2
    assert [payload["text"] for _, payload in FakeAsyncClient.posts] == ["a", "b"]
    assert {url for url, _ in FakeAsyncClient.posts} == {"http://127.0.0.1:9999/speak"}


def test_worker_contract_fields_are_forwarded(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post(
        "/api/speak",
        json={
            "text": "hello",
            "character_id": "jp_companion",
            "emotion_mode": "vector",
            "emotion_alpha": 0.5,
            "emotion_text": "bright and gentle",
            "ref_text": "Hello, senpai.",
            "prompt_audio": "prompt.wav",
            "instructions": "Keep the delivery warm and conversational.",
            "send_instructions": False,
        },
    )

    assert response.status_code == 200
    payload = FakeAsyncClient.posts[0][1]
    assert payload["emotion_mode"] == "vector"
    assert payload["emotion_alpha"] == 0.5
    assert payload["emotion_text"] == "bright and gentle"
    assert payload["ref_text"] == "Hello, senpai."
    assert payload["prompt_audio"] == "prompt.wav"
    assert payload["instructions"] == "Keep the delivery warm and conversational."
    assert payload["send_instructions"] is False


def test_worker_job_status_proxy(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.get("/api/worker/status/mock-job?worker_url=http%3A%2F%2F127.0.0.1%3A8765")

    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert FakeAsyncClient.gets == ["http://127.0.0.1:8765/status/mock-job"]


def test_worker_url_rejects_unlisted_hosts(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post("/api/speak", json={"text": "nope", "worker_url": "http://example.com:8765"})

    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_parameter_inference_uses_local_heuristic_without_llm(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    response = test_client.post(
        "/api/infer-parameters",
        json={"text": "谢谢你，今天太好了", "character_id": "jp_companion"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "heuristic"
    assert body["parameters"]["language"] == "Japanese"
    assert body["parameters"]["emotion_mode"] == "vector"
    assert "cheerful" in body["parameters"]["emotion_tags"]


def test_parameter_inference_can_call_openai_compatible_llm(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    monkeypatch.setattr(main, "LLM_BASE_URL", "http://127.0.0.1:12345/v1")
    monkeypatch.setattr(main, "LLM_MODEL", "test-model")

    response = test_client.post(
        "/api/infer-parameters",
        json={"text": "hello", "character_id": "jp_companion", "provider": "llm"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "llm"
    assert body["parameters"]["emotion_alpha"] == 0.6
    assert FakeAsyncClient.posts[0][0] == "http://127.0.0.1:12345/v1/chat/completions"


def write_voice_clone_request(tmp_path: Path) -> Path:
    request_dir = tmp_path / "cache" / "voice-clone-requests"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "user_voice.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_voice_enrollment",
                "reference_audio_url": "https://example.test/ref.wav",
                "character": {
                    "id": "user_voice",
                    "display_name_zh": "我的声音",
                    "tts_engine": "Qwen-TTS-API",
                    "api_clone_target_model": "cosyvoice-v3-plus",
                    "api_clone_language_hint": "zh",
                },
            }
        ),
        encoding="utf-8",
    )
    return request_path


def test_voice_clone_requests_are_listed(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    request_path = write_voice_clone_request(tmp_path)

    response = test_client.get("/api/voice-clone/requests")

    assert response.status_code == 200
    body = response.json()
    assert body["requests"][0]["path"] == str(request_path.resolve())
    assert body["requests"][0]["character_id"] == "user_voice"


def test_voice_clone_enroll_dry_run_builds_dashscope_payload(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    write_voice_clone_request(tmp_path)

    response = test_client.post("/api/voice-clone/enroll", json={"character_id": "user_voice", "dry_run": True})

    assert response.status_code == 200
    body = response.json()
    assert body["payload"]["model"] == "voice-enrollment"
    assert body["payload"]["input"]["action"] == "create_voice"
    assert body["payload"]["input"]["target_model"] == "cosyvoice-v3-plus"
    assert body["payload"]["input"]["url"] == "https://example.test/ref.wav"
    assert body["payload"]["input"]["max_prompt_audio_length"] == 20


def test_voice_clone_enroll_writes_voice_id_to_registry(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    write_voice_clone_request(tmp_path)
    registry = tmp_path / "voice-references" / "reference-index.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"version":1,"root":"voice-references","characters":[]}', encoding="utf-8")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    response = test_client.post("/api/voice-clone/enroll", json={"character_id": "user_voice"})

    assert response.status_code == 200
    body = response.json()
    assert body["api_voice_id"] == "cosyvoice-v3-plus-user-1234"
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["characters"][0]["id"] == "user_voice"
    assert saved["characters"][0]["api_voice_id"] == "cosyvoice-v3-plus-user-1234"
