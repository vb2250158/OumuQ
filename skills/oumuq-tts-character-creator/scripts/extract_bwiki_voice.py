from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API = "https://wiki.biligame.com/czn/api.php"
PROFILE_FIELDS = ("combatant_id", "name", "nickname", "background_text", "birth", "cv_zhs", "cv_ja", "cv_ko", "race_type", "specialty", "faction", "sub_faction")


def fetch(url: str, expect_json: bool = False, retries: int = 2) -> tuple[str, dict]:
    last: Exception | None = None
    for attempt in range(retries + 1):
        request = Request(url, headers={
            "User-Agent": "Mozilla/5.0 Chrome/126.0 Safari/537.36",
            "Accept": "application/json,text/html,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://wiki.biligame.com/czn/",
        })
        try:
            with urlopen(request, timeout=35) as response:
                raw = response.read().decode("utf-8", errors="replace")
                headers = dict(response.headers.items())
            if expect_json and (raw.lstrip().startswith("<") or "application/json" not in headers.get("Content-Type", "")):
                raise RuntimeError(f"edge_blocked_or_non_json eo={headers.get('EO-LOG-UUID', '')}")
            return raw, headers
        except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
            last = exc
            status = getattr(exc, "code", None)
            if status in {403, 412} or attempt >= retries:
                break
            time.sleep(0.8 * (2**attempt))
    raise RuntimeError(f"请求失败：{url}：{last}")


def api_json(params: dict) -> dict:
    raw, _ = fetch(API + "?" + urlencode(params), expect_json=True)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("API 返回不是 JSON object")
    return value


