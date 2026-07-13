from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
import wave


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser(description="严格验证 OumuQ 证据化角色条目")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--character-dir", type=Path, help="仅验证独立角色包；可配合 --skip-registry")
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-registry", action="store_true")
    args = parser.parse_args()
    if not args.workspace and not args.character_dir:
        parser.error("--workspace 与 --character-dir 至少提供一个")
    workspace = args.workspace.resolve() if args.workspace else None
    root = workspace / "voice-references" if workspace else None
    registry_path = root / "reference-index.json" if root is not None else None
    registry = (
        load(registry_path)
        if registry_path is not None and registry_path.is_file() and not args.skip_registry
        else None
    )
    registry_entries = [
        item
        for item in (registry.get("characters", []) if isinstance(registry, dict) else [])
        if str(item.get("id", "")).lower() == args.character_id.lower()
    ]
    if args.character_dir:
        folder = args.character_dir.resolve()
    elif workspace is not None and len(registry_entries) == 1 and registry_entries[0].get("character_folder"):
        folder = (workspace / str(registry_entries[0]["character_folder"])).resolve()
    else:
        folder = root / "characters" / args.character_id
    errors: list[str] = []
    warnings: list[str] = []
    required = [folder / "README.md", folder / "voice-index.json", folder / "character-evidence.json", folder / "character-profile.json"]
    if not args.skip_registry:
        if root is None:
            errors.append("注册表验证需要 --workspace，或使用 --skip-registry")
        else:
            required.append(root / "reference-index.json")
    if args.strict and not (folder / "source-bundle.json").is_file() and not (folder / "bwiki-voice-extract.json").is_file():
        errors.append("严格模式至少需要 source-bundle.json 或 bwiki-voice-extract.json")
    for path in required:
        if not path.is_file():
            errors.append(f"缺少文件：{path}")
    if errors:
        print("\n".join(errors))
        return 1

    voice = load(folder / "voice-index.json")
    if not isinstance(voice, list):
        errors.append("voice-index.json 顶层必须是数组")
        voice = []
    evidence = load(folder / "character-evidence.json")
    profile = load(folder / "character-profile.json")
    evidence_list = evidence.get("evidence_lines", [])
    evidence_ids = {str(item.get("id")) for item in evidence_list}
    if len(evidence_ids) != len(evidence_list):
        errors.append("character-evidence.json 存在重复证据 ID")
    profile_evidence_path = folder / "profile-evidence.json"
    if profile_evidence_path.is_file():
        profile_evidence = load(profile_evidence_path)
        profile_items = profile_evidence.get("evidence", [])
        profile_ids = [str(item.get("id")) for item in profile_items]
        if len(profile_ids) != len(set(profile_ids)):
            errors.append("profile-evidence.json 存在重复证据 ID")
        evidence_ids.update(profile_ids)
        bwiki_path = folder / "bwiki-voice-extract.json"
        bwiki_profile = load(bwiki_path).get("profile", {}) if bwiki_path.is_file() else {}
        source_bundle_path = folder / "source-bundle.json"
        source_text = "\n".join(item.get("text", "") for item in load(source_bundle_path).get("sources", [])) if source_bundle_path.is_file() else ""
        if not source_text and bwiki_profile:
            source_text = str(bwiki_profile.get("background_text") or "")
        normalized_source = re.sub(r"\s+", "", source_text)
        for item in profile_items:
            if item.get("kind") == "community-wiki-profile" and re.sub(r"\s+", "", str(item.get("excerpt", ""))) not in normalized_source:
                errors.append(f"资料证据原文未出现在 source-bundle：{item.get('id')}")
            for field, values in (item.get("structured_values") or {}).items():
                source_values = bwiki_profile.get(field)
                source_values = source_values if isinstance(source_values, list) else [source_values] if source_values else []
                if list(values) != list(source_values):
                    errors.append(f"资料证据结构化值与 BWIKI 提取包不一致：{item.get('id')}:{field}")
    source_bundle_path = folder / "source-bundle.json"
    if source_bundle_path.is_file():
        source_bundle = load(source_bundle_path)
        if args.strict and source_bundle.get("status") not in {None, "success"}:
            errors.append(f"source-bundle 状态不是 success：{source_bundle.get('status')}")
        if args.strict and source_bundle.get("failures"):
            errors.append("source-bundle 存在失败来源")

    if evidence.get("voice_entry_count", 0) and not voice:
        errors.append("来源包含语音，但 voice-index.json 为空")
    expected_sections = ["identity_facts", "persona_traits", "speech_patterns", "address_terms", "emotional_modes", "preferences", "boundaries"]
    for section in expected_sections:
        if section not in profile:
            errors.append(f"character-profile.json 缺少固定章节：{section}")
    for section in evidence.get("required_profile_sections", []):
        values = profile.get(section)
        if values is None:
            errors.append(f"character-profile.json 缺少章节：{section}")
            continue
        for index, claim in enumerate(values if isinstance(values, list) else []):
            refs = {str(x) for x in claim.get("evidence_ids", [])}
            confidence = claim.get("confidence")
            if confidence not in {"high", "medium", "low", "unverified"}:
                errors.append(f"{section}[{index}] confidence 非法：{confidence}")
            if confidence != "unverified" and not refs:
                errors.append(f"{section}[{index}] 没有证据引用")
            missing = refs - evidence_ids
            if missing:
                errors.append(f"{section}[{index}] 引用了不存在的证据：{sorted(missing)}")

    if registry is not None:
        all_characters = registry.get("characters", [])
        case_ids = [str(item.get("id", "")).lower() for item in all_characters]
        if len(case_ids) != len(set(case_ids)):
            errors.append("注册表存在大小写不敏感的重复角色 ID")
        entries = [item for item in all_characters if str(item.get("id", "")).lower() == args.character_id.lower()]
        if len(entries) != 1:
            errors.append(f"注册表中角色数量应为 1，实际为 {len(entries)}")
            entries = []
    else:
        entries = []
    if entries:
        entry = entries[0]
        for field in ("name", "display_name_zh", "character_folder", "index_file", "tts_engine", "worker_url", "speech_language", "visible_language", "style_summary", "style_summary_zh"):
            if not entry.get(field):
                errors.append(f"注册表缺少字段：{field}")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(entry.get("id", ""))):
            errors.append("角色 ID 必须是路径安全的小写字母、数字、下划线或连字符")
        for field in ("character_folder", "index_file"):
            value = entry.get(field)
            if value:
                resolved = (workspace / value).resolve()
                if workspace not in resolved.parents:
                    errors.append(f"{field} 路径越界：{value}")
                elif not resolved.exists():
                    errors.append(f"{field} 不存在：{value}")
        fallback = entry.get("fallback_prompt_audio")
        if fallback and not (workspace / fallback).is_file():
            errors.append(f"fallback_prompt_audio 不存在：{fallback}")
        elif fallback and (workspace / fallback).suffix.lower() == ".wav":
            with wave.open(str(workspace / fallback), "rb") as wav:
                duration = wav.getnframes() / wav.getframerate()
            if duration < 6:
                warnings.append(f"fallback_prompt_audio 仅 {duration:.2f}s，建议选择 6-20s 片段")
        if not entry.get("style_summary_zh"):
            errors.append("注册表缺少 style_summary_zh")

        engine_key = str(entry.get("tts_engine") or "").strip().lower()
        if engine_key in {"qwen-tts-api", "qwen_tts_api", "qwen-api"}:
            target_model = entry.get("api_target_model") or entry.get("api_clone_target_model")
            enrollment_model = entry.get("api_enrollment_model")
            creation_method = entry.get("api_voice_creation_method")
            if not target_model:
                errors.append("Qwen-TTS-API 角色缺少实际合成模型 api_target_model/api_clone_target_model")
            if not entry.get("api_clone_language_hint") and not entry.get("api_voice_design_language"):
                errors.append("Qwen-TTS-API 角色缺少语言提示")
            if entry.get("fallback_prompt_audio"):
                errors.append("云端角色不得携带本地 fallback_prompt_audio")

            if str(target_model).startswith("qwen3-tts-vd-"):
                if enrollment_model != "qwen-voice-design":
                    errors.append("Qwen3-TTS-VD 必须使用 qwen-voice-design")
                if creation_method not in {None, "voice_design"}:
                    errors.append("Qwen3-TTS-VD 的 api_voice_creation_method 必须是 voice_design")
                if not entry.get("api_voice_id"):
                    if not entry.get("api_voice_prompt") or not entry.get("api_voice_preview_text"):
                        errors.append("未注册的 Qwen 声音设计角色需要 api_voice_prompt 与 api_voice_preview_text")
            elif str(target_model).startswith("qwen3-tts-vc-"):
                if enrollment_model != "qwen-voice-enrollment":
                    errors.append("Qwen3-TTS-VC 必须使用 qwen-voice-enrollment")
                if creation_method not in {None, "voice_cloning"}:
                    errors.append("Qwen3-TTS-VC 的 api_voice_creation_method 必须是 voice_cloning")
                if not entry.get("api_voice_id") and not (
                    entry.get("api_clone_audio_url") or entry.get("api_clone_audio_path")
                ):
                    errors.append("未注册的 Qwen 声音复刻角色需要 voice ID 或授权参考音频")
            elif str(target_model).startswith("cosyvoice-"):
                if enrollment_model not in {None, "voice-enrollment"}:
                    errors.append("CosyVoice 克隆必须使用 voice-enrollment")
                if not entry.get("api_voice_id") and not entry.get("api_clone_audio_url"):
                    errors.append("未注册的 CosyVoice 云角色需要 voice ID 或公网参考音频 URL")
            elif not entry.get("api_voice_id"):
                errors.append("Qwen-TTS-API 角色缺少 api_voice_id")

    voice_ids = [str(item.get("id", "")) for item in voice]
    if len(voice_ids) != len(set(voice_ids)):
        errors.append("voice-index.json 存在重复 ID")
    for item in voice:
        for field in ("id", "title", "language", "text"):
            if not item.get(field):
                errors.append(f"语音条目 {item.get('id')} 缺少 {field}")
        vector = item.get("emotion_vector")
        if not isinstance(vector, list) or len(vector) != 8 or any(not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 or x > 1 for x in vector):
            errors.append(f"{item.get('id')} 的 emotion_vector 必须是 8 个 0-1 有限数字")
        patterns = item.get("match_patterns")
        if not isinstance(patterns, list) or not patterns or any(not isinstance(x, str) or not x for x in patterns):
            errors.append(f"{item.get('id')} 缺少 match_patterns")
        else:
            for pattern in patterns:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"{item.get('id')} 的正则无效：{pattern}：{exc}")
        audio = item.get("audio_file")
        if audio:
            if workspace is None:
                parts = Path(audio).parts
                if len(parts) >= 4 and parts[:3] == ("voice-references", "characters", args.character_id):
                    resolved_audio = (folder / Path(*parts[3:])).resolve()
                else:
                    errors.append(f"独立角色包的 audio_file 无法映射到角色目录：{audio}")
                    continue
                allowed_root = folder
            else:
                resolved_audio = (workspace / audio).resolve()
                allowed_root = workspace
            if allowed_root not in resolved_audio.parents:
                errors.append(f"音频路径越界：{audio}")
                continue
            if not resolved_audio.is_file():
                errors.append(f"语音索引文件不存在：{audio}")
                continue
            try:
                with wave.open(str(resolved_audio), "rb") as wav:
                    actual_duration = wav.getnframes() / wav.getframerate()
                    actual_rate = wav.getframerate()
            except (wave.Error, EOFError) as exc:
                errors.append(f"WAV 不可解码：{audio}：{exc}")
                continue
            if not item.get("audio_sha256") or item.get("duration_seconds") is None or item.get("sample_rate") is None:
                errors.append(f"音频条目缺少哈希/时长/采样率：{audio}")
            actual = hashlib.sha256(resolved_audio.read_bytes()).hexdigest()
            if item.get("audio_sha256") and actual != item.get("audio_sha256"):
                errors.append(f"音频哈希不匹配：{audio}")
            if abs(float(item.get("duration_seconds") or 0) - actual_duration) > 0.02:
                errors.append(f"音频时长不匹配：{audio}")
            if int(item.get("sample_rate") or 0) != actual_rate:
                errors.append(f"音频采样率不匹配：{audio}")
            language_key = {"Chinese": "cn", "Japanese": "ja", "Korean": "ko"}.get(str(item.get("language")))
            source_meta = item.get(f"source_audio_meta_{language_key}") if language_key else None
            if source_meta and source_meta.get("sha1"):
                actual_sha1 = hashlib.sha1(resolved_audio.read_bytes()).hexdigest()
                if actual_sha1 != source_meta["sha1"]:
                    errors.append(f"音频 SHA1 与 BWIKI imageinfo 不匹配：{audio}")
    if args.strict and evidence.get("voice_entry_count", 0) != len(voice):
        errors.append(f"严格模式：来源语音 {evidence.get('voice_entry_count')} 条，索引 {len(voice)} 条")
    if not any(item.get("audio_file") for item in voice):
        warnings.append("没有本地参考音频；本地参考音色未验证，云端 Voice Design 仍可继续进行 WAV 验证")
    elif evidence.get("rights_status") == "unknown":
        errors.append("已有本地参考音频，但 rights_status 仍为 unknown")

    report = {"ok": not errors, "character_id": args.character_id, "voice_entries": len(voice), "evidence_ids": len(evidence_ids), "errors": errors, "warnings": warnings}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
