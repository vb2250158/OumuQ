from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen


KURO_ENTRY_API = "https://api.kurobbs.com/wiki/core/catalogue/item/getEntryDetail"
DYNAMIC_SHELL_MARKERS = (
    "您使用的浏览器版本过低",
    "浏览器版本过低",
    "enable javascript to run this app",
    "please enable javascript",
    "requires javascript",
)


def fetch(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[bytes, str]:
    request_headers = {
        "User-Agent": "Mozilla/5.0 Chrome/126.0 Safari/537.36",
        "Accept": "text/html,application/json,text/plain,*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    request_headers.update(headers or {})
    request = Request(url, data=data, headers=request_headers)
    with urlopen(request, timeout=35) as response:
        return response.read(), response.headers.get("Content-Type", "")


def html_text(value: str) -> str:
    value = re.sub(r"<script\b[\s\S]*?</script>|<style\b[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<br\s*/?>|</(?:p|div|li|tr|h[1-6])>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    lines = [re.sub(r"\s+", " ", unescape(line)).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    return html_text(xml)


def pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("读取 PDF 需要 pypdf；也可先用 PDF skill 提取为文本") from exc
    return "\n".join((page.extract_text() or "").strip() for page in PdfReader(str(path)).pages).strip()


def local_source(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return docx_text(path), "docx-xml"
    if suffix == ".pdf":
        return pdf_text(path), "pypdf"
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    if suffix in {".html", ".htm"}:
        return html_text(text), "html-strip"
    if suffix == ".json":
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2), "json"
    return text.strip(), "plain-text"


def mediawiki_api(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or "wiki" not in parsed.netloc:
        return None
    title = unquote(parts[-1])
    base = f"{parsed.scheme}://{parsed.netloc}"
    if parts[0].lower() == "wiki":
        api_paths = ("/w/api.php", "/api.php")
    else:
        api_paths = (f"/{parts[0]}/api.php", "/api.php")
    for api_path in api_paths:
        try:
            api = f"{base}{api_path}?action=parse&page={quote(title)}&prop=text&format=json&disablelimitreport=1"
            raw, _ = fetch(api)
            data = json.loads(raw.decode("utf-8", errors="replace"))
            html = data.get("parse", {}).get("text", {}).get("*")
            if html:
                return html_text(html), f"mediawiki-parse-api:{api_path}"
        except Exception:
            continue
    return None


def _append_text(lines: list[str], label: str, value: object, *, markup: bool = False) -> None:
    if not isinstance(value, str):
        return
    text = html_text(value) if markup else re.sub(r"\s+", " ", unescape(value)).strip()
    if text:
        lines.append(f"【{label}】\n{text}")


def kurobbs_item_api(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    match = re.fullmatch(r"/mc/item/(\d+)/?", parsed.path)
    if parsed.netloc.lower() != "wiki.kurobbs.com" or not match:
        return None
    raw, _ = fetch(
        KURO_ENTRY_API,
        data=urlencode({"id": match.group(1)}).encode("ascii"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "wiki_type": "9",
        },
    )
    payload = json.loads(raw.decode("utf-8", errors="replace"))
    if not payload.get("success") or not isinstance(payload.get("data"), dict):
        raise ValueError("库街区官方条目接口返回失败")
    content = payload["data"].get("content")
    if not isinstance(content, dict):
        raise ValueError("库街区官方条目接口缺少 content")

    role_title = str(content.get("title") or "").strip()
    lines: list[str] = []
    _append_text(lines, "角色名", role_title)
    for module in content.get("modules") or []:
        if not isinstance(module, dict):
            continue
        module_title = str(module.get("title") or "").strip()
        if module_title not in {"基础资料", "角色档案", "角色语音"}:
            continue
        lines.append(f"# {module_title}")
        for component in module.get("components") or []:
            if not isinstance(component, dict):
                continue
            component_type = component.get("type")
            component_title = str(component.get("title") or "").strip()
            if module_title == "基础资料":
                if component_type == "role-component":
                    role = component.get("role") or {}
                    if isinstance(role, dict):
                        for key, label in (
                            ("title", "角色"),
                            ("subtitle", "英文名"),
                            ("roleDescriptionTitle", "共鸣能力"),
                            ("roleDescription", "角色简介"),
                        ):
                            _append_text(lines, label, role.get(key))
                        for item in role.get("info") or []:
                            if isinstance(item, dict):
                                _append_text(lines, "基础信息", item.get("text"))
                elif component_title == "其他信息":
                    _append_text(lines, component_title, component.get("content"), markup=True)
                continue

            if module_title == "角色档案":
                _append_text(lines, component_title or "档案", component.get("content"), markup=True)
                for tab in component.get("tabs") or []:
                    if isinstance(tab, dict):
                        _append_text(lines, str(tab.get("title") or component_title or "档案"), tab.get("content"), markup=True)
                continue

            if module_title == "角色语音" and component_type == "audio-component":
                if component_title:
                    lines.append(f"## {component_title}")
                for tab in component.get("mediaTabs") or []:
                    if not isinstance(tab, dict):
                        continue
                    tab_title = str(tab.get("title") or "").strip()
                    media = tab.get("mediaList") or []
                    if not media:
                        continue
                    if tab_title:
                        lines.append(f"### {tab_title}")
                    for item in media:
                        if not isinstance(item, dict):
                            continue
                        label = str(item.get("audioTitle") or "语音").strip()
                        _append_text(lines, label, item.get("content"))

    text = "\n".join(lines).strip()
    if not role_title or role_title not in text or len(re.sub(r"\s+", "", text)) < 300:
        raise ValueError("库街区官方条目接口正文不足")
    return text, "kurobbs-entry-detail-api"


def validate_url_text(text: str, method: str) -> None:
    compact = re.sub(r"\s+", "", text)
    lowered = text.lower()
    if any(marker in lowered for marker in DYNAMIC_SHELL_MARKERS):
        raise ValueError("网页只返回浏览器兼容提示，疑似动态空壳")
    if method == "direct-html" and len(compact) < 120:
        raise ValueError("直连 HTML 正文过短，疑似动态空壳")


def url_source(url: str) -> tuple[str, str]:
    kuro = kurobbs_item_api(url)
    if kuro:
        return kuro
    try:
        wiki = mediawiki_api(url)
        if wiki:
            return wiki
    except Exception:
        pass
    raw, content_type = fetch(url)
    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type or "<html" in text[:1000].lower():
        extracted, method = html_text(text), "direct-html"
    else:
        extracted, method = text.strip(), "direct-text"
    validate_url_text(extracted, method)
    return extracted, method


def main() -> int:
    parser = argparse.ArgumentParser(description="把网页、Wiki 和本地资料规范化为角色证据文本包")
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-partial", action="store_true", help="部分来源失败时仍返回退出码 0；结果仍标记 partial")
    args = parser.parse_args()
    records = []
    failures = []
    for index, source in enumerate(args.sources, 1):
        try:
            if re.match(r"https?://", source, re.I):
                text, method = url_source(source)
                kind = "url"
            else:
                path = Path(source).expanduser().resolve()
                text, method = local_source(path)
                kind = "file"
            if not text:
                raise ValueError("未提取到正文")
            records.append({
                "id": f"source-{index}", "source": source, "kind": kind, "method": method,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "characters": len(text), "text": text,
            })
        except Exception as exc:
            failures.append({"source": source, "error": str(exc)})
    status = "success" if records and not failures else "partial" if records else "failed"
    result = {"schema_version": 1, "status": status, "extracted_at": datetime.now(timezone.utc).isoformat(), "sources": records, "failures": failures}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": status == "success", "status": status, "sources": len(records), "failures": len(failures), "output": str(args.output)}, ensure_ascii=False))
    if status == "success" or (status == "partial" and args.allow_partial):
        return 0
    return 2 if status == "partial" else 1


if __name__ == "__main__":
    raise SystemExit(main())