def clean_html(value: str | None) -> str:
    value = re.sub(r"<br\s*/?>|</p>", "\n", value or "", flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return "\n".join(re.sub(r"\s+", " ", unescape(line)).strip() for line in value.splitlines() if line.strip())


def first(values):
    return values[0] if isinstance(values, list) and values else None


def profile_by_title(title: str) -> dict:
    data = api_json({"action": "askargs", "conditions": title, "printouts": "|".join(PROFILE_FIELDS), "format": "json"})
    results = data.get("query", {}).get("results", {})
    for result in results.values():
        printouts = result.get("printouts", {})
        combatant_id = first(printouts.get("combatant_id"))
        if combatant_id:
            profile = {field: printouts.get(field) for field in PROFILE_FIELDS}
            profile["combatant_id"] = str(combatant_id)
            profile["name"] = first(printouts.get("name")) or result.get("fulltext") or title
            profile["canonical_title"] = result.get("fulltext") or profile["name"]
            profile["canonical_url"] = result.get("fullurl")
            profile["background_text_raw"] = first(printouts.get("background_text")) or ""
            profile["background_text"] = clean_html(profile["background_text_raw"])
            return profile
    raise ValueError(f"SMW 未找到有效 combatant_id：{title}")


def profile_by_id(combatant_id: str) -> dict | None:
    query = f"[[combatant_id::{combatant_id}]]" + "".join(f"|?{field}" for field in PROFILE_FIELDS if field != "combatant_id")
    data = api_json({"action": "ask", "query": query, "format": "json"})
    results = data.get("query", {}).get("results", {})
    if not results:
        return None
    result = next(iter(results.values()))
    printouts = result.get("printouts", {})
    normalized = {re.sub(r"\s+", "_", key).lower(): value for key, value in printouts.items()}
    raw_background = first(normalized.get("background_text")) or ""
    return {
        "combatant_id": combatant_id,
        "name": first(normalized.get("name")) or result.get("fulltext"),
        "canonical_title": result.get("fulltext"),
        "canonical_url": result.get("fullurl"),
        "background_text_raw": raw_background,
        "background_text": clean_html(raw_background),
        **normalized,
    }


def recover_profile_by_search(title: str) -> dict:
    candidates = []
    queries = [title]
    compact = re.sub(r"\s+", "", title)
    if len(compact) >= 2:
        queries.append(compact[:2])
    for query in queries:
        data = api_json({
            "action": "query", "list": "prefixsearch", "pssearch": query,
            "psnamespace": 0, "pslimit": 10, "format": "json", "formatversion": 2,
        })
        for item in data.get("query", {}).get("prefixsearch", []):
            candidate = item.get("title")
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        if candidates:
            break
    profiles = []
    for candidate in candidates:
        try:
            profile = profile_by_title(candidate)
            if profile and all(profile.get("combatant_id") != item.get("combatant_id") for item in profiles):
                profiles.append(profile)
        except Exception:
            continue
    if len(profiles) != 1:
        names = [item.get("canonical_title") for item in profiles]
        raise ValueError(f"页面名恢复不唯一：候选={names or candidates}")
    profiles[0]["input_alias"] = title
    return profiles[0]


def revision(title: str) -> dict:
    data = api_json({"action": "query", "titles": title, "prop": "revisions", "rvprop": "ids|timestamp", "format": "json", "formatversion": 2})
    page = (data.get("query", {}).get("pages") or [{}])[0]
    rev = (page.get("revisions") or [{}])[0]
    return {"title": page.get("title"), "pageid": page.get("pageid"), "revid": rev.get("revid"), "timestamp": rev.get("timestamp"), "missing": bool(page.get("missing"))}


def root_payloads(html: str) -> list[dict]:
    roots = []
    for match in re.finditer(r"<div\b[^>]*class=['\"][^'\"]*\bvoice-player-root\b[^'\"]*['\"][^>]*>", html, re.I):
        tag = match.group(0)
        attrs = {key.lower(): unescape(value) for key, _, value in re.findall(r"([\w-]+)\s*=\s*(['\"])(.*?)\2", tag, re.S)}
        try:
            entries = json.loads(attrs.get("data-entries", "[]").replace("https&#58;//", "https://").replace("https&colon;//", "https://"))
            types = json.loads(attrs.get("data-types", "[]"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"voice-player-root JSON 无效：{exc}") from exc
        roots.append({"char_id": attrs.get("data-char-id"), "total": int(attrs.get("data-total") or len(entries)), "entries": entries, "types": types})
    return roots


def voice_by_module(combatant_id: str) -> tuple[list[dict], str]:
    text = "{{#invoke:Voice|main|" + combatant_id + "}}"
    data = api_json({"action": "expandtemplates", "text": text, "prop": "wikitext", "format": "json", "formatversion": 2})
    return root_payloads(data.get("expandtemplates", {}).get("wikitext", "")), "expandtemplates"


def parse_voice_lua(content: str, combatant_id: str) -> list[dict]:
    entries = []
    current = None
    for line in content.splitlines():
        if re.fullmatch(r"\s*\{\s*", line):
            current = {}
            continue
        if current is not None and re.fullmatch(r"\s*\},?\s*", line):
            if current.get("id"):
                if str(current.get("char_id") or combatant_id) != combatant_id:
                    raise ValueError(f"Lua char_id 不一致：{current.get('char_id')}")
                entries.append(current)
            current = None
            continue
        if current is None:
            continue
        match = re.fullmatch(r'\s*([A-Za-z_][\w]*)\s*=\s*"(.*)"\s*,?\s*', line)
        if match:
            key, raw_value = match.groups()
            try:
                current[key] = json.loads('"' + raw_value + '"')
            except json.JSONDecodeError:
                current[key] = raw_value.replace(r'\"', '"').replace(r"\\", "\\")
    if not entries:
        raise ValueError("Module:Voice Lua 未解析到条目")
    return entries


def voice_by_raw_lua(combatant_id: str) -> tuple[list[dict], str]:
    data = api_json({
        "action": "query", "titles": f"模块:Voice/{combatant_id}", "prop": "revisions",
        "rvprop": "content", "rvslots": "main", "format": "json", "formatversion": 2,
    })
    page = (data.get("query", {}).get("pages") or [{}])[0]
    revision_data = (page.get("revisions") or [{}])[0]
    content = revision_data.get("slots", {}).get("main", {}).get("content", "")
    entries = parse_voice_lua(content, combatant_id)
    root = {"char_id": combatant_id, "total": len(entries), "entries": entries, "types": []}
    return [root], "raw-lua"


def roots_from_page(title: str) -> tuple[list[dict], str]:
    data = api_json({"action": "parse", "page": title, "prop": "text", "format": "json", "formatversion": 2, "disablelimitreport": 1})
    return root_payloads(data.get("parse", {}).get("text", "")), "parse-page"


def merge_roots(roots: list[dict], requested_id: str) -> tuple[list[dict], list[dict], int]:
    seen: dict[str, dict] = {}
    conflicts = []
    declared = 0
    types = []
    for root in roots:
        if root.get("char_id") and str(root["char_id"]) != requested_id:
            raise ValueError(f"Voice char-id 不一致：请求 {requested_id}，页面 {root['char_id']}")
        declared = max(declared, int(root.get("total") or 0))
        if root.get("types"):
            types = root["types"]
        for item in root.get("entries", []):
            item_id = str(item.get("id") or "")
            if not item_id:
                raise ValueError("语音条目缺少 id")
            if item_id in seen and seen[item_id] != item:
                conflicts.append({"id": item_id, "first": seen[item_id], "second": item})
            else:
                seen[item_id] = item
    entries = list(seen.values())
    if conflicts:
        raise ValueError(f"重复语音 ID 内容冲突：{[x['id'] for x in conflicts]}")
    if declared and declared != len(entries):
        raise ValueError(f"data-total={declared}，唯一条目={len(entries)}")
    type_total = sum(int(item.get("count") or 0) for item in types)
    if types and type_total != len(entries):
        raise ValueError(f"data-types 合计={type_total}，唯一条目={len(entries)}")
    return entries, types, declared or len(entries)


def media_key(value: str) -> str:
    return value.split(":", 1)[-1].strip().lower().replace(" ", "_")


def verify_audio_metadata(entries: list[dict]) -> tuple[dict, list[dict]]:
    requested: dict[str, tuple[dict, str]] = {}
    for item in entries:
        base = str(item.get("file") or "").strip()
        if not base:
            continue
        for lang in ("cn", "ja", "ko"):
            filename = f"{base}_{lang}.wav"
            requested[media_key(filename)] = (item, lang)
    resolved = {}
    keys = list(requested)
    for start in range(0, len(keys), 40):
        titles = ["File:" + key for key in keys[start : start + 40]]
        data = api_json({
            "action": "query", "titles": "|".join(titles), "prop": "imageinfo",
            "iiprop": "url|size|mime|sha1", "format": "json", "formatversion": 2,
        })
        for page in data.get("query", {}).get("pages", []):
            key = media_key(str(page.get("title") or ""))
            info = first(page.get("imageinfo")) or {}
            resolved[key] = {
                "missing": bool(page.get("missing")) or not bool(info), "size": info.get("size"),
                "mime": info.get("mime"), "sha1": info.get("sha1"), "url": info.get("url"),
            }
    conflicts = []
    counts = {"cn": 0, "ja": 0, "ko": 0}
    for key, (item, lang) in requested.items():
        meta = resolved.get(key, {"missing": True})
        item[f"audio_meta_{lang}"] = meta
        field = "url" + lang.title()
        module_url = item.get(field) or ""
        if not module_url and not meta.get("missing") and meta.get("url"):
            item[field] = meta["url"]
            module_url = meta["url"]
        if not meta.get("missing"):
            counts[lang] += 1
        if bool(module_url) == bool(meta.get("missing")):
            conflicts.append({"id": item.get("id"), "language": lang, "module_url": module_url, "imageinfo": meta})
    return counts, conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description="结构化提取 BWIKI czn 角色资料、多语言台词和音频 URL")
    parser.add_argument("--title")
    parser.add_argument("--combatant-id")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--html-file", type=Path, help="API 受限时使用浏览器保存的完整渲染 HTML")
    parser.add_argument("--lua-file", type=Path, help="使用本地保存的 Module:Voice/<id> 原始 Lua；需给 --combatant-id")
    parser.add_argument("--offline", action="store_true", help="仅解析 --html-file，不发网络请求；需同时给 --combatant-id")
    parser.add_argument("--verify-audio-metadata", action="store_true", help="用批量 imageinfo 校验三语 WAV 的存在、大小、MIME 和 SHA1")
    args = parser.parse_args()
    if not args.title and not args.combatant_id:
        parser.error("--title 与 --combatant-id 至少提供一个")

    attempts = []
    profile = None
    if args.offline and not args.html_file and not args.lua_file:
        parser.error("--offline 需要 --html-file 或 --lua-file")
    if args.lua_file and not args.combatant_id:
        parser.error("--lua-file 需要 --combatant-id")
    if args.title and not args.offline:
        try:
            profile = profile_by_title(args.title)
            attempts.append({"strategy": "smw-title", "ok": True})
        except Exception as exc:
            attempts.append({"strategy": "smw-title", "ok": False, "error": str(exc)})
            try:
                profile = recover_profile_by_search(args.title)
                attempts.append({"strategy": "prefixsearch-profile", "ok": True, "canonical_title": profile.get("canonical_title")})
            except Exception as recovery_exc:
                attempts.append({"strategy": "prefixsearch-profile", "ok": False, "error": str(recovery_exc)})
    combatant_id = str(args.combatant_id or (profile or {}).get("combatant_id") or "")
    html_roots = root_payloads(args.html_file.read_text(encoding="utf-8-sig")) if args.html_file else []
    lua_roots = []
    if args.lua_file:
        lua_entries = parse_voice_lua(args.lua_file.read_text(encoding="utf-8-sig"), str(args.combatant_id))
        lua_roots = [{"char_id": str(args.combatant_id), "total": len(lua_entries), "entries": lua_entries, "types": []}]
    if not combatant_id and html_roots:
        html_ids = {str(root.get("char_id") or "") for root in html_roots if root.get("char_id")}
        if len(html_ids) == 1:
            combatant_id = next(iter(html_ids))
            attempts.append({"strategy": "rendered-html-id", "ok": True, "combatant_id": combatant_id})
    if not combatant_id:
        print(json.dumps({"ok": False, "attempts": attempts}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    if profile is None and not args.offline:
        try:
            profile = profile_by_id(combatant_id)
            attempts.append({"strategy": "smw-id", "ok": bool(profile)})
        except Exception as exc:
            attempts.append({"strategy": "smw-id", "ok": False, "error": str(exc)})

    roots = []
    strategy = ""
    for name, loader in ([] if args.offline else [
        ("expandtemplates", lambda: voice_by_module(combatant_id)),
        ("raw-lua", lambda: voice_by_raw_lua(combatant_id)),
        ("parse-page", lambda: roots_from_page((profile or {}).get("canonical_title") or args.title or "")),
    ]):
        try:
            roots, strategy = loader()
            attempts.append({"strategy": name, "ok": bool(roots), "roots": len(roots)})
            if roots:
                break
        except Exception as exc:
            attempts.append({"strategy": name, "ok": False, "error": str(exc)})
    if not roots and lua_roots:
        roots = lua_roots
        strategy = "raw-lua-file"
        attempts.append({"strategy": strategy, "ok": True, "roots": len(roots)})
    if not roots and html_roots:
        roots = html_roots
        strategy = "rendered-html"
        attempts.append({"strategy": strategy, "ok": bool(roots), "roots": len(roots)})
    if not roots:
        print(json.dumps({"ok": False, "combatant_id": combatant_id, "attempts": attempts}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3

    entries, types, declared = merge_roots(roots, combatant_id)
    verified_audio_counts = None
    audio_metadata_conflicts = []
    if (args.verify_audio_metadata or strategy == "raw-lua") and not args.offline:
        verified_audio_counts, audio_metadata_conflicts = verify_audio_metadata(entries)
        if audio_metadata_conflicts:
            raise ValueError(f"Voice URL 与 imageinfo 冲突：{len(audio_metadata_conflicts)} 条")
    canonical_title = (profile or {}).get("canonical_title") or args.title
    result = {
        "schema_version": 2,
        "ok": True,
        "input_title": args.title,
        "canonical_title": canonical_title,
        "page_url": (profile or {}).get("canonical_url"),
        "combatant_id": combatant_id,
        "profile": profile or {},
        "profile_source": {"kind": "community-wiki-structured-profile", "authority": "community_wiki", "directness": "explicit_page_statement"},
        "page_revision": revision(canonical_title) if canonical_title and not args.offline else None,
        "voice_module_revision": revision(f"模块:Voice/{combatant_id}") if not args.offline else None,
        "voice_strategy": strategy,
        "voice_total_declared": declared,
        "voice_types": types,
        "entries": entries,
        "language_text_counts": {lang: sum(bool(item.get(lang)) for item in entries) for lang in ("cn", "ja", "ko")},
        "audio_url_counts": {lang: sum(bool(item.get("url" + lang.title())) for item in entries) for lang in ("cn", "ja", "ko")},
        "verified_audio_counts": verified_audio_counts,
        "audio_metadata_conflicts": audio_metadata_conflicts,
        "attempts": attempts,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"ok": True, "id": combatant_id, "title": canonical_title, "entries": len(entries), "audio": result["audio_url_counts"], "strategy": strategy}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
