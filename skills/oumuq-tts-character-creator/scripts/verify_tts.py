from __future__ import annotations

import argparse
import json
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PLAYBACK_POLICY_DESCRIPTION = "OumuQ 进程内 FIFO + 主机级播放互斥；不保证跨进程全局 FIFO 顺序"


def request_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers={"Content-Type": "application/json; charset=utf-8"} if data else {})
    with urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"接口未返回 JSON object：{url}")
    return result


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def playback_policy_stage(status: dict) -> dict:
    verified = (
        status.get("enabled") is True
        and status.get("mode") == "process-fifo+host-lock"
        and status.get("ordering_scope") == "process"
        and status.get("playback_mutex_scope") == "host"
        and status.get("cross_process_fifo") is False
        and status.get("overlap_allowed") is False
    )
    return {
        "ok": verified,
        "playback_policy_verified": verified,
        "playback_audio_tested": False,
        "request_play": False,
        "mode": status.get("mode"),
        "ordering_scope": status.get("ordering_scope"),
        "playback_mutex_scope": status.get("playback_mutex_scope"),
        "cross_process_fifo": status.get("cross_process_fifo"),
        "overlap_allowed": status.get("overlap_allowed"),
        "enabled": status.get("enabled"),
    }


def job_identity_stage(character_id: str, expected_model: str | None, job: dict) -> dict:
    actual_character_id = str(job.get("character_id") or "")
    actual_model = str(job.get("model") or "")
    character_matches = actual_character_id.lower() == character_id.lower()
    model_matches = not expected_model or actual_model == expected_model
    return {
        "ok": character_matches and model_matches,
        "expected_character_id": character_id,
        "actual_character_id": actual_character_id or None,
        "character_matches": character_matches,
        "expected_model": expected_model,
        "actual_model": actual_model or None,
        "model_matches": model_matches,
    }


