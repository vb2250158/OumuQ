from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


VECTOR_ORDER = ("happy", "angry", "sad", "afraid", "disgusted", "melancholic", "surprised", "calm")
DEFAULT_VECTOR = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.55]
ALLOWED_OUTPUT_KEYS = {
    "language",
    "emotion_mode",
    "emotion_alpha",
    "emotion_vector",
    "emotion_tags",
    "emotion_text",
    "ref_text",
    "match_patterns",
    "max_new_tokens",
    "reason",
}


def read_text_if_exists(path: Path, limit: int = 6000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8-sig")[:limit]


def read_json_if_exists(path: Path, limit_items: int = 8) -> Any:
    if not path.exists() or not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, list):
        return data[:limit_items]
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return {**data, "entries": data["entries"][:limit_items]}
    return data


def character_context(workspace: Path, character: dict[str, Any] | None) -> dict[str, Any]:
    if not character:
        return {"character": {}, "readme": "", "voice_index": []}

    folder_value = str(character.get("character_folder") or "").strip()
    folder = Path(folder_value) if folder_value else None
    if folder is not None and not folder.is_absolute():
        folder = workspace / folder

    index_value = str(character.get("index_file") or "").strip()
    index_file = Path(index_value) if index_value else None
    if index_file is not None and not index_file.is_absolute():
        index_file = workspace / index_file
    if index_file is None and folder is not None:
        index_file = folder / "voice-index.json"

    return {
        "character": character,
        "readme": read_text_if_exists(folder / "README.md") if folder is not None else "",
        "voice_index": read_json_if_exists(index_file) if index_file is not None else [],
    }


def build_parameter_prompt(
    template_path: Path,
    *,
    text: str,
    character: dict[str, Any] | None,
    character_readme: str,
    voice_index: Any,
) -> str:
    template = template_path.read_text(encoding="utf-8")
    values = {
        "character_json": json.dumps(character or {}, ensure_ascii=False, indent=2),
        "character_readme": character_readme or "（无）",
        "voice_index_json": json.dumps(voice_index, ensure_ascii=False, indent=2),
        "text": text,
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def heuristic_parameters(text: str, character: dict[str, Any] | None) -> dict[str, Any]:
    normalized = text.lower()
    tags: list[str] = []
    vector = DEFAULT_VECTOR.copy()
    mode = "auto-vector"
    alpha = 0.55

    if any(word in normalized for word in ("谢谢", "感谢", "开心", "太好了", "thank", "happy", "great")):
        tags = ["warm", "cheerful"]
        vector = [0.58, 0.0, 0.0, 0.0, 0.0, 0.0, 0.08, 0.14]
        mode = "vector"
        alpha = 0.62
    elif any(word in normalized for word in ("抱歉", "难过", "遗憾", "sad", "sorry", "tired")):
        tags = ["soft", "melancholic"]
        vector = [0.0, 0.0, 0.45, 0.0, 0.0, 0.18, 0.0, 0.18]
        mode = "vector"
        alpha = 0.6
    elif any(word in normalized for word in ("？", "?", "怎么", "为什么", "what", "why", "how")):
        tags = ["curious", "clear"]
        vector = [0.18, 0.0, 0.0, 0.0, 0.0, 0.0, 0.22, 0.28]
        mode = "vector"
        alpha = 0.55
    else:
        tags = ["calm", "natural"]

    max_tokens = 192
    if len(text) > 180:
        max_tokens = 384
    elif len(text) > 80:
        max_tokens = 256

    return {
        "language": character.get("speech_language") if character else None,
        "emotion_mode": mode,
        "emotion_alpha": alpha,
        "emotion_vector": vector,
        "emotion_tags": tags,
        "emotion_text": ", ".join(tags),
        "ref_text": text[:80],
        "match_patterns": tags[:2],
        "max_new_tokens": max_tokens,
        "reason": "未配置 LLM provider，使用本地启发式推理。",
    }


def extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM output must be a JSON object.")
    return data


def sanitize_parameters(data: dict[str, Any]) -> dict[str, Any]:
    sanitized = {key: value for key, value in data.items() if key in ALLOWED_OUTPUT_KEYS}

    vector = sanitized.get("emotion_vector")
    if vector is not None:
        if not isinstance(vector, list) or len(vector) != len(VECTOR_ORDER):
            sanitized.pop("emotion_vector", None)
        else:
            try:
                sanitized["emotion_vector"] = [float(item) for item in vector]
            except (TypeError, ValueError):
                sanitized.pop("emotion_vector", None)

    alpha = sanitized.get("emotion_alpha")
    if alpha is not None:
        try:
            sanitized["emotion_alpha"] = max(0.0, min(1.0, float(alpha)))
        except (TypeError, ValueError):
            sanitized.pop("emotion_alpha", None)

    for key in ("emotion_tags", "match_patterns"):
        value = sanitized.get(key)
        if isinstance(value, str):
            sanitized[key] = [part.strip() for part in re.split(r"[,，\s]+", value) if part.strip()]
        elif isinstance(value, list):
            sanitized[key] = [str(part).strip() for part in value if str(part).strip()]
        elif value is not None:
            sanitized.pop(key, None)

    tokens = sanitized.get("max_new_tokens")
    if tokens is not None:
        try:
            sanitized["max_new_tokens"] = max(16, min(2048, int(tokens)))
        except (TypeError, ValueError):
            sanitized.pop("max_new_tokens", None)

    return {key: value for key, value in sanitized.items() if value not in (None, [], "")}
