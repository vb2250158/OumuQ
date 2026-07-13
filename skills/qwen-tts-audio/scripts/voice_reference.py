import hashlib
import json
import math
import re
from pathlib import Path


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def audio_duration(path):
    import soundfile as sf

    return float(sf.info(str(path)).duration)


def read_mono_audio(path):
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data, sr


def resample_linear(data, source_sr, target_sr):
    if source_sr == target_sr:
        return data
    import numpy as np

    if len(data) == 0:
        return data
    old_x = np.linspace(0.0, 1.0, num=len(data), endpoint=False)
    new_len = max(1, int(round(len(data) * target_sr / source_sr)))
    new_x = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(new_x, old_x, data).astype("float32")


def concatenate_audio_files(paths, out_path, gap_seconds=0.12, target_sr=None):
    import numpy as np
    import soundfile as sf

    chunks = []
    resolved_sr = target_sr
    for path in paths:
        data, sr = read_mono_audio(path)
        if resolved_sr is None:
            resolved_sr = sr
        data = resample_linear(data, sr, resolved_sr)
        chunks.append(data)
        chunks.append(np.zeros(int(resolved_sr * gap_seconds), dtype="float32"))
    if not chunks:
        raise RuntimeError("No prompt audio files to concatenate.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), np.concatenate(chunks), resolved_sr)


def normalize_tags(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip().lower() for part in re.split(r"[,，\s]+", value) if part.strip()]
    if isinstance(value, list):
        return [str(part).strip().lower() for part in value if str(part).strip()]
    return []


def parse_vector(value):
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        parts = value
    else:
        return None
    try:
        vector = [float(part) for part in parts]
    except (TypeError, ValueError):
        return None
    return vector if vector else None


def text_affinity(text, entry):
    haystack = text.lower()
    score = 0.0
    for key in ("title", "ja", "zh"):
        field = str(entry.get(key, "")).lower().strip()
        if not field:
            continue
        if field in haystack or haystack in field:
            score += 120.0
        field_chars = {ch for ch in field if re.match(r"[\w\u3040-\u30ff\u3400-\u9fff]", ch)}
        text_chars = {ch for ch in haystack if re.match(r"[\w\u3040-\u30ff\u3400-\u9fff]", ch)}
        if field_chars and text_chars:
            score += 35.0 * (len(field_chars & text_chars) / len(field_chars | text_chars))
    return score


def vector_affinity(target, candidate):
    target = parse_vector(target)
    candidate = parse_vector(candidate)
    if not target or not candidate:
        return 0.0
    size = min(len(target), len(candidate))
    if size == 0:
        return 0.0
    distance = math.sqrt(sum((target[i] - candidate[i]) ** 2 for i in range(size)))
    return max(0.0, 100.0 - distance * 180.0)


def regex_affinity(text, entry, request_patterns=None):
    score = 0.0
    for pattern in list(entry.get("match_patterns", []) or []) + list(request_patterns or []):
        try:
            if re.search(pattern, text, re.IGNORECASE):
                score += 140.0
        except re.error:
            if str(pattern).lower() in text.lower():
                score += 70.0
    return score


def entry_score(text, entry, emotion_tags=None, emotion_vector=None, match_patterns=None, primary_entry=None, distance=0):
    tags = set(normalize_tags(emotion_tags))
    entry_tags = set(normalize_tags(entry.get("mood")) + normalize_tags(entry.get("emotion_tags")))
    tag_score = 55.0 * len(tags & entry_tags) if tags and entry_tags else 0.0

    target_vector = emotion_vector
    if target_vector is None and primary_entry is not None:
        target_vector = primary_entry.get("emotion_vector")

    return (
        regex_affinity(text, entry, match_patterns) * 1.4
        + vector_affinity(target_vector, entry.get("emotion_vector")) * 1.2
        + tag_score
        + text_affinity(text, entry) * 0.45
        - min(distance, 30) * 1.5
    )


class VoiceReferenceResolver:
    def __init__(
        self,
        workdir,
        reference_cache_dir,
        default_prompt_audio,
        min_prompt_duration=6.0,
        target_prompt_duration=10.0,
        prompt_gap_seconds=0.12,
        composite_target_sr=None,
        prepare_single_audio=None,
    ):
        self.workdir = Path(workdir).resolve()
        self.reference_cache_dir = Path(reference_cache_dir)
        if not self.reference_cache_dir.is_absolute():
            self.reference_cache_dir = self.workdir / self.reference_cache_dir
        self.reference_cache_dir.mkdir(parents=True, exist_ok=True)
        default_prompt_audio = Path(default_prompt_audio)
        if not default_prompt_audio.is_absolute():
            default_prompt_audio = self.workdir / default_prompt_audio
        self.default_prompt_audio = default_prompt_audio.resolve()
        self.min_prompt_duration = float(min_prompt_duration)
        self.target_prompt_duration = float(target_prompt_duration)
        self.prompt_gap_seconds = float(prompt_gap_seconds)
        self.composite_target_sr = composite_target_sr
        self.prepare_single_audio = prepare_single_audio

    def resolve_character_folder(self, character_id=None, character_folder=None):
        if character_folder:
            path = Path(character_folder)
            if not path.is_absolute():
                path = self.workdir / path
            path = path.resolve()
            if not path.exists():
                raise FileNotFoundError(f"Character folder not found: {path}")
            return path

        if not character_id:
            return None

        registry_path = self.workdir / "voice-references" / "reference-index.json"
        if not registry_path.exists():
            raise FileNotFoundError(f"Voice reference registry not found: {registry_path}")
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        for character in registry.get("characters", []):
            if str(character.get("id", "")).lower() == str(character_id).lower():
                folder = Path(character["character_folder"])
                if not folder.is_absolute():
                    folder = self.workdir / folder
                return folder.resolve()
        raise ValueError(f"Character id not found in registry: {character_id}")

    def resolve_prompt_files(
        self,
        prompt_audio=None,
        prompt_audios=None,
        text="",
        character_folder=None,
        emotion_tags=None,
        emotion_vector=None,
        match_patterns=None,
    ):
        raw = []
        if prompt_audios:
            if not isinstance(prompt_audios, list):
                raise ValueError("prompt_audios must be a list of audio paths.")
            raw.extend(prompt_audios)
        if prompt_audio:
            raw.append(prompt_audio)
        if not raw and character_folder:
            return self.select_character_prompt_files(character_folder, text, emotion_tags, emotion_vector, match_patterns)
        if not raw:
            raw.append(str(self.default_prompt_audio))

        resolved = []
        for item in raw:
            path = Path(item)
            if not path.is_absolute():
                path = self.workdir / path
            path = path.resolve()
            if not path.exists():
                raise FileNotFoundError(f"Prompt audio not found: {path}")
            if path not in resolved:
                resolved.append(path)
        return resolved

    def select_character_prompt_files(self, character_folder, text, emotion_tags=None, emotion_vector=None, match_patterns=None):
        character_folder = Path(character_folder).resolve()
        index_path = character_folder / "voice-index.json"
        if not index_path.exists():
            raise FileNotFoundError(f"Character voice index not found: {index_path}")
        entries = json.loads(index_path.read_text(encoding="utf-8-sig"))
        scored = []
        for pos, entry in enumerate(entries):
            candidate = self._entry_audio(entry)
            if candidate is None:
                continue
            score = entry_score(
                text,
                entry,
                emotion_tags=emotion_tags,
                emotion_vector=emotion_vector,
                match_patterns=match_patterns,
            )
            score += min(audio_duration(candidate), 8.0)
            scored.append((score, -pos, entry, candidate))
        if not scored:
            raise ValueError(f"No usable audio files in character voice index: {index_path}")

        scored.sort(reverse=True)
        selected = []
        total = 0.0
        for _, _, _, candidate in scored:
            selected.append(candidate)
            total += audio_duration(candidate) + self.prompt_gap_seconds
            if total >= self.target_prompt_duration:
                break
        return selected

    def prepare_prompt_audio(self, prompt_files):
        files = list(prompt_files)
        if len(files) == 1 and audio_duration(files[0]) < self.min_prompt_duration:
            files = self.augment_short_prompt(files[0])

        if len(files) == 1:
            prepared = self.prepare_single_audio(files[0]) if self.prepare_single_audio else files[0]
            return prepared, files, False

        digest_payload = {
            "files": [{"path": str(path), "sha256": sha256_file(path)} for path in files],
            "gap": self.prompt_gap_seconds,
            "target_duration": self.target_prompt_duration,
            "target_sr": self.composite_target_sr,
            "matcher": "regex+emotion-vector",
        }
        digest = hashlib.sha256(json.dumps(digest_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        out_path = self.reference_cache_dir / f"prompt-{digest[:16]}.wav"
        meta_path = self.reference_cache_dir / f"prompt-{digest[:16]}.json"
        if not out_path.exists():
            concatenate_audio_files(files, out_path, gap_seconds=self.prompt_gap_seconds, target_sr=self.composite_target_sr)
        write_json(meta_path, {
            "output": str(out_path),
            "sources": [str(path) for path in files],
            "durations": [round(audio_duration(path), 3) for path in files],
            "total_duration": round(audio_duration(out_path), 3),
            "settings": digest_payload,
        })
        return out_path, files, True

    def augment_short_prompt(self, primary):
        selected = [primary]
        total = audio_duration(primary)
        if total >= self.min_prompt_duration:
            return selected

        for candidate in self.find_related_prompt_candidates(primary):
            if candidate in selected:
                continue
            selected.append(candidate)
            total += audio_duration(candidate) + self.prompt_gap_seconds
            if total >= self.target_prompt_duration:
                break
        return selected

    def find_related_prompt_candidates(self, primary):
        primary = Path(primary).resolve()
        character_dir = primary.parent.parent
        index_path = character_dir / "voice-index.json"
        if not index_path.exists():
            return []
        try:
            entries = json.loads(index_path.read_text(encoding="utf-8-sig"))
        except Exception:
            return []

        candidates = []
        primary_key = str(primary).replace("\\", "/")
        primary_index = None
        primary_entry = None
        for pos, entry in enumerate(entries):
            candidate = self._entry_audio(entry)
            if candidate is None:
                continue
            candidates.append((pos, entry, candidate))
            if str(candidate).replace("\\", "/") == primary_key:
                primary_index = pos
                primary_entry = entry

        def candidate_score(item):
            pos, entry, candidate = item
            distance = abs(pos - primary_index) if primary_index is not None else 9999
            duration = audio_duration(candidate)
            tiny_penalty = 20 if duration < 1.2 else 0
            long_penalty = 5 if duration > 12 else 0
            return (
                -entry_score("", entry, primary_entry=primary_entry, distance=distance)
                + tiny_penalty
                + long_penalty,
                -min(duration, 8.0),
            )

        return [candidate for _, _, candidate in sorted(candidates, key=candidate_score)]

    def _entry_audio(self, entry):
        audio_file = entry.get("audio_file")
        if not audio_file:
            return None
        candidate = Path(audio_file)
        if not candidate.is_absolute():
            candidate = self.workdir / candidate
        candidate = candidate.resolve()
        return candidate if candidate.exists() else None
