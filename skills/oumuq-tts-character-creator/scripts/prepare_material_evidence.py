from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path


def atomic_json(path: Path, value, backup: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def segments(text: str) -> list[dict]:
    result = []
    offset = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            offset += len(line) + 1
            continue
        cursor = 0
        pieces = [part.strip() for part in re.findall(r".+?(?:[。！？!?]+[’”」』】）)]*|$)", stripped) if part.strip()]
        for sentence in pieces:
            local = stripped.find(sentence, cursor)
            start = offset + max(local, 0)
            end = start + len(sentence)
            result.append({"line": line_number, "char_start": start, "char_end": end, "text": sentence})
            cursor = max(local, 0) + len(sentence)
        offset += len(line) + 1
    return result


def kurobbs_voice_entries(source: dict) -> list[dict]:
    if source.get("method") != "kurobbs-entry-detail-api":
        return []
    in_voice = False
    category = ""
    language = ""
    pending_label = ""
    pending_text: list[str] = []
    raw_entries: list[tuple[str, str, str, str]] = []

    def flush() -> None:
        nonlocal pending_label, pending_text
        text = " ".join(part for part in pending_text if part).strip()
        if pending_label and text:
            raw_entries.append((category, language, pending_label, text))
        pending_label = ""
        pending_text = []

    for line in str(source.get("text") or "").splitlines():
        stripped = line.strip()
        if stripped == "# 角色语音":
            flush()
            in_voice = True
            continue
        if not in_voice:
            continue
        if stripped.startswith("# "):
            flush()
            break
        if stripped.startswith("## "):
            flush()
            category = stripped[3:].strip()
            continue
        if stripped.startswith("### "):
            flush()
            language = stripped[4:].strip()
            continue
        label = re.fullmatch(r"【(.+)】", stripped)
        if label:
            flush()
            pending_label = label.group(1).strip()
            continue
        if pending_label and stripped:
            pending_text.append(stripped)
    flush()

    entries = []
    for category, language, title, text in raw_entries:
        if not language.startswith("中文"):
            continue
        category_key = "personality" if category == "个性语音" else "combat" if category == "战斗语音" else "voice"
        identity_source = "\0".join((category, language, title, text))
        stable_id = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:12]
        is_combat = category_key == "combat"
        entries.append({
            "id": f"kurobbs-{category_key}-{stable_id}",
            "title": title,
            "category": category,
            "language": "Chinese",
            "text": text,
            "text_zh": text,
            "mood": ["calm", "determined"] if is_combat else ["calm", "reflective"],
            "emotion_tags": ["calm", "determined"] if is_combat else ["calm", "reflective"],
            "emotion_vector": [0.25, 0.05 if is_combat else 0.0, 0.0, 0.0, 0.0, 0.0, 0.02, 0.35],
            "match_patterns": [re.escape(title)],
            "source_id": source.get("id"),
            "source_method": source.get("method"),
            "style_notes": "从库街区官方接口提取台词文字；未保存、下载或使用页面音频。",
        })
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="把通用 source-bundle 转成带精确 locator 的角色证据")
    parser.add_argument("--source-bundle", required=True, type=Path)
    parser.add_argument("--character-dir", required=True, type=Path)
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--backup", action="store_true")
    parser.add_argument(
        "--refresh-generated-voice-index",
        action="store_true",
        help="仅当现有索引全部是无音频的库街区生成条目时，用稳定内容 ID 刷新索引",
    )
    args = parser.parse_args()
    bundle = json.loads(args.source_bundle.read_text(encoding="utf-8-sig"))
    if not bundle.get("sources"):
        raise SystemExit("source-bundle 没有成功来源")
    evidence_lines = []
    voice_entries = []
    for source in bundle["sources"]:
        source_id = str(source.get("id") or "source")
        voice_entries.extend(kurobbs_voice_entries(source))
        for index, segment in enumerate(segments(str(source.get("text") or "")), 1):
            evidence_lines.append({
                "id": f"{source_id}-e{index:03d}", "source_id": source_id, "source": source.get("source"),
                "source_sha256": source.get("sha256"), "method": source.get("method"), **segment,
            })
    evidence = {
        "schema_version": 1, "character_id": args.character_id, "source_bundle": str(args.source_bundle),
        "source_status": bundle.get("status"), "voice_entry_count": len(voice_entries), "indexed_entry_count": len(voice_entries),
        "downloaded_audio_count": 0, "evidence_lines": evidence_lines, "downloads": [], "rights_status": "not_applicable",
        "required_profile_sections": ["identity_facts", "persona_traits", "speech_patterns", "address_terms", "emotional_modes", "preferences", "boundaries"],
        "profile_rule": "每项资料事实与人格推断必须引用真实 evidence id；无证据内容标记 unverified。",
    }
    args.character_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(args.character_dir / "character-evidence.json", evidence, args.backup)
    voice_index = args.character_dir / "voice-index.json"
    current_voice = json.loads(voice_index.read_text(encoding="utf-8-sig")) if voice_index.exists() else []
    if args.refresh_generated_voice_index and current_voice:
        unsafe = [
            item.get("id")
            for item in current_voice
            if item.get("source_method") != "kurobbs-entry-detail-api" or item.get("audio_file")
        ]
        if unsafe:
            raise SystemExit(f"拒绝刷新包含手工/音频条目的 voice-index：{unsafe[:5]}")
    if voice_entries and (not current_voice or args.refresh_generated_voice_index):
        atomic_json(voice_index, voice_entries, args.backup)
    elif not voice_index.exists():
        atomic_json(voice_index, [], False)
    print(json.dumps({
        "ok": True,
        "sources": len(bundle["sources"]),
        "evidence_lines": len(evidence_lines),
        "voice_entries": len(voice_entries),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
