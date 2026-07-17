from __future__ import annotations

import base64
import importlib.util
import io
import json
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "qwen-tts-api"
    / "scripts"
    / "qwen_tts_api_worker.py"
)
SPEC = importlib.util.spec_from_file_location("oumuq_qwen_tts_api_worker", SCRIPT_PATH)
assert SPEC and SPEC.loader
worker_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker_module)


def write_registry(workdir: Path) -> None:
    registry = {
        "version": 1,
        "characters": [
            {
                "id": "cloud_a",
                "tts_engine": "Qwen-TTS-API",
                "speech_language": "Chinese",
                "api_clone_language_hint": "zh",
                "api_target_model": "model-a",
                "api_clone_target_model": "legacy-model-a",
                "api_voice_id": "voice-a",
                "api_voice_instructions": "角色 A 指令",
                "send_instructions_by_default": True,
            },
            {
                "id": "cloud_b",
                "tts_engine": "Qwen-TTS-API",
                "speech_language": "Japanese",
                "api_clone_language_hint": "ja",
                "api_clone_target_model": "model-b",
                "api_voice_id": "voice-b",
                "api_voice_instructions": "角色 B 指令",
                "send_instructions_by_default": False,
            },
            {
                "id": "cloud_missing",
                "tts_engine": "Qwen-TTS-API",
                "speech_language": "Chinese",
            },
            {
                "id": "cloud_clone",
                "tts_engine": "Qwen-TTS-API",
                "speech_language": "Chinese",
                "api_clone_language_hint": "zh",
                "api_clone_target_model": "model-clone",
                "api_clone_audio_url": "https://example.test/reference.wav",
                "api_clone_prefix": "cloud_clone",
            },
            {
                "id": "cloud_design",
                "tts_engine": "Qwen-TTS-API",
                "tts_provider": "Alibaba Cloud Model Studio (DashScope)",
                "speech_language": "Chinese",
                "api_clone_language_hint": "zh",
                "api_voice_design_language": "zh",
                "api_voice_creation_method": "voice_design",
                "api_enrollment_model": "qwen-voice-design",
                "api_target_model": "qwen3-tts-vd-2026-01-26",
                "api_clone_target_model": "qwen3-tts-vd-2026-01-26",
                "api_voice_prompt": "年轻、明亮、可靠的女性声音。",
                "api_voice_preview_text": "今天的任务交给我吧。",
                "voice_mode": "cloud-voice-design",
            },
        ],
    }
    target = workdir / "voice-references" / "reference-index.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(registry), encoding="utf-8")


def worker_args(workdir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        host="127.0.0.1",
        port=0,
        workdir=str(workdir),
        cache_dir=".cache",
        output_dir="outputs",
        base_url="https://dashscope.aliyuncs.com",
        api_key_env="DASHSCOPE_API_KEY",
        character_id="cloud_a",
        model="generic-model",
        voice="GenericVoice",
        voice_id=None,
        language="Chinese",
        instructions=None,
        send_instructions=False,
        optimize_instructions=False,
        clone_audio_url=None,
        clone_prefix="default_clone",
        clone_target_model="generic-clone-model",
        clone_language_hint="zh",
        max_prompt_audio_length=15,
        enable_preprocess=False,
        no_play=True,
        app_name="OumuQ Test Worker",
    )


def create_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    write_registry(tmp_path)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    return worker_module.QwenTTSApiWorker(worker_args(tmp_path))


def test_interleaved_characters_get_independent_job_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)

    jobs = [
        worker.submit("你好", character_id="cloud_a", session_id="session-a", play=False),
        worker.submit("こんにちは", character_id="cloud_b", session_id="session-b", play=False),
        worker.submit("再见", character_id="cloud_a", session_id="session-a", play=False),
    ]

    assert [
        (
            job["character_id"],
            job["session_id"],
            job["voice"],
            job["model"],
            job["language"],
            job["language_hint"],
            job["instructions"],
            job["send_instructions"],
        )
        for job in jobs
    ] == [
        ("cloud_a", "session-a", "voice-a", "model-a", "Chinese", "zh", "角色 A 指令", True),
        ("cloud_b", "session-b", "voice-b", "model-b", "Japanese", "ja", "角色 B 指令", False),
        ("cloud_a", "session-a", "voice-a", "model-a", "Chinese", "zh", "角色 A 指令", True),
    ]
    status = worker.snapshot()
    assert status["dynamic_character_routing"] is True
    assert status["default_character_id"] == "cloud_a"
    assert status["model"] == "model-a"
    assert status["voice_configured"] is True
    assert "voice" not in status
    assert all("voice" not in item for item in status["jobs"])
    assert all(item["voice_configured"] is True for item in status["jobs"])
    serialized = json.dumps(status)
    assert "voice-a" not in serialized
    assert "voice-b" not in serialized
    for job in jobs:
        persisted = json.loads((Path(job["cache_dir"]) / "job.json").read_text(encoding="utf-8"))
        persisted_text = json.dumps(persisted, ensure_ascii=False)
        assert persisted["voice_configured"] is True
        assert "voice" not in persisted
        assert "voice_id" not in persisted_text
        assert job["voice"] not in persisted_text