def creation_metadata(
    character: dict,
    route: dict | None = None,
    job: dict | None = None,
    verification_status: str = "registered",
    *,
    playback_policy_verified: bool = False,
    playback_audio_tested: bool = False,
) -> dict:
    route = route or {}
    job = job or {}
    payload = route.get("payload", {}) if isinstance(route.get("payload"), dict) else {}
    engine = str(character.get("tts_engine") or job.get("engine") or "unknown")
    model = (
        job.get("model")
        or payload.get("model")
        or character.get("api_target_model")
        or character.get("api_clone_target_model")
    )
    engine_key = engine.lower()
    enrollment_model = character.get("api_enrollment_model")
    creation_method = character.get("api_voice_creation_method")
    if engine_key in {"qwen-tts-api", "qwen_tts_api", "qwen-api"}:
        provider = "阿里云百炼（Alibaba Cloud Model Studio）"
        api = "DashScope HTTP API"
        if not creation_method:
            if enrollment_model == "qwen-voice-design":
                creation_method = "voice_design"
            elif enrollment_model in {"qwen-voice-enrollment", "voice-enrollment"}:
                creation_method = "voice_cloning"
            elif character.get("api_voice_configured") or character.get("api_voice_id"):
                creation_method = "existing_cloud_voice"
            else:
                creation_method = "provider_preset"
        if not model:
            model = "未配置"
    elif engine_key in {"indextts2", "index-tts2", "index_tts2"}:
        provider = "本机本地推理"
        api = "IndexTTS2 worker HTTP API"
        model = model or "IndexTTS2"
        creation_method = creation_method or "local_reference_conditioning"
    elif engine_key in {"qwen3-tts", "qwen3_tts", "qwen"}:
        provider = "本机本地推理"
        api = "Qwen3-TTS worker HTTP API"
        model = model or "Qwen3-TTS"
        creation_method = creation_method or "local_reference_conditioning"
    else:
        provider = str(character.get("tts_provider") or "未标明")
        api = "未标明"
        model = model or "未配置"
        creation_method = creation_method or "unknown"

    reference_source = (
        "不使用参考音频（由角色资料设计原创音色）"
        if creation_method == "voice_design"
        else (
            "授权参考音频（具体路径和 URL 仅保存在本机）"
            if creation_method in {"voice_cloning", "local_reference_conditioning"}
            else "已有音色或预设音色"
        )
    )
    return {
        "status": verification_status,
        "character_id": character.get("id"),
        "display_name": character.get("display_name_zh")
        or character.get("display_name")
        or character.get("name"),
        "variant_of": character.get("base_character_id"),
        "persona_source": character.get("source_profile_url") or "角色目录中的证据化资料",
        "provider": provider,
        "api": api,
        "oumuq_engine": engine,
        "worker_url": route.get("worker_url") or character.get("worker_url"),
        "actual_model": model,
        "voice_creation_method": creation_method,
        "enrollment_model": enrollment_model,
        "voice_id_configured": bool(character.get("api_voice_configured") or character.get("api_voice_id")),
        "reference_source": reference_source,
        "reference_audio_language": character.get("api_clone_reference_language"),
        "speech_language": character.get("speech_language"),
        "visible_language": character.get("visible_language"),
        "playback_policy": PLAYBACK_POLICY_DESCRIPTION,
        "playback_policy_verified": playback_policy_verified,
        "playback_audio_tested": playback_audio_tested,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 OumuQ 角色注册、路由和真实 TTS 输出")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--oumuq-url", default="http://127.0.0.1:8780")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    base = args.oumuq_url.rstrip("/")
    report = {
        "schema_version": 2,
        "character_id": args.character_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "creation": {},
        "stages": {},
    }

    characters = request_json(base + "/api/characters")
    matches = [
        item
        for item in characters.get("characters", [])
        if str(item.get("id", "")).lower() == args.character_id.lower()
    ]
    report["stages"]["character_visible"] = {
        "ok": len(matches) == 1,
        "registry_source": characters.get("source"),
    }
    if len(matches) != 1:
        write_report(report, args.report)
        raise SystemExit(f"角色可见性失败：{len(matches)}")
    character = matches[0]
    language = character.get("speech_language") or "Chinese"
    report["creation"] = creation_metadata(character)

    route = request_json(
        base + "/api/route/resolve",
        {
            "character_id": args.character_id,
            "text": args.text,
            "language": language,
            "play": False,
        },
    )
    payload = route.get("payload", {})
    fixed_prompt_audio_configured = bool(
        payload.get("prompt_audio") or payload.get("prompt_audio_configured")
    )
    route_ok = (
        route.get("route_id") == args.character_id
        and payload.get("character_folder")
        and not fixed_prompt_audio_configured
    )
    report["stages"]["route_ready"] = {
        "ok": bool(route_ok),
        "worker_url": route.get("worker_url"),
        "dynamic_character_folder": payload.get("character_folder"),
        "fixed_prompt_audio_configured": fixed_prompt_audio_configured,
    }
    report["creation"] = creation_metadata(character, route)
    if not route_ok:
        write_report(report, args.report)
        raise SystemExit("路由未使用 character_folder 动态选择，或角色 ID 不一致")

    playback_status = request_json(base + "/api/playback/status")
    policy_stage = playback_policy_stage(playback_status)
    report["stages"]["playback_policy"] = policy_stage
    report["creation"] = creation_metadata(
        character,
        route,
        playback_policy_verified=policy_stage["playback_policy_verified"],
        playback_audio_tested=False,
    )
    if not policy_stage["ok"]:
        write_report(report, args.report)
        raise SystemExit("播放策略验收失败：需要进程内 FIFO 与主机级播放互斥")

    submitted = request_json(
        base + "/api/speak",
        {
            "character_id": args.character_id,
            "text": args.text,
            "language": language,
            "play": False,
        },
        timeout=30,
    )
    worker_response = submitted.get("worker_response", {})
    job_id = worker_response.get("id")
    status = worker_response.get("status")
    report["stages"]["tts_queued"] = {
        "ok": bool(job_id) and status in {"queued", "running", "done"},
        "job_id": job_id,
        "status": status,
        "run_dir": submitted.get("run_dir"),
    }
    if not job_id:
        write_report(report, args.report)
        raise SystemExit("worker 未返回 job id")

    worker_url = route.get("worker_url")
    deadline = time.time() + args.timeout
    job = worker_response
    while time.time() < deadline and job.get("status") not in {"done", "error"}:
        time.sleep(3)
        query = urlencode({"worker_url": worker_url})
        job = request_json(f"{base}/api/worker/status/{job_id}?{query}", timeout=10)
    if job.get("status") != "done":
        report["stages"]["tts_completed"] = {
            "ok": False,
            "status": job.get("status"),
            "error": job.get("error"),
        }
        report["creation"] = creation_metadata(
            character,
            route,
            job,
            "tts_failed",
            playback_policy_verified=True,
            playback_audio_tested=False,
        )
        write_report(report, args.report)
        raise SystemExit(f"TTS 未完成：{job.get('status')}")

    expected_model = str(
        payload.get("model")
        or character.get("api_target_model")
        or character.get("api_clone_target_model")
        or ""
    ) or None
    identity_stage = job_identity_stage(args.character_id, expected_model, job)
    report["stages"]["job_identity"] = identity_stage
    if not identity_stage["ok"]:
        report["creation"] = creation_metadata(
            character,
            route,
            job,
            "job_identity_failed",
            playback_policy_verified=True,
            playback_audio_tested=False,
        )
        write_report(report, args.report)
        raise SystemExit("最终 worker job 的角色或模型与路由预期不一致")

    output = Path(job.get("output", ""))
    if not output.is_file() or "voice-references" in {part.lower() for part in output.parts}:
        report["stages"]["tts_verified"] = {
            "ok": False,
            "error": f"输出路径无效：{output}",
            "playback_audio_tested": False,
        }
        write_report(report, args.report)
        raise SystemExit(f"输出路径无效：{output}")
    with wave.open(str(output), "rb") as wav:
        duration = wav.getnframes() / wav.getframerate()
        sample_rate = wav.getframerate()
    verified = output.stat().st_size > 44 and duration > 0.1
    report["stages"]["tts_completed"] = {"ok": True, "job_id": job_id}
    report["stages"]["tts_verified"] = {
        "ok": verified,
        "output": str(output),
        "bytes": output.stat().st_size,
        "duration_seconds": duration,
        "sample_rate": sample_rate,
        "prompt_audio_configured": bool(job.get("prompt_audio_configured")),
        "prompt_audio_count": int(job.get("prompt_audio_count") or 0),
        "prompt_audio_augmented": job.get("prompt_audio_augmented"),
        "playback_audio_tested": False,
    }
    report["creation"] = creation_metadata(
        character,
        route,
        job,
        "tts_verified" if verified else "tts_verification_failed",
        playback_policy_verified=True,
        playback_audio_tested=False,
    )
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    write_report(report, args.report)
    print(json.dumps({"creation": report["creation"], "stages": report["stages"]}, ensure_ascii=False, indent=2))
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
