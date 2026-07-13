from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main


def malformed_preview_wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(bytes(4800))
    data = bytearray(buffer.getvalue())
    data[4:8] = (0x7FFFFFFF).to_bytes(4, "little")
    data[40:44] = (0x7FFFFFFF).to_bytes(4, "little")
    return bytes(data)


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
            if json.get("model") == "qwen-voice-design":
                return FakeResponse(
                    {
                        "output": {
                            "voice": "qwen-designed-voice",
                            "target_model": json["input"]["target_model"],
                            "preview_audio": {
                                "data": base64.b64encode(malformed_preview_wav()).decode("ascii"),
                                "sample_rate": 24000,
                                "response_format": "wav",
                            },
                        },
                        "request_id": "voice-design-request",
                    }
                )
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
    monkeypatch.setattr(main, "GLOBAL_PLAYBACK_ENABLED", False)
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
    route = test_client.post(
        "/api/route/resolve",
        json={
            "character_id": "bb",
            "character_folder": "voice-references/characters/wrong-character",
        },
    ).json()

    assert characters["source"] == str(registry_dir / "reference-index.json")
    assert [item["id"] for item in characters["characters"]] == ["bb"]
    assert route["payload"]["character_folder"] == "voice-references/characters/bb"
    assert route["payload"]["prompt_audio_configured"] is True
    assert "prompt_audio" not in route["payload"]


