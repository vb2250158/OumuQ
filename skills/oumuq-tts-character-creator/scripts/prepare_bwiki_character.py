from __future__ import annotations

import argparse
import shutil
import hashlib
import io
import json
import re
import wave
from pathlib import Path
from urllib.request import Request, urlopen


LANG = {
    "cn": ("Chinese", "cn", "urlCn"),
    "ja": ("Japanese", "ja", "urlJa"),
    "ko": ("Korean", "ko", "urlKo"),
}


def clean(value: str | None) -> str:
    return re.sub(r"(?:<br\s*/?>|<p>)", "\n", value or "", flags=re.I).strip()


def mood_for(item: dict) -> tuple[list[str], list[float]]:
    token = f"{item.get('id', '')} {item.get('key', '')} {item.get('type', '')}".lower()
    if re.search(r"fail|death|collapse|stress|失败|崩溃|压力|呻吟", token):
        return ["sad", "stressed"], [0.0, 0.05, 0.42, 0.22, 0.0, 0.12, 0.0, 0.08]
    if re.search(r"attack|skill|turn|defense|buff|card|攻击|必杀|防御|战斗|技能|卡牌", token):
        return ["determined", "energetic"], [0.58, 0.0, 0.0, 0.12, 0.0, 0.0, 0.03, 0.18]
    if re.search(r"gacha|lobby|touch|talk|manage|问候|闲聊|点击|详细", token):
        return ["friendly", "conversational"], [0.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.02, 0.35]
    return ["neutral"], [0.35, 0.0, 0.0, 0.0, 0.0, 0.0, 0.02, 0.25]


def patterns_for(item: dict, text: str) -> list[str]:
    token = str(item.get("id") or "").lower()
    rules = [
        (r"gacha", r"初次见面|又见面|自我介绍"),
        (r"manage", r"管理|帮忙|协助|整理文件"),
        (r"stage_success", r"成功|完成|做到了"),
        (r"stage_fail", r"失败|对不起|抱歉|我的错"),
        (r"lobby_enter_02", r"新年|节日|庆祝"),
        (r"lobby_enter_03", r"圣诞|礼物|圣诞老人"),
        (r"touch_02", r"无聊|故事|陪伴"),
        (r"small_talk_03", r"辛苦|太累|工作|分担|文件"),
        (r"small_talk_04", r"咖啡|糖|饮料"),
        (r"story_moment", r"报告|文件|整理|帮忙|紧急"),
        (r"collapse|death|stress", r"害怕|崩溃|压力|不要|消失"),
        (r"attack|skill|card|turn|defense|buff", r"战斗|攻击|技能|准备|实力"),
        (r"captain_call", r"呼唤舰长|叫我|称呼"),
    ]
    patterns = [pattern for matcher, pattern in rules if re.search(matcher, token)]
    if not patterns:
        title = str(item.get("key") or item.get("type") or "").strip()
        if len(title) >= 3 and title not in {"详细信息问候", "配置队伍"}:
            patterns.append(re.escape(title))
    return patterns or [re.escape(text[:12])] if text else [re.escape(token)]


def write_json_atomic(path: Path, value, backup: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def build_profile_evidence(source: dict, character_id: str) -> dict:
    profile = source.get("profile") or {}
    evidence = []
    labels = {
        "race_type": "种族", "birth": "生日", "specialty": "异能", "faction": "所属势力",
        "sub_faction": "子势力", "nickname": "昵称", "cv_zhs": "中文配音", "cv_ja": "日文配音", "cv_ko": "韩文配音",
    }
    structured = {}
    for field, label in labels.items():
        value = profile.get(field)
        values = value if isinstance(value, list) else [value] if value else []
        if values:
            structured[field] = values
    if structured:
        excerpt = "；".join(f"{labels[field]}：{'、'.join(map(str, values))}" for field, values in structured.items())
        evidence.append({
            "id": "profile-identity", "kind": "community-wiki-structured-profile", "authority": "community_wiki",
            "directness": "explicit_page_statement", "excerpt": excerpt, "structured_values": structured,
        })
    background = clean(profile.get("background_text"))
    sentences = [part.strip() for part in re.split(r"(?<=[。！？])\s*|\n+", background) if part.strip()]
    for index, sentence in enumerate(sentences, 1):
        evidence.append({
            "id": f"profile-background-{index:02d}", "kind": "community-wiki-profile", "authority": "community_wiki",
            "directness": "explicit_page_statement", "excerpt": sentence,
        })
    return {
        "schema_version": 1, "character_id": character_id, "source_url": source.get("page_url") or source.get("source"),
        "page_revision": source.get("page_revision"), "profile_source": source.get("profile_source"), "evidence": evidence,
    }


def download(url: str, target: Path) -> dict:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://wiki.biligame.com/czn/"})
    with urlopen(req, timeout=45) as response:
        data = response.read()
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"BWIKI 音频不是有效 WAV：{url} ({len(data)} bytes)")
    duration = None
    sample_rate = None
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as wav:
            sample_rate = wav.getframerate()
            duration = wav.getnframes() / sample_rate
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "duration_seconds": duration, "sample_rate": sample_rate}


