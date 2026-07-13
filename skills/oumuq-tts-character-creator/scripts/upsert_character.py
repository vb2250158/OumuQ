from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


REQUIRED = ("id", "name", "display_name_zh", "character_folder", "index_file", "tts_engine", "worker_url", "speech_language", "visible_language", "style_summary", "style_summary_zh")


def main() -> int:
    parser = argparse.ArgumentParser(description="结构化新增或更新 OumuQ 角色注册表")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--entry-file", required=True, type=Path)
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    registry_path = workspace / "voice-references" / "reference-index.json"
    entry = json.loads(args.entry_file.read_text(encoding="utf-8-sig"))
    if not isinstance(entry, dict):
        raise SystemExit("entry-file 顶层必须是 object")
    missing = [field for field in REQUIRED if not entry.get(field)]
    if missing:
        raise SystemExit(f"角色条目缺少字段：{missing}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(entry["id"])):
        raise SystemExit("角色 ID 必须是路径安全的小写标识")
    for field in ("character_folder", "index_file"):
        target = (workspace / entry[field]).resolve()
        if workspace not in target.parents or not target.exists():
            raise SystemExit(f"{field} 路径越界或不存在：{entry[field]}")

    registry = json.loads(registry_path.read_text(encoding="utf-8-sig")) if registry_path.exists() else {"version": 1, "root": "voice-references", "characters": []}
    characters = registry.setdefault("characters", [])
    matches = [index for index, item in enumerate(characters) if str(item.get("id", "")).lower() == entry["id"].lower()]
    if len(matches) > 1:
        raise SystemExit(f"注册表已有重复角色 ID：{entry['id']}")
    action = "update" if matches else "create"
    if matches:
        characters[matches[0]] = {**characters[matches[0]], **entry}
    else:
        characters.append(entry)
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "action": action, "id": entry["id"]}, ensure_ascii=False))
        return 0
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if args.backup and registry_path.exists():
        shutil.copy2(registry_path, registry_path.with_suffix(".json.bak"))
    temporary = registry_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(registry_path)
    print(json.dumps({"ok": True, "action": action, "id": entry["id"], "registry": str(registry_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