def test_explicit_character_never_enrolls_or_falls_back_to_startup_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    enrollment_calls = 0

    def unexpected_enrollment(*args, **kwargs):
        nonlocal enrollment_calls
        enrollment_calls += 1
        return "must-not-be-used"

    monkeypatch.setattr(worker, "_ensure_voice_id", unexpected_enrollment)
    for character_id in ("cloud_missing", "cloud_clone", "cloud_design"):
        with pytest.raises(ValueError, match="Register it explicitly through OumuQ"):
            worker.submit("不能串音", character_id=character_id, play=False)

    assert enrollment_calls == 0
    with pytest.raises(ValueError, match="not found"):
        worker.submit("未知角色", character_id="does_not_exist", play=False)


def test_http_speak_accepts_character_id_per_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    server = worker_module.ThreadingHTTPServer(("127.0.0.1", 0), worker_module.make_handler(worker))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "text": "こんにちは",
                "character_id": "cloud_b",
                "session_id": "session-b",
                "voice": "voice-a",
                "voice_id": "voice-a",
                "model": "model-a",
                "play": False,
            }
        ).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{server.server_port}/speak",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            job = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert job["character_id"] == "cloud_b"
    assert job["session_id"] == "session-b"
    assert job["voice_configured"] is True
    assert "voice" not in job
    assert "voice-b" not in json.dumps(job)
    assert job["model"] == "model-b"
    assert job["language_hint"] == "ja"

    internal_job = worker.jobs[job["id"]]
    assert internal_job["voice"] == "voice-b"
    assert internal_job["model"] == "model-b"
    persisted_job = json.loads(
        (Path(internal_job["cache_dir"]) / "job.json").read_text(encoding="utf-8")
    )
    persisted_text = json.dumps(persisted_job, ensure_ascii=False)
    assert persisted_job["voice_configured"] is True
    assert "voice" not in persisted_job
    assert "voice_id" not in persisted_text
    assert "voice-a" not in persisted_text
    assert "voice-b" not in persisted_text

    status_job = worker.snapshot(job["id"])
    assert status_job["voice_configured"] is True
    assert "voice" not in status_job


def test_qwen_voice_design_uses_official_payload_and_job_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    calls: list[dict] = []

    def fake_api_post(path: str, payload: dict) -> dict:
        calls.append({"path": path, "payload": payload})
        return {
            "output": {
                "voice": "designed-voice",
                "target_model": "qwen3-tts-vd-2026-01-26",
                "preview_audio": {"data": "cHJldmlldw==", "response_format": "wav"},
            }
        }

    monkeypatch.setattr(worker, "_api_post", fake_api_post)
    character_config = worker_module.load_character_api_config(tmp_path, "cloud_design")
    voice_id = worker._ensure_voice_id(character_config, "cloud_design")

    assert voice_id == "designed-voice"
    assert calls[0]["path"] == worker_module.VOICE_ENROLLMENT_PATH
    assert calls[0]["payload"] == {
        "model": "qwen-voice-design",
        "input": {
            "action": "create",
            "target_model": "qwen3-tts-vd-2026-01-26",
            "preferred_name": "cloud_design",
            "voice_prompt": "年轻、明亮、可靠的女性声音。",
            "preview_text": "今天的任务交给我吧。",
            "language": "zh",
        },
        "parameters": {"sample_rate": 24000, "response_format": "wav"},
    }


