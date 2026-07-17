from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import main  # noqa: E402


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


async def run(args: argparse.Namespace) -> int:
    if args.list:
        requests = await main.voice_clone_requests()
        print_json(requests)
        return 0
    request = main.VoiceCloneEnrollRequest(
        request_path=args.request,
        character_id=args.character_id,
        reference_audio_url=args.audio_url,
        reference_audio_path=args.audio_path,
        target_model=args.target_model,
        prefix=args.prefix,
        language_hints=args.language_hint,
        endpoint=args.endpoint,
        enrollment_model=args.enrollment_model,
        dry_run=args.dry_run,
    )
    result = await main.voice_clone_enroll(request)
    print_json(result)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enroll a pending FenneNote/OumuQ voice clone request with DashScope.")
    parser.add_argument("--list", action="store_true", help="List pending voice clone request JSON files.")
    parser.add_argument("--request", help="Path to a FenneNote voice-clone request JSON.")
    parser.add_argument("--character-id", help="Use the newest pending request for this character id.")
    parser.add_argument("--audio-url", help="Provider-accessible reference audio URL.")
    parser.add_argument("--audio-path", help="Local reference audio path. Only non-CosyVoice modes may convert this to a data URL.")
    parser.add_argument("--target-model", default=None, help="DashScope target model, e.g. cosyvoice-v3-plus.")
    parser.add_argument("--prefix", help="Voice id prefix requested from DashScope.")
    parser.add_argument("--language-hint", action="append", help="Reference audio language hint, e.g. zh, ja, en.")
    parser.add_argument("--endpoint", help="DashScope customization endpoint override.")
    parser.add_argument("--enrollment-model", default="voice-enrollment", help="DashScope enrollment model. Default: voice-enrollment.")
    parser.add_argument("--dry-run", action="store_true", help="Print the DashScope payload without calling the provider.")
    return parser.parse_args()


def main_cli() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