def main() -> int:
    parser = argparse.ArgumentParser(description="把 BWIKI 提取结果变成 OumuQ 语音索引和证据包")
    parser.add_argument("--extract", required=True, type=Path)
    parser.add_argument("--character-dir", required=True, type=Path)
    parser.add_argument("--character-id", required=True)
    parser.add_argument("--language", choices=LANG, default="cn")
    parser.add_argument("--download", action="store_true", help="下载目标语言中公开列出的音频到本机私有角色目录")
    parser.add_argument("--rights-status", choices=("unknown", "user-requested-private-use", "confirmed"), default="unknown")
    parser.add_argument("--replace", action="store_true", help="不合并既有人工/音频字段，完整替换索引")
    parser.add_argument("--backup", action="store_true", help="写入前保存 .bak")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source = json.loads(args.extract.read_text(encoding="utf-8-sig"))
    entries = source.get("entries") or source.get("voice_root_entries") or []
    if not entries:
        raise SystemExit("失败：提取包没有语音条目")

    language, text_field, url_field = LANG[args.language]
    audio_dir = args.character_dir / "audio" / f"bwiki_{args.language}"
    voice_index = []
    evidence_lines = []
    downloads = []
    existing_path = args.character_dir / "voice-index.json"
    existing_evidence_path = args.character_dir / "character-evidence.json"
    existing_evidence = {}
    if existing_evidence_path.is_file() and not args.replace:
        value = json.loads(existing_evidence_path.read_text(encoding="utf-8-sig"))
        existing_evidence = value if isinstance(value, dict) else {}
    existing = {}
    if existing_path.is_file() and not args.replace:
        current = json.loads(existing_path.read_text(encoding="utf-8-sig"))
        if isinstance(current, list):
            existing = {str(item.get("id")): item for item in current if isinstance(item, dict) and item.get("id")}

    for item in entries:
        item_id = str(item.get("id") or item.get("key") or "").strip()
        if not item_id:
            continue
        text = clean(item.get(text_field))
        mood, vector = mood_for(item)
        record = {
            "id": item_id,
            "title": item.get("key") or item.get("type") or item_id,
            "language": language,
            "text": text,
            "text_zh": clean(item.get("cn")),
            "text_ja": clean(item.get("ja")),
            "text_ko": clean(item.get("ko")),
            "voice_key": item.get("key") or item.get("type"),
            "base_name": item.get("baseName") or item.get("file") or item.get("type"),
            "idx": item.get("idx"),
            "source_audio_url_cn": item.get("urlCn"),
            "source_audio_url_ja": item.get("urlJa"),
            "source_audio_url_ko": item.get("urlKo"),
            "source_audio_meta_cn": item.get("audio_meta_cn"),
            "source_audio_meta_ja": item.get("audio_meta_ja"),
            "source_audio_meta_ko": item.get("audio_meta_ko"),
            "mood": mood,
            "emotion_tags": mood,
            "emotion_vector": vector,
            "match_patterns": patterns_for(item, text),
            "style_notes": "从 BWIKI voice-player-root 数据提取；仅作本机私有参考，重新分发或训练前确认权利。",
        }
        url = item.get(url_field)
        prior = existing.get(item_id, {})
        if not args.replace:
            for key in ("audio_file", "audio_sha256", "duration_seconds", "sample_rate", "manual_notes", "quality_tags"):
                if key in prior:
                    record[key] = prior[key]
        if args.download and url and not args.dry_run:
            filename = f"{item_id}_{args.language}.wav"
            target = audio_dir / filename
            meta = download(url, target)
            record["audio_file"] = f"voice-references/characters/{args.character_id}/audio/bwiki_{args.language}/{filename}"
            record["audio_sha256"] = meta["sha256"]
            record["duration_seconds"] = meta["duration_seconds"]
            record["sample_rate"] = meta["sample_rate"]
            downloads.append({"id": item_id, "url": url, "file": f"audio/bwiki_{args.language}/{filename}", **meta})
        voice_index.append(record)
        if text:
            evidence_lines.append({"id": item_id, "label": item.get("key") or item.get("type") or item_id, "text": text, "language": language})

    if args.dry_run:
        print(json.dumps({"dry_run": True, "voice_entries": len(voice_index), "would_download": sum(bool(item.get(url_field)) for item in entries)}, ensure_ascii=False))
        return 0
    args.character_dir.mkdir(parents=True, exist_ok=True)
    if not downloads and not args.replace:
        downloads = list(existing_evidence.get("downloads") or [])
    rights_status = args.rights_status
    if rights_status == "unknown" and not args.replace:
        rights_status = existing_evidence.get("rights_status") or rights_status
    evidence = {
        "schema_version": 1,
        "character_id": args.character_id,
        "source_url": source.get("source") or source.get("page_url"),
        "voice_entry_count": len(entries),
        "indexed_entry_count": len(voice_index),
        "downloaded_audio_count": len(downloads),
        "evidence_lines": evidence_lines,
        "downloads": downloads,
        "rights_status": rights_status,
        "rights_note": "该状态只描述本地工作流确认，不授予训练、再分发或公开克隆权利。",
        "required_profile_sections": ["identity_facts", "persona_traits", "speech_patterns", "address_terms", "emotional_modes", "boundaries"],
        "profile_rule": "character-profile.json 的每个推断必须引用 evidence_lines 中存在的 id；无证据的事实必须标记 unverified。",
    }
    write_json_atomic(args.character_dir / "voice-index.json", voice_index, backup=args.backup)
    write_json_atomic(args.character_dir / "character-evidence.json", evidence, backup=args.backup)
    if source.get("profile"):
        write_json_atomic(args.character_dir / "profile-evidence.json", build_profile_evidence(source, args.character_id), backup=args.backup)
    print(json.dumps({"voice_entries": len(voice_index), "evidence_lines": len(evidence_lines), "downloaded": len(downloads)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