@pytest.mark.parametrize(
    ("model", "expects_instructions"),
    [
        ("qwen3-tts-vd-2026-01-26", False),
        ("qwen3-tts-vc-2026-01-22", False),
        ("qwen3-tts-flash", False),
        ("qwen3-tts-instruct-flash", True),
    ],
)
def test_qwen_synthesis_uses_only_model_supported_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    model: str,
    expects_instructions: bool,
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    captured: list[dict] = []

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(bytes(480))
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    def fake_api_post(path: str, payload: dict) -> dict:
        captured.append(payload)
        return {"output": {"audio": {"data": encoded}}}

    monkeypatch.setattr(worker, "_api_post", fake_api_post)
    output = tmp_path / f"{model}.wav"
    job = {
        "model": model,
        "voice": "designed-voice",
        "language": "Chinese",
        "instructions": "不应发送",
        "send_instructions": True,
        "optimize_instructions": True,
        "volume": 80,
        "speech_rate": 1.2,
        "pitch_rate": 1.1,
    }

    worker._synthesize("你好", job, output)

    assert output.is_file()
    assert len(captured) == 1
    assert captured[0]["model"] == model
    input_payload = captured[0]["input"]
    assert input_payload["text"] == "你好"
    assert input_payload["voice"] == "designed-voice"
    assert input_payload["language_type"] == "Chinese"
    assert input_payload["stream"] is False
    assert "volume" not in input_payload
    assert "speech_rate" not in input_payload
    assert "pitch_rate" not in input_payload
    if expects_instructions:
        assert input_payload["instructions"] == "不应发送"
        assert input_payload["optimize_instructions"] is True
    else:
        assert "instructions" not in input_payload
        assert "optimize_instructions" not in input_payload


def test_parallel_clone_enrollment_is_deduplicated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    calls: list[dict] = []

    def fake_api_post(path: str, payload: dict) -> dict:
        calls.append({"path": path, "payload": payload})
        return {"output": {"voice_id": "voice-cloned"}}

    monkeypatch.setattr(worker, "_api_post", fake_api_post)
    character_config = worker_module.load_character_api_config(tmp_path, "cloud_clone")
    with ThreadPoolExecutor(max_workers=2) as executor:
        voice_ids = list(
            executor.map(
                lambda _: worker._ensure_voice_id(character_config, "cloud_clone"),
                range(2),
            )
        )

    assert voice_ids == ["voice-cloned", "voice-cloned"]
    assert len(calls) == 1
    assert calls[0]["payload"]["input"]["prefix"] == "cloudclone"


def test_job_and_chunk_metadata_persist_only_safe_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    job = worker.submit("安全落盘测试", character_id="cloud_a", play=False)
    provider_voice = "provider-private-voice"
    audio_data = "cHJpdmF0ZS1hdWRpby1ieXRlcw=="
    private_url = "https://private.example.test/audio.wav?token=secret"

    def fake_synthesize(sentence: str, internal_job: dict, output: Path) -> dict:
        with wave.open(str(output), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(24000)
            wav_file.writeframes(bytes(480))
        return {
            "status_code": 200,
            "request_id": "request-safe-persisted",
            "model": internal_job["model"],
            "message": f"generated with {internal_job['voice']} at {private_url}",
            "output": {
                "voice": internal_job["voice"],
                "voice_id": provider_voice,
                "audio": {
                    "data": audio_data,
                    "url": private_url,
                    "format": "wav",
                },
                "preview_audio": f"data:audio/wav;base64,{audio_data}",
                "download_url": private_url,
            },
        }

    monkeypatch.setattr(worker, "_synthesize", fake_synthesize)
    worker._run_job(job["id"])

    cache_dir = Path(job["cache_dir"])
    job_document = json.loads((cache_dir / "job.json").read_text(encoding="utf-8"))
    metadata_paths = [path for path in cache_dir.glob("*.json") if path.name != "job.json"]
    assert len(metadata_paths) == 1
    metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
    settings = metadata["settings"]
    response = metadata["response"]

    assert worker.jobs[job["id"]]["voice"] == "voice-a"
    assert job_document["voice_configured"] is True
    assert "voice" not in job_document
    assert settings["voice_configured"] is True
    assert "voice" not in settings
    assert "voice_id" not in settings
    assert response["status_code"] == 200
    assert response["request_id"] == "request-safe-persisted"
    assert response["model"] == "model-a"
    assert response["output"]["voice_configured"] is True
    assert response["output"]["audio"]["format"] == "wav"
    assert response["output"]["audio"]["audio_available"] is True
    assert "data" not in response["output"]["audio"]
    assert "url" not in response["output"]["audio"]

    persisted_text = json.dumps(
        {"job": job_document, "metadata": metadata},
        ensure_ascii=False,
    )
    for secret in ("voice-a", provider_voice, audio_data, private_url):
        assert secret not in persisted_text
    assert '"voice_id"' not in persisted_text


def test_http_speak_requires_explicit_oumuq_enrollment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)

    def unexpected_enrollment(*args, **kwargs):
        raise AssertionError("/speak must not enroll an explicit character")

    monkeypatch.setattr(worker, "_ensure_voice_id", unexpected_enrollment)
    server = worker_module.ThreadingHTTPServer(("127.0.0.1", 0), worker_module.make_handler(worker))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "text": "请不要隐式注册",
                "character_id": "cloud_design",
                "play": False,
            }
        ).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{server.server_port}/speak",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        response_body = json.loads(exc_info.value.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert exc_info.value.code == 400
    assert "Register it explicitly through OumuQ" in response_body["error"]
    assert "automatic enrollment is disabled" in response_body["error"]


