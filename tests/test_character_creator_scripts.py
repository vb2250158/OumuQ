from __future__ import annotations

import html
import importlib.util
import json
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest


SKILL = Path(__file__).resolve().parents[1] / "skills" / "oumuq-tts-character-creator"


def run(script: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(SKILL / "scripts" / script), *args],
        text=True,
        capture_output=True,
        check=check,
        encoding="utf-8",
    )


def load_verify_tts() -> Any:
    verify_path = SKILL / "scripts" / "verify_tts.py"
    spec = importlib.util.spec_from_file_location("character_verify_tts", verify_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_extract_sources() -> Any:
    extract_path = SKILL / "scripts" / "extract_sources.py"
    spec = importlib.util.spec_from_file_location("character_extract_sources", extract_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_prepare_material_evidence() -> Any:
    prepare_path = SKILL / "scripts" / "prepare_material_evidence.py"
    spec = importlib.util.spec_from_file_location("character_prepare_material_evidence", prepare_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_test_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 4800)


def verified_playback_status() -> dict[str, object]:
    return {
        "enabled": True,
        "mode": "process-fifo+host-lock",
        "ordering_scope": "process",
        "playback_mutex_scope": "host",
        "cross_process_fifo": False,
        "overlap_allowed": False,
    }


def test_offline_bwiki_extract_validates_root_counts(tmp_path: Path) -> None:
    entries = [
        {"id": "42_gacha_01", "type": "初见", "file": "vo_42_gacha_01", "cn": "你好，舰长！", "ja": "こんにちは", "ko": "안녕하세요", "urlCn": ""},
        {"id": "42_skill_01", "type": "技能1", "file": "vo_42_skill_01", "cn": "交给我吧！", "ja": "任せて", "ko": "맡겨줘", "urlCn": ""},
    ]
    types = [{"name": "初见", "count": 1}, {"name": "技能1", "count": 1}]
    tag = (
        '<div class="voice-player-root" data-char-id="42" data-total="2" '
        f'data-entries="{html.escape(json.dumps(entries, ensure_ascii=False), quote=True)}" '
        f'data-types="{html.escape(json.dumps(types, ensure_ascii=False), quote=True)}"></div>'
    )
    source = tmp_path / "rendered.html"
    output = tmp_path / "extract.json"
    source.write_text(tag, encoding="utf-8")

    run("extract_bwiki_voice.py", "--title", "Fixture", "--html-file", str(source), "--offline", "--output", str(output))

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["voice_total_declared"] == 2
    assert result["combatant_id"] == "42"
    assert result["language_text_counts"] == {"cn": 2, "ja": 2, "ko": 2}
    assert result["voice_strategy"] == "rendered-html"


def test_offline_bwiki_extract_rejects_wrong_declared_total(tmp_path: Path) -> None:
    entries = [{"id": "42_gacha_01", "type": "初见", "cn": "你好"}]
    tag = (
        '<div class="voice-player-root" data-char-id="42" data-total="2" '
        f'data-entries="{html.escape(json.dumps(entries, ensure_ascii=False), quote=True)}" '
        'data-types="[]"></div>'
    )
    source = tmp_path / "bad.html"
    source.write_text(tag, encoding="utf-8")

    result = run(
        "extract_bwiki_voice.py", "--combatant-id", "42", "--html-file", str(source),
        "--offline", "--output", str(tmp_path / "extract.json"), check=False,
    )

    assert result.returncode != 0
    assert "data-total=2" in result.stderr


def test_offline_bwiki_extract_parses_restricted_lua_without_execution(tmp_path: Path) -> None:
    lua = tmp_path / "voice.lua"
    lua.write_text(
        'return {\n  {\n    id = "42_gacha_01",\n    char_id = "42",\n    type = "初见",\n'
        '    file = "vo_42_gacha_01",\n    cn = "你好，舰长！",\n    ja = "こんにちは",\n    ko = "안녕하세요",\n  },\n}\n',
        encoding="utf-8",
    )
    output = tmp_path / "extract.json"

    run(
        "extract_bwiki_voice.py", "--combatant-id", "42", "--lua-file", str(lua),
        "--offline", "--output", str(output),
    )

    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["voice_strategy"] == "raw-lua-file"
    assert result["entries"][0]["cn"] == "你好，舰长！"


def test_prepare_merges_manual_fields_and_builds_semantic_patterns(tmp_path: Path) -> None:
    character = tmp_path / "character"
    character.mkdir()
    (character / "voice-index.json").write_text(
        json.dumps([{"id": "42_gacha_01", "manual_notes": "keep-me"}]), encoding="utf-8"
    )
    extract = tmp_path / "extract.json"
    extract.write_text(
        json.dumps(
            {
                "source": "fixture",
                "page_url": "https://example.test/role",
                "profile": {
                    "race_type": ["人类"],
                    "birth": ["7月3日"],
                    "background_text": "她做事果决。她也很温柔。"
                },
                "entries": [
                    {"id": "42_gacha_01", "type": "初见", "file": "vo_42_gacha_01", "cn": "你好，舰长！"},
                    {"id": "42_skill_01", "type": "技能1", "file": "vo_42_skill_01", "cn": "交给我吧！"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    run("prepare_bwiki_character.py", "--extract", str(extract), "--character-dir", str(character), "--character-id", "fixture", "--language", "cn")

    index = json.loads((character / "voice-index.json").read_text(encoding="utf-8"))
    assert index[0]["manual_notes"] == "keep-me"
    assert index[0]["match_patterns"] == ["初次见面|又见面|自我介绍"]
    assert index[1]["mood"] == ["determined", "energetic"]
    assert index[1]["base_name"] == "vo_42_skill_01"
    profile_evidence = json.loads((character / "profile-evidence.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in profile_evidence["evidence"]] == [
        "profile-identity", "profile-background-01", "profile-background-02"
    ]


def test_extract_sources_marks_partial_as_nonzero(tmp_path: Path) -> None:
    good = tmp_path / "good.md"
    good.write_text("角色资料", encoding="utf-8")
    output = tmp_path / "sources.json"

    result = run("extract_sources.py", str(good), str(tmp_path / "missing.md"), "--output", str(output), check=False)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == 2
    assert payload["status"] == "partial"
    assert len(payload["sources"]) == 1
    assert len(payload["failures"]) == 1


def test_extract_sources_rejects_dynamic_shell() -> None:
    module = load_extract_sources()

    with pytest.raises(ValueError, match="动态空壳"):
        module.validate_url_text("鸣潮WIKI官网\n您使用的浏览器版本过低", "direct-html")

    with pytest.raises(ValueError, match="正文过短"):
        module.validate_url_text("只有页面标题", "direct-html")


def test_kurobbs_item_api_uses_official_text_and_drops_media_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_extract_sources()
    fixture = {
        "success": True,
        "data": {
            "content": {
                "title": "守岸人",
                "modules": [
                    {
                        "title": "基础资料",
                        "components": [{
                            "type": "role-component",
                            "role": {
                                "title": "守岸人",
                                "subtitle": "THE SHOREKEEPER",
                                "roleDescriptionTitle": "共鸣能力：叙响织构",
                                "roleDescription": "黑海岸守岸人，神秘清冷、超然物外。" * 16,
                                "info": [{"text": "性别：女"}, {"text": "出生：黑海岸"}],
                                "figureUrl": "https://media.invalid/figure.png",
                            },
                        }],
                    },
                    {
                        "title": "角色档案",
                        "components": [{
                            "type": "basic-component",
                            "title": "检验鉴定",
                            "content": "<p>她由回音能量晶体构成，并逐渐理解人类情感。</p>",
                        }],
                    },
                    {
                        "title": "角色语音",
                        "components": [{
                            "type": "audio-component",
                            "title": "个性语音",
                            "mediaTabs": [{
                                "title": "中文：测试",
                                "mediaList": [{
                                    "audioTitle": "心声1",
                                    "content": "欢迎回来。我会一直守望这片海岸。",
                                    "playUrl": "https://media.invalid/private.wav",
                                }],
                            }],
                        }],
                    },
                    {"title": "角色养成", "components": [{"title": "不应提取", "content": "攻击力数值"}]},
                ],
            },
        },
    }
    calls: list[tuple[str, bytes | None, dict[str, str] | None]] = []

    def fake_fetch(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
        calls.append((url, data, headers))
        return json.dumps(fixture, ensure_ascii=False).encode(), "application/json"

    monkeypatch.setattr(module, "fetch", fake_fetch)
    text, method = module.kurobbs_item_api("https://wiki.kurobbs.com/mc/item/1286814658335739904")

    assert method == "kurobbs-entry-detail-api"
    assert calls == [(module.KURO_ENTRY_API, b"id=1286814658335739904", {
        "Content-Type": "application/x-www-form-urlencoded", "wiki_type": "9",
    })]
    assert "神秘清冷" in text
    assert "欢迎回来" in text
    assert "攻击力数值" not in text
    assert "playUrl" not in text
    assert "media.invalid" not in text


def test_prepare_material_evidence_indexes_kurobbs_voice_text(tmp_path: Path) -> None:
    character = tmp_path / "character"
    source_bundle = tmp_path / "source-bundle.json"
    source_bundle.write_text(json.dumps({
        "status": "success",
        "sources": [{
            "id": "source-1",
            "source": "https://wiki.kurobbs.com/mc/item/1",
            "method": "kurobbs-entry-detail-api",
            "sha256": "fixture",
            "text": "\n".join([
                "【角色名】", "测试角色", "# 角色语音", "## 个性语音", "### 中文：测试",
                "【心声1】", "欢迎回来。", "## 战斗语音", "### 中文：测试", "【技能1】", "不用怕。",
            ]),
        }],
        "failures": [],
    }, ensure_ascii=False), encoding="utf-8")

    run(
        "prepare_material_evidence.py",
        "--source-bundle", str(source_bundle),
        "--character-dir", str(character),
        "--character-id", "fixture",
    )

    evidence = json.loads((character / "character-evidence.json").read_text(encoding="utf-8"))
    voices = json.loads((character / "voice-index.json").read_text(encoding="utf-8"))
    assert evidence["voice_entry_count"] == 2
    assert evidence["indexed_entry_count"] == 2
    assert voices[0]["id"].startswith("kurobbs-personality-")
    assert voices[1]["id"].startswith("kurobbs-combat-")
    assert all(len(item["id"].rsplit("-", 1)[-1]) == 12 for item in voices)
    assert all("audio_file" not in item for item in voices)
    assert all("playUrl" not in json.dumps(item) for item in voices)


def test_kurobbs_voice_ids_are_stable_when_source_order_changes() -> None:
    module = load_prepare_material_evidence()
    prefix = "# 角色语音\n## 个性语音\n### 中文：测试\n"
    source_a = {
        "method": "kurobbs-entry-detail-api",
        "text": prefix + "【心声1】\n欢迎回来。\n【心声2】\n我会记得。",
    }
    source_b = {
        "method": "kurobbs-entry-detail-api",
        "text": prefix + "【心声2】\n我会记得。\n【心声1】\n欢迎回来。",
    }

    ids_a = {item["title"]: item["id"] for item in module.kurobbs_voice_entries(source_a)}
    ids_b = {item["title"]: item["id"] for item in module.kurobbs_voice_entries(source_b)}

    assert ids_a == ids_b


def test_upsert_character_is_atomic_and_idempotent(tmp_path: Path) -> None:
    character_dir = tmp_path / "voice-references" / "characters" / "fixture"
    character_dir.mkdir(parents=True)
    (character_dir / "voice-index.json").write_text("[]", encoding="utf-8")
    registry = tmp_path / "voice-references" / "reference-index.json"
    registry.write_text('{"version":1,"root":"voice-references","characters":[]}', encoding="utf-8")
    entry = {
        "id": "fixture", "name": "Fixture", "display_name_zh": "测试角色",
        "character_folder": "voice-references/characters/fixture",
        "index_file": "voice-references/characters/fixture/voice-index.json",
        "tts_engine": "IndexTTS2", "worker_url": "http://127.0.0.1:8766",
        "speech_language": "Chinese", "visible_language": "Chinese",
        "style_summary": "Test persona.", "style_summary_zh": "测试人格。",
    }
    entry_file = character_dir / "registry-entry.json"
    entry_file.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")

    run("upsert_character.py", "--workspace", str(tmp_path), "--entry-file", str(entry_file), "--dry-run")
    assert json.loads(registry.read_text(encoding="utf-8"))["characters"] == []

    run("upsert_character.py", "--workspace", str(tmp_path), "--entry-file", str(entry_file))
    run("upsert_character.py", "--workspace", str(tmp_path), "--entry-file", str(entry_file))
    characters = json.loads(registry.read_text(encoding="utf-8"))["characters"]
    assert [item["id"] for item in characters] == ["fixture"]


def test_prepare_material_evidence_adds_precise_locators(tmp_path: Path) -> None:
    bundle = tmp_path / "source-bundle.json"
    bundle.write_text(
        json.dumps(
            {
                "status": "success",
                "sources": [
                    {
                        "id": "source-1", "source": "notes.md", "method": "plain-text", "sha256": "abc",
                        "text": "她做事利落。遇到故障会说‘别慌，我来！’\n她喜欢甜茶。",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    character = tmp_path / "character"

    run(
        "prepare_material_evidence.py", "--source-bundle", str(bundle),
        "--character-dir", str(character), "--character-id", "lanxi",
    )

    evidence = json.loads((character / "character-evidence.json").read_text(encoding="utf-8"))
    assert [item["id"] for item in evidence["evidence_lines"]] == [
        "source-1-e001", "source-1-e002", "source-1-e003"
    ]
    assert evidence["evidence_lines"][2]["line"] == 2
    assert json.loads((character / "voice-index.json").read_text(encoding="utf-8")) == []


def test_strict_validator_rejects_invalid_match_regex(tmp_path: Path) -> None:
    folder = tmp_path / "voice-references" / "characters" / "broken"
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("损坏角色", encoding="utf-8")
    (folder / "source-bundle.json").write_text(
        json.dumps({"status": "success", "sources": [{"text": "证据", "id": "source-1"}], "failures": []}),
        encoding="utf-8",
    )
    (folder / "character-evidence.json").write_text(
        json.dumps({"voice_entry_count": 1, "evidence_lines": [{"id": "line-1", "text": "证据"}], "rights_status": "not_applicable"}),
        encoding="utf-8",
    )
    claim = {"claim": "证据化结论", "evidence_ids": ["line-1"], "confidence": "high"}
    profile = {section: [claim] for section in (
        "identity_facts", "persona_traits", "speech_patterns", "address_terms",
        "emotional_modes", "preferences", "boundaries",
    )}
    (folder / "character-profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (folder / "voice-index.json").write_text(
        json.dumps(
            [{
                "id": "line-1", "title": "测试", "language": "Chinese", "text": "证据",
                "emotion_vector": [0.2, 0, 0, 0, 0, 0, 0, 0.3], "match_patterns": ["["],
            }]
        ),
        encoding="utf-8",
    )

    result = run(
        "validate_character.py", "--character-dir", str(folder), "--character-id", "broken",
        "--strict", "--skip-registry", check=False,
    )

    assert result.returncode == 1
    assert "正则无效" in result.stdout

def test_validator_supports_cloud_variant_reusing_base_character_folder(tmp_path: Path) -> None:
    folder = tmp_path / "voice-references" / "characters" / "tifira"
    folder.mkdir(parents=True)
    (folder / "README.md").write_text("蒂菲拉角色提示词", encoding="utf-8")
    (folder / "source-bundle.json").write_text(
        json.dumps({"status": "success", "sources": [], "failures": []}),
        encoding="utf-8",
    )
    (folder / "character-evidence.json").write_text(
        json.dumps(
            {
                "voice_entry_count": 0,
                "evidence_lines": [],
                "required_profile_sections": [],
                "rights_status": "not_applicable",
            }
        ),
        encoding="utf-8",
    )
    profile = {
        section: []
        for section in (
            "identity_facts",
            "persona_traits",
            "speech_patterns",
            "address_terms",
            "emotional_modes",
            "preferences",
            "boundaries",
        )
    }
    (folder / "character-profile.json").write_text(json.dumps(profile), encoding="utf-8")
    (folder / "voice-index.json").write_text("[]", encoding="utf-8")

    registry = {
        "version": 1,
        "root": "voice-references",
        "characters": [
            {
                "id": "tifira_qwen",
                "name": "Tifira Qwen",
                "display_name_zh": "蒂菲拉（千问云端）",
                "character_folder": "voice-references/characters/tifira",
                "index_file": "voice-references/characters/tifira/voice-index.json",
                "tts_engine": "Qwen-TTS-API",
                "worker_url": "http://127.0.0.1:8767",
                "speech_language": "Chinese",
                "visible_language": "Chinese",
                "style_summary": "Original Qwen-designed Tifira voice.",
                "style_summary_zh": "根据角色资料设计的原创千问音色。",
                "api_voice_creation_method": "voice_design",
                "api_enrollment_model": "qwen-voice-design",
                "api_target_model": "qwen3-tts-vd-2026-01-26",
                "api_clone_target_model": "qwen3-tts-vd-2026-01-26",
                "api_clone_language_hint": "zh",
                "api_voice_design_language": "zh",
                "api_voice_prompt": "年轻、明亮、可靠的女性声音。",
                "api_voice_preview_text": "今天的任务交给我吧。",
            }
        ],
    }
    registry_path = tmp_path / "voice-references" / "reference-index.json"
    registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    result = run(
        "validate_character.py",
        "--workspace",
        str(tmp_path),
        "--character-id",
        "tifira_qwen",
        "--strict",
    )

    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["character_id"] == "tifira_qwen"


def test_completion_metadata_names_real_provider_model_and_hides_voice_id() -> None:
    module = load_verify_tts()
    character = {
        "id": "tifira_qwen",
        "display_name_zh": "蒂菲拉（千问云端）",
        "base_character_id": "tifira",
        "tts_engine": "Qwen-TTS-API",
        "worker_url": "http://127.0.0.1:8767",
        "speech_language": "Chinese",
        "visible_language": "Chinese",
        "api_voice_id": "private-voice-id",
        "api_voice_creation_method": "voice_design",
        "api_enrollment_model": "qwen-voice-design",
        "api_target_model": "qwen3-tts-vd-2026-01-26",
        "api_clone_audio_path": r"C:\private\reference.wav",
    }

    metadata = module.creation_metadata(
        character,
        {
            "worker_url": "http://127.0.0.1:8767",
            "payload": {"model": "qwen3-tts-vd-2026-01-26"},
        },
        {"model": "qwen3-tts-vd-2026-01-26"},
        "tts_verified",
    )

    rendered = json.dumps(metadata, ensure_ascii=False)
    assert metadata["provider"] == "阿里云百炼（Alibaba Cloud Model Studio）"
    assert metadata["api"] == "DashScope HTTP API"
    assert metadata["actual_model"] == "qwen3-tts-vd-2026-01-26"
    assert metadata["voice_creation_method"] == "voice_design"
    assert metadata["status"] == "tts_verified"
    assert metadata["playback_policy"] == (
        "OumuQ 进程内 FIFO + 主机级播放互斥；不保证跨进程全局 FIFO 顺序"
    )
    assert metadata["playback_policy_verified"] is False
    assert metadata["playback_audio_tested"] is False
    assert "private-voice-id" not in rendered
    assert "reference.wav" not in rendered


def test_completion_metadata_recognizes_redacted_existing_cloud_voice() -> None:
    module = load_verify_tts()
    metadata = module.creation_metadata(
        {
            "id": "public_cloud_character",
            "tts_engine": "Qwen-TTS-API",
            "api_voice_configured": True,
            "api_target_model": "qwen3-tts-vd-fixture",
        }
    )

    assert metadata["voice_id_configured"] is True
    assert metadata["voice_creation_method"] == "existing_cloud_voice"


def test_verify_tts_checks_policy_and_job_identity_without_claiming_playback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verify_tts()
    output = tmp_path / "generated.wav"
    write_test_wav(output)
    report_path = tmp_path / "report.json"
    calls: list[tuple[str, dict | None]] = []
    character = {
        "id": "fixture_qwen",
        "display_name_zh": "测试角色（千问）",
        "tts_engine": "Qwen-TTS-API",
        "speech_language": "Chinese",
        "visible_language": "Chinese",
        "api_target_model": "qwen3-tts-vd-fixture",
        "api_voice_configured": True,
    }

    def fake_request_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
        calls.append((url, payload))
        if url.endswith("/api/characters"):
            return {"source": "fixture", "characters": [character]}
        if url.endswith("/api/route/resolve"):
            return {
                "route_id": "fixture_qwen",
                "worker_url": "http://127.0.0.1:8767",
                "payload": {
                    "character_folder": "voice-references/characters/fixture",
                    "model": "qwen3-tts-vd-fixture",
                },
            }
        if url.endswith("/api/playback/status"):
            return verified_playback_status()
        if url.endswith("/api/speak"):
            return {
                "run_dir": str(tmp_path / "run"),
                "worker_response": {
                    "id": "job-fixture",
                    "status": "done",
                    "character_id": "fixture_qwen",
                    "model": "qwen3-tts-vd-fixture",
                    "output": str(output),
                },
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(module, "request_json", fake_request_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_tts.py",
            "--character-id",
            "fixture_qwen",
            "--text",
            "测试语句",
            "--report",
            str(report_path),
        ],
    )

    assert module.main() == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stages"]["playback_policy"]["playback_policy_verified"] is True
    assert report["stages"]["playback_policy"]["playback_audio_tested"] is False
    assert report["stages"]["job_identity"]["ok"] is True
    assert report["stages"]["tts_verified"]["playback_audio_tested"] is False
    assert report["creation"]["playback_policy_verified"] is True
    assert report["creation"]["playback_audio_tested"] is False
    speak_payload = next(payload for url, payload in calls if url.endswith("/api/speak"))
    assert speak_payload is not None and speak_payload["play"] is False


@pytest.mark.parametrize(
    ("actual_character_id", "actual_model"),
    [
        ("wrong_character", "qwen3-tts-vd-fixture"),
        ("fixture_qwen", "wrong-model"),
    ],
)
def test_verify_tts_rejects_final_job_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    actual_character_id: str,
    actual_model: str,
) -> None:
    module = load_verify_tts()
    report_path = tmp_path / "mismatch-report.json"

    def fake_request_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
        if url.endswith("/api/characters"):
            return {
                "source": "fixture",
                "characters": [
                    {
                        "id": "fixture_qwen",
                        "tts_engine": "Qwen-TTS-API",
                        "speech_language": "Chinese",
                        "api_target_model": "qwen3-tts-vd-fixture",
                    }
                ],
            }
        if url.endswith("/api/route/resolve"):
            return {
                "route_id": "fixture_qwen",
                "worker_url": "http://127.0.0.1:8767",
                "payload": {
                    "character_folder": "voice-references/characters/fixture",
                    "model": "qwen3-tts-vd-fixture",
                },
            }
        if url.endswith("/api/playback/status"):
            return verified_playback_status()
        if url.endswith("/api/speak"):
            return {
                "worker_response": {
                    "id": "job-mismatch",
                    "status": "done",
                    "character_id": actual_character_id,
                    "model": actual_model,
                    "output": str(tmp_path / "unused.wav"),
                }
            }
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(module, "request_json", fake_request_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_tts.py",
            "--character-id",
            "fixture_qwen",
            "--text",
            "测试语句",
            "--report",
            str(report_path),
        ],
    )

    with pytest.raises(SystemExit, match="角色或模型"):
        module.main()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stages"]["job_identity"]["ok"] is False
    assert report["creation"]["status"] == "job_identity_failed"
    assert report["creation"]["playback_audio_tested"] is False


def test_verify_tts_rejects_unverified_playback_policy_before_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verify_tts()
    report_path = tmp_path / "policy-report.json"
    speak_called = False

    def fake_request_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
        nonlocal speak_called
        if url.endswith("/api/characters"):
            return {
                "source": "fixture",
                "characters": [
                    {
                        "id": "fixture_qwen",
                        "tts_engine": "Qwen-TTS-API",
                        "speech_language": "Chinese",
                    }
                ],
            }
        if url.endswith("/api/route/resolve"):
            return {
                "route_id": "fixture_qwen",
                "worker_url": "http://127.0.0.1:8767",
                "payload": {"character_folder": "voice-references/characters/fixture"},
            }
        if url.endswith("/api/playback/status"):
            return {
                "enabled": True,
                "mode": "global-fifo",
                "overlap_allowed": False,
            }
        if url.endswith("/api/speak"):
            speak_called = True
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(module, "request_json", fake_request_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_tts.py",
            "--character-id",
            "fixture_qwen",
            "--text",
            "测试语句",
            "--report",
            str(report_path),
        ],
    )

    with pytest.raises(SystemExit, match="播放策略验收失败"):
        module.main()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stages"]["playback_policy"]["playback_policy_verified"] is False
    assert report["stages"]["playback_policy"]["playback_audio_tested"] is False
    assert speak_called is False


def test_verify_tts_rejects_redacted_fixed_prompt_audio_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_verify_tts()
    report_path = tmp_path / "fixed-prompt-report.json"

    def fake_request_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
        if url.endswith("/api/characters"):
            return {
                "source": "fixture",
                "characters": [
                    {
                        "id": "fixture_local",
                        "tts_engine": "IndexTTS2",
                        "speech_language": "Chinese",
                    }
                ],
            }
        if url.endswith("/api/route/resolve"):
            return {
                "route_id": "fixture_local",
                "worker_url": "http://127.0.0.1:8766",
                "payload": {
                    "character_folder": "voice-references/characters/fixture",
                    "prompt_audio_configured": True,
                },
            }
        raise AssertionError(f"unexpected URL after invalid route: {url}")

    monkeypatch.setattr(module, "request_json", fake_request_json)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_tts.py",
            "--character-id",
            "fixture_local",
            "--text",
            "测试语句",
            "--report",
            str(report_path),
        ],
    )

    with pytest.raises(SystemExit, match="路由未使用 character_folder"):
        module.main()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stages"]["route_ready"]["ok"] is False
    assert report["stages"]["route_ready"]["fixed_prompt_audio_configured"] is True


def test_skill_persists_issue_lessons_and_prevention_gates() -> None:
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    troubleshooting = (SKILL / "references" / "troubleshooting.md").read_text(encoding="utf-8")
    openai_yaml = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")

    assert "问题复盘与防复发" in skill_text
    assert "references/troubleshooting.md" in skill_text
    assert "本次问题沉淀" in skill_text
    for required in (
        "OumuQ worker 名不等于真实模型",
        "共享云 worker 串用启动角色音色",
        "不同 worker 各自播放会发生叠音",
        "Qwen Voice Design 预览 WAV 的 RIFF 长度是占位值",
        "预留播放序号后的非网络异常会永久卡住队列",
        "显式角色仍接受客户端残留的 voice/model/folder",
        "worker API 已脱敏但运行期缓存仍落盘真实音色",
        "参考音频文件列表使用了未覆盖的字段名",
        "自定义注册端点或任意本地路径可造成密钥与文件外传",
        "共享 worker 在 `/speak` 中自动注册音色",
        "状态轮询一次失败就释放任务",
        "请求文件角色与 API character_id 不一致导致错绑音色",
        "WAV 解码验证被文案写成实际扬声器试听",
        "PowerShell 生成 skill 元数据时吞掉 `$skill-name`",
        "仓库 skill 与已安装 skill 不一致",
        "HTTP 200 的动态 Wiki 空壳被误判为正文",
        "动态 Wiki 语音文字已提取但 voice-index 仍为空",
        "没有本地参考音频被误报为云端音色无法验证",
        "浏览器渲染回退无法附加动态页面",
        "脱敏扫描用子串匹配误报安全布尔键",
        "PowerShell foreach 结果直接接管道触发解析错误",
        "Get-NetTCPConnection 非终止错误被误判为服务离线",
        "并行只读检查中 rg 无匹配导致整批失败",
        "ASCII Base64 携带中文迁移内容导致字符损坏",
        "迁移脚本先备份后因错误相对路径半途失败",
        "台词顺序号作为身份导致插入时 ID 漂移",
        "Windows 受限令牌阻止 multiprocessing 命名管道",
        "Windows PowerShell 5 把无 BOM 中文脚本读成乱码",
        "迁移包把 Voice Design 版本当成声音克隆",
        "库街区文字提取丢弃 playUrl 后没有本地克隆样本",
        "系统没有 ffprobe 时 WAV 时长被误报为零",
        "克隆需求被静默替换为 Voice Design",
        "把“不上传 GitHub”误解为“不提取本地音频”",
        "验证门禁",
    ):
        assert required in troubleshooting
    assert "$oumuq-tts-character-creator" in openai_yaml
    assert skill_text.count('"api_target_model": "qwen3-tts-vd-2026-01-26"') == 1
    assert skill_text.count('"api_target_model": "qwen3-tts-vc-2026-01-22"') == 1
    validator_text = (SKILL / "scripts" / "validate_character.py").read_text(encoding="utf-8")
    assert "云端 Voice Design 仍可继续进行 WAV 验证" in validator_text
    assert "无法完成音色试听" not in validator_text


def test_skill_separates_local_audio_cloud_clone_and_github_publication() -> None:
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    openai_yaml = (SKILL / "agents" / "openai.yaml").read_text(encoding="utf-8")
    troubleshooting = (SKILL / "references" / "troubleshooting.md").read_text(
        encoding="utf-8"
    )
    qwen_skill = (SKILL.parent / "qwen-tts-api" / "SKILL.md").read_text(encoding="utf-8")

    assert "保存到本机" in skill_text
    assert "提交给阿里云百炼做克隆" in skill_text
    assert "上传到 GitHub" in skill_text
    assert "先把参考音频提取到本机私有目录" in skill_text
    assert "不得改成 Voice Design 冒充克隆" in skill_text
    assert "只有用户明确要求原创音色时" in skill_text
    assert "默认使用 Qwen 声音设计" not in skill_text
    assert "声音设计（默认" not in qwen_skill
    assert "不需要 GitHub、公开 URL 或公网对象存储" in qwen_skill
    assert "不得把“不上传 GitHub/公网”解释为“不提取本地音频”" in qwen_skill
    assert "先把参考音频提取到本机私有 voice-references" in openai_yaml
    assert "skill、代码和脱敏模板可以上传 GitHub" in openai_yaml
    assert "真实 TTS 参考音频不得放到 GitHub、公开 URL 或公网对象存储" in openai_yaml
    assert "把“不上传 GitHub”误解为“不提取本地音频”" in troubleshooting
    assert "发布扫描必须允许 skill 文件" in troubleshooting
    assert "Data URL 克隆调用变成 0" in troubleshooting
    assert "旧配置或仅人格包不得据此触发注册" in troubleshooting