def test_parameter_inference_reads_parent_registry_character_context(tmp_path: Path, monkeypatch: Any) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    character_dir = tmp_path / "voice-references" / "characters" / "tifira"
    character_dir.mkdir(parents=True)
    (character_dir / "README.md").write_text("TIFIRA_CONTEXT_MARKER 舰长，请交给我。", encoding="utf-8")
    (character_dir / "voice-index.json").write_text(
        json.dumps([{"id": "hello", "text": "舰长！", "language": "Chinese"}]), encoding="utf-8"
    )
    (tmp_path / "voice-references" / "reference-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "characters": [
                    {
                        "id": "tifira",
                        "speech_language": "Chinese",
                        "character_folder": "voice-references/characters/tifira",
                        "index_file": "voice-references/characters/tifira/voice-index.json",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "DEFAULT_WORKSPACE", project_dir)
    monkeypatch.setattr(main, "PROJECT_DIR", project_dir)
    test_client = TestClient(main.app)

    response = test_client.post(
        "/api/infer-parameters",
        json={"character_id": "tifira", "text": "你好", "provider": "heuristic", "include_prompt": True},
    )

    assert response.status_code == 200
    prompt = response.json()["prompt"]
    assert "TIFIRA_CONTEXT_MARKER" in prompt
    assert '"id": "hello"' in prompt


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
    assert body["payload"]["input"]["url"] == "<redacted-url>"
    assert body["payload"]["input"]["reference_audio_configured"] is True
    assert body["payload"]["input"]["max_prompt_audio_length"] == 20


def test_voice_clone_enroll_rejects_untrusted_endpoint(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    write_voice_clone_request(tmp_path)

    response = test_client.post(
        "/api/voice-clone/enroll",
        json={
            "character_id": "user_voice",
            "endpoint": "https://attacker.example/api/v1/services/audio/tts/customization",
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    assert "Invalid DashScope" in response.json()["detail"]
    assert FakeAsyncClient.posts == []


def test_voice_clone_request_path_must_stay_in_authorized_directory(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    outside = tmp_path / "outside.json"
    outside.write_text('{"character":{"id":"outside"}}', encoding="utf-8")

    response = test_client.post(
        "/api/voice-clone/enroll",
        json={"request_path": str(outside), "character_id": "outside", "dry_run": True},
    )

    assert response.status_code == 400
    assert "outside authorized request directories" in response.json()["detail"]


def test_voice_clone_request_character_must_match_api_character(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)
    request_path = write_voice_clone_request(tmp_path)

    response = test_client.post(
        "/api/voice-clone/enroll",
        json={
            "request_path": str(request_path),
            "character_id": "different_voice",
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]
    assert FakeAsyncClient.posts == []


def test_automatic_voice_clone_request_discovery_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)
    outside = tmp_path / "outside-symlink-target.json"
    outside.write_text('{"character":{"id":"symlink_escape"}}', encoding="utf-8")
    request_dir = tmp_path / "cache" / "voice-clone-requests"
    request_dir.mkdir(parents=True)
    link = request_dir / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"当前 Windows 环境不能创建测试符号链接：{type(exc).__name__}")

    listed = test_client.get("/api/voice-clone/requests").json()
    enrolled = test_client.post(
        "/api/voice-clone/enroll",
        json={"character_id": "symlink_escape", "dry_run": True},
    )

    assert all(item["character_id"] != "symlink_escape" for item in listed["requests"])
    assert enrolled.status_code == 404


def test_qwen_voice_enrollment_rejects_audio_outside_voice_references(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)
    request_dir = tmp_path / "cache" / "voice-clone-requests"
    request_dir.mkdir(parents=True)
    request_path = request_dir / "restricted_audio.json"
    request_path.write_text(
        '{"character":{"id":"restricted_audio","tts_engine":"Qwen-TTS-API"}}',
        encoding="utf-8",
    )
    outside_audio = tmp_path / "private.wav"
    outside_audio.write_bytes(b"not-authorized-audio")

    response = test_client.post(
        "/api/voice-clone/enroll",
        json={
            "request_path": str(request_path),
            "character_id": "restricted_audio",
            "enrollment_model": "qwen-voice-enrollment",
            "target_model": "qwen3-tts-vc-2026-01-22",
            "reference_audio_path": str(outside_audio),
            "dry_run": True,
        },
    )

    assert response.status_code == 400
    assert "outside authorized audio directories" in response.json()["detail"]


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
    assert body["api_voice_configured"] is True
    assert "api_voice_id" not in body
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["characters"][0]["id"] == "user_voice"
    assert saved["characters"][0]["api_voice_id"] == "cosyvoice-v3-plus-user-1234"


def write_voice_design_request(tmp_path: Path) -> Path:
    request_dir = tmp_path / "cache" / "voice-clone-requests"
    request_dir.mkdir(parents=True, exist_ok=True)
    request_path = request_dir / "designed_voice.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "pending_voice_design",
                "character": {
                    "id": "designed_voice",
                    "name": "Designed Voice",
                    "display_name_zh": "设计音色",
                    "character_folder": "voice-references/characters/designed_voice",
                    "index_file": "voice-references/characters/designed_voice/voice-index.json",
                    "tts_engine": "Qwen-TTS-API",
                    "worker_url": "http://127.0.0.1:8767",
                    "speech_language": "Chinese",
                    "visible_language": "Chinese",
                    "style_summary": "Original designed voice.",
                    "style_summary_zh": "原创设计音色。",
                    "tts_provider": "Alibaba Cloud Model Studio (DashScope)",
                    "api_voice_creation_method": "voice_design",
                    "api_enrollment_model": "qwen-voice-design",
                    "api_target_model": "qwen3-tts-vd-2026-01-26",
                    "api_clone_target_model": "qwen3-tts-vd-2026-01-26",
                    "api_voice_design_language": "zh",
                    "api_clone_language_hint": "zh",
                    "api_voice_prompt": "年轻、明亮、可靠的女性声音。",
                    "api_voice_preview_text": "今天的任务交给我吧。",
                    "voice_mode": "cloud-voice-design",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return request_path


def test_qwen_voice_design_dry_run_uses_official_payload(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    request_path = write_voice_design_request(tmp_path)

    response = test_client.post(
        "/api/voice-clone/enroll",
        json={"request_path": str(request_path), "character_id": "designed_voice", "dry_run": True},
    )

    assert response.status_code == 200
    payload = response.json()["payload"]
    assert payload["model"] == "qwen-voice-design"
    assert payload["input"] == {
        "action": "create",
        "target_model": "qwen3-tts-vd-2026-01-26",
        "preferred_name": "designed_voice",
        "voice_prompt": "年轻、明亮、可靠的女性声音。",
        "preview_text": "今天的任务交给我吧。",
        "language": "zh",
    }
    assert payload["parameters"] == {"sample_rate": 24000, "response_format": "wav"}


def test_qwen_voice_design_saves_voice_and_redacted_preview(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    request_path = write_voice_design_request(tmp_path)
    registry = tmp_path / "voice-references" / "reference-index.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"version":1,"root":"voice-references","characters":[]}', encoding="utf-8")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")

    response = test_client.post(
        "/api/voice-clone/enroll",
        json={"request_path": str(request_path), "character_id": "designed_voice"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["api_voice_configured"] is True
    assert "api_voice_id" not in body
    preview_path = Path(body["preview_audio_path"])
    with wave.open(str(preview_path), "rb") as preview_wav:
        assert preview_wav.getframerate() == 24000
        assert preview_wav.getnchannels() == 1
        assert preview_wav.getnframes() == 2400
    assert int.from_bytes(preview_path.read_bytes()[4:8], "little") == preview_path.stat().st_size - 8
    assert body["dashscope_response"]["output"]["preview_audio"]["data"] == "<redacted-data>"
    assert body["dashscope_response"]["output"]["voice_configured"] is True
    assert "voice" not in body["dashscope_response"]["output"]
    saved = json.loads(registry.read_text(encoding="utf-8"))
    assert saved["characters"][0]["api_voice_id"] == "qwen-designed-voice"
    pending = json.loads(request_path.read_text(encoding="utf-8"))
    assert pending["dashscope_response"]["output"]["preview_audio"]["data"] == "<redacted-data>"


def test_voice_enrollment_persists_actual_overridden_models_for_later_routing(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)
    request_path = write_voice_design_request(tmp_path)
    registry = tmp_path / "voice-references" / "reference-index.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"version":1,"root":"voice-references","characters":[]}', encoding="utf-8")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    actual_target = "qwen3-tts-vd-override-fixture"

    enrolled = test_client.post(
        "/api/voice-clone/enroll",
        json={
            "request_path": str(request_path),
            "character_id": "designed_voice",
            "target_model": actual_target,
        },
    )
    route = test_client.post(
        "/api/route/resolve",
        json={"character_id": "designed_voice", "play": False},
    )

    assert enrolled.status_code == 200
    assert route.status_code == 200
    saved = json.loads(registry.read_text(encoding="utf-8"))["characters"][0]
    assert saved["api_target_model"] == actual_target
    assert saved["api_clone_target_model"] == actual_target
    assert saved["api_enrollment_model"] == "qwen-voice-design"
    assert saved["api_voice_creation_method"] == "voice_design"
    assert route.json()["payload"]["model"] == actual_target


def configure_two_cloud_characters(tmp_path: Path) -> None:
    registry_path = tmp_path / "project" / "voice-references.example" / "reference-index.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    cloud_zh = next(item for item in registry["characters"] if item["id"] == "cloud_zh_voice")
    cloud_zh.update(
        {
            "api_voice_id": "voice-zh",
            "api_clone_target_model": "cosyvoice-zh",
            "api_voice_instructions": "中文会话音色。",
            "worker_url": "http://127.0.0.1:8767",
        }
    )
    registry["characters"].append(
        {
            "id": "cloud_jp_voice",
            "tts_engine": "Qwen-TTS-API",
            "speech_language": "Japanese",
            "api_voice_id": "voice-jp",
            "api_clone_target_model": "cosyvoice-jp",
            "api_voice_instructions": "日本語の会話音声。",
            "worker_url": "http://127.0.0.1:8767",
        }
    )
    registry_path.write_text(json.dumps(registry), encoding="utf-8")


def test_characters_redact_private_cloud_voice_fields(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)
    configure_two_cloud_characters(tmp_path)

    response = test_client.get("/api/characters")

    assert response.status_code == 200
    cloud = next(item for item in response.json()["characters"] if item["id"] == "cloud_zh_voice")
    assert cloud["api_voice_configured"] is True
    assert "api_voice_id" not in cloud
    assert "api_clone_audio_url" not in cloud
    assert "api_clone_audio_path" not in cloud
    assert "fallback_prompt_audio" not in cloud


def test_interleaved_sessions_keep_character_and_cloud_voice_isolated(tmp_path: Path, monkeypatch: Any) -> None:
    client(tmp_path, monkeypatch)
    configure_two_cloud_characters(tmp_path)

    async def submit_interleaved() -> list[dict[str, Any]]:
        requests = [
            main.SpeakRequest(text="你好-A1", session_id="session-a", character_id="cloud_zh_voice", play=False),
            main.SpeakRequest(
                text="こんにちは-B1",
                session_id="session-b",
                character_id="cloud_jp_voice",
                play=False,
                model="cosyvoice-zh",
                voice="voice-zh",
                voice_id="voice-zh",
            ),
            main.SpeakRequest(text="再见-A2", session_id="session-a", character_id="cloud_zh_voice", play=False),
        ]
        return await asyncio.gather(*(main.speak(request) for request in requests))

    results = asyncio.run(submit_interleaved())
    resolved = [
        (
            item["request"]["session_id"],
            item["request"]["route_id"],
            item["request"]["worker_url"],
            item["request"]["payload"]["voice_configured"],
            item["request"]["payload"]["language"],
        )
        for item in results
    ]

    assert resolved == [
        ("session-a", "cloud_zh_voice", "http://127.0.0.1:8767", True, "Chinese"),
        ("session-b", "cloud_jp_voice", "http://127.0.0.1:8767", True, "Japanese"),
        ("session-a", "cloud_zh_voice", "http://127.0.0.1:8767", True, "Chinese"),
    ]
    downstream_payloads = [payload for _, payload in FakeAsyncClient.posts]
    assert [payload["character_id"] for payload in downstream_payloads] == [
        "cloud_zh_voice",
        "cloud_jp_voice",
        "cloud_zh_voice",
    ]
    assert [payload["voice_id"] for payload in downstream_payloads] == ["voice-zh", "voice-jp", "voice-zh"]
    assert [payload["model"] for payload in downstream_payloads] == [
        "cosyvoice-zh",
        "cosyvoice-jp",
        "cosyvoice-zh",
    ]
    assert all("session_id" not in payload for payload in downstream_payloads)


def test_public_routes_runs_and_worker_status_never_expose_voice_credentials(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)
    configure_two_cloud_characters(tmp_path)

    async def response_with_private_voice(
        self: FakeAsyncClient, url: str, json: dict[str, Any], **kwargs: Any
    ) -> FakeResponse:
        self.posts.append((url, json))
        return FakeResponse(
            {
                "id": "private-job",
                "status": "done",
                "text": json["text"],
                "output": "safe.wav",
                "voice": "provider-private-voice",
                "voice_id": "provider-private-voice-id",
                "prompt_audio_files": ["C:/private/reference-one.wav"],
                "error": "provider rejected provider-private-voice-id at https://provider.example/private",
            }
        )

    async def status_with_private_voice(self: FakeAsyncClient, url: str) -> FakeResponse:
        self.gets.append(url)
        return FakeResponse(
            {
                "id": "private-job",
                "status": "done",
                "output": "safe.wav",
                "voice": "provider-private-voice",
                "voice_id": "provider-private-voice-id",
                "prompt_audio_files": ["C:/private/reference-two.wav"],
                "message": "provider-private-voice failed with data:audio/wav;base64,private",
            }
        )

    monkeypatch.setattr(FakeAsyncClient, "post", response_with_private_voice)
    route = test_client.post("/api/route/resolve", json={"character_id": "cloud_zh_voice"}).json()
    speak = test_client.post(
        "/api/speak",
        json={"text": "安全边界", "character_id": "cloud_zh_voice", "play": False},
    ).json()
    monkeypatch.setattr(FakeAsyncClient, "get", status_with_private_voice)
    status = test_client.get(
        "/api/worker/status/private-job?worker_url=http%3A%2F%2F127.0.0.1%3A8767"
    ).json()
    runs = test_client.get("/api/runs?character_id=cloud_zh_voice").json()

    for public_value in (route, speak, status, runs):
        rendered = json.dumps(public_value, ensure_ascii=False)
        assert "provider-private-voice" not in rendered
        assert "provider.example" not in rendered
        assert "base64,private" not in rendered
        assert "reference-one.wav" not in rendered
        assert "reference-two.wav" not in rendered
        assert '"voice_id"' not in rendered
        assert '"api_voice_id"' not in rendered
    assert route["payload"]["voice_configured"] is True
    assert speak["request"]["payload"]["voice_configured"] is True
    assert speak["worker_response"]["voice_configured"] is True
    assert speak["worker_response"]["prompt_audio_configured"] is True
    assert speak["worker_response"]["prompt_audio_count"] == 1
    assert status["voice_configured"] is True
    assert status["prompt_audio_configured"] is True


def test_reserved_playback_sequence_is_failed_when_logging_raises(
    tmp_path: Path, monkeypatch: Any
) -> None:
    test_client = client(tmp_path, monkeypatch)
    coordinator = main.GlobalPlaybackCoordinator(start_thread=False)
    monkeypatch.setattr(main, "GLOBAL_PLAYBACK_ENABLED", True)
    monkeypatch.setattr(main, "PLAYBACK_COORDINATOR", coordinator)

    def broken_write_json(path: Path, data: Any) -> None:
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(main, "write_json", broken_write_json)
    response = test_client.post(
        "/api/speak",
        json={"text": "first", "character_id": "zh_reader", "play": True},
    )

    assert response.status_code == 502
    records = {record["sequence"]: record for record in coordinator.snapshot()["records"]}
    assert records[1]["status"] == "generation_error"

    second = coordinator.reserve(session_id="later", character_id="zh_reader", worker_url="worker")
    coordinator.mark_ready(second, tmp_path / "later.wav")
    records = {record["sequence"]: record for record in coordinator.snapshot()["records"]}
    assert records[second]["status"] == "queued_playback"


def test_playback_monitor_recovers_after_transient_status_failure(
    tmp_path: Path, monkeypatch: Any
) -> None:
    coordinator = main.GlobalPlaybackCoordinator(start_thread=False)
    sequence = coordinator.reserve(session_id="session", character_id="zh_reader", worker_url="worker")
    calls = 0

    class FlakyStatusClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            return None

        async def __aenter__(self) -> "FlakyStatusClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.ConnectError("temporary", request=httpx.Request("GET", url))
            return FakeResponse(
                {
                    "id": "job-transient",
                    "status": "done",
                    "output": str(tmp_path / "generated.wav"),
                }
            )

    monkeypatch.setattr(main, "PLAYBACK_COORDINATOR", coordinator)
    monkeypatch.setattr(main.httpx, "AsyncClient", FlakyStatusClient)
    monkeypatch.setattr(main, "GLOBAL_PLAYBACK_POLL_SECONDS", 0.001)
    monkeypatch.setattr(main, "GLOBAL_PLAYBACK_STATUS_ERROR_GRACE_SECONDS", 1.0)

    asyncio.run(main.monitor_worker_for_playback(sequence, "http://127.0.0.1:8765", "job-transient"))

    records = {record["sequence"]: record for record in coordinator.snapshot()["records"]}
    assert calls == 2
    assert records[sequence]["status"] == "queued_playback"


def test_session_id_requires_explicit_character_and_is_validated(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    missing_character = test_client.post("/api/speak", json={"text": "hello", "session_id": "session-a"})
    invalid_id = test_client.post(
        "/api/speak",
        json={"text": "hello", "session_id": "contains spaces", "character_id": "jp_companion"},
    )
    too_long = test_client.post(
        "/api/speak",
        json={"text": "hello", "session_id": "a" * 129, "character_id": "jp_companion"},
    )
    non_canonical_character = test_client.post(
        "/api/route/resolve",
        json={"character_id": "Cloud_Character"},
    )

    assert missing_character.status_code == 400
    assert invalid_id.status_code == 422
    assert too_long.status_code == 422
    assert non_canonical_character.status_code == 422


def test_batch_and_inference_echo_session_without_forwarding_it(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    batch_response = test_client.post(
        "/api/batch",
        json={
            "lines": ["第一句", "第二句"],
            "session_id": "session-a",
            "character_id": "zh_reader",
            "play": False,
        },
    )
    inference_response = test_client.post(
        "/api/infer-parameters",
        json={
            "text": "谢谢你",
            "session_id": "session-a",
            "character_id": "zh_reader",
            "provider": "heuristic",
        },
    )

    assert batch_response.status_code == 200
    assert [job["request"]["session_id"] for job in batch_response.json()["jobs"]] == ["session-a", "session-a"]
    assert all("session_id" not in payload for _, payload in FakeAsyncClient.posts)
    assert inference_response.status_code == 200
    assert inference_response.json()["session_id"] == "session-a"


def test_runs_filter_by_session_before_limit_and_by_character(tmp_path: Path, monkeypatch: Any) -> None:
    test_client = client(tmp_path, monkeypatch)

    run_a = test_client.post(
        "/api/speak",
        json={"text": "older-a", "session_id": "session-a", "character_id": "jp_companion", "play": False},
    ).json()
    run_b = test_client.post(
        "/api/speak",
        json={"text": "newer-b", "session_id": "session-b", "character_id": "zh_reader", "play": False},
    ).json()
    os.utime(Path(run_a["run_dir"]) / "response.json", (100, 100))
    os.utime(Path(run_b["run_dir"]) / "response.json", (200, 200))

    filtered_a = test_client.get("/api/runs?limit=1&session_id=session-a").json()
    filtered_b = test_client.get("/api/runs?limit=1&session_id=session-b&character_id=zh_reader").json()
    wrong_character = test_client.get("/api/runs?session_id=session-b&character_id=jp_companion").json()

    assert [item["request"]["session_id"] for item in filtered_a["runs"]] == ["session-a"]
    assert filtered_a["runs"][0]["request"]["route_id"] == "jp_companion"
    assert [item["request"]["session_id"] for item in filtered_b["runs"]] == ["session-b"]
    assert filtered_b["runs"][0]["request"]["route_id"] == "zh_reader"
    assert wrong_character["runs"] == []