def test_public_status_and_startup_event_redact_voice_ids_and_error_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    job = worker.submit("你好", character_id="cloud_a", play=False)
    worker._set_job(
        job["id"],
        status="error",
        error="provider failed for voice-a at https://signed.example.test/private.wav?token=secret",
    )

    job_status = worker.snapshot(job["id"])
    root_status = worker.snapshot()
    startup = worker_module.startup_event(worker, worker.args)
    serialized = json.dumps(
        {"job": job_status, "status": root_status, "startup": startup},
        ensure_ascii=False,
    )

    assert job_status["voice_configured"] is True
    assert root_status["voice_configured"] is True
    assert startup["voice_configured"] is True
    assert "voice" not in job_status
    assert "voice" not in root_status
    assert "voice" not in startup
    assert "voice-a" not in serialized
    assert "signed.example.test" not in serialized
    assert "<redacted-voice>" in job_status["error"]
    assert "<redacted-url>" in job_status["error"]


def test_api_error_reports_only_safe_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    secret_voice = "private-voice-123"
    detail = json.dumps(
        {
            "code": "InvalidParameter",
            "message": f"provider exposed {secret_voice}",
            "request_id": "request-safe-123",
            "output": {"voice_id": secret_voice, "debug": "private response"},
        }
    ).encode("utf-8")
    http_error = HTTPError(
        "https://dashscope.aliyuncs.com/private",
        400,
        "Bad Request",
        None,
        io.BytesIO(detail),
    )

    def fail_urlopen(*args, **kwargs):
        raise http_error

    monkeypatch.setattr(worker_module, "urlopen", fail_urlopen)
    with pytest.raises(RuntimeError) as exc_info:
        worker._api_post(worker_module.TTS_PATH, {"input": {"voice": secret_voice}})

    message = str(exc_info.value)
    assert "http_status=400" in message
    assert "provider_code=InvalidParameter" in message
    assert "request_id=request-safe-123" in message
    assert secret_voice not in message
    assert "provider exposed" not in message
    assert "private response" not in message


def test_missing_audio_error_does_not_include_provider_response_or_voice_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = create_worker(tmp_path, monkeypatch)
    secret_voice = "private-voice-456"

    monkeypatch.setattr(
        worker,
        "_api_post",
        lambda *args, **kwargs: {
            "request_id": "request-safe-456",
            "output": {"voice_id": secret_voice, "debug": "private response"},
        },
    )
    job = {
        "model": "qwen3-tts-flash",
        "voice": secret_voice,
        "language": "Chinese",
        "instructions": None,
        "send_instructions": False,
        "optimize_instructions": False,
        "volume": 80,
        "speech_rate": 1.2,
        "pitch_rate": 1.1,
    }

    with pytest.raises(RuntimeError) as exc_info:
        worker._synthesize("你好", job, tmp_path / "missing.wav")

    message = str(exc_info.value)
    assert "request_id=request-safe-456" in message
    assert "output_keys=['debug', 'voice_id']" in message
    assert secret_voice not in message
    assert "private response" not in message
