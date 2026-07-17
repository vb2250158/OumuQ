#!/usr/bin/env python
import argparse
import os
from pathlib import Path

import dashscope
from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer


def get_windows_user_env(name):
    if os.name != "nt":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def get_api_key():
    for name in ("DASHSCOPE_API_KEY", "QWEN_API_KEY"):
        value = os.environ.get(name) or get_windows_user_env(name)
        if value:
            return value
    raise RuntimeError("Missing DASHSCOPE_API_KEY or QWEN_API_KEY")


def fix_wav_sizes(path):
    path = Path(path)
    data = bytearray(path.read_bytes())
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return
    data_index = data.find(b"data")
    if data_index < 0 or data_index + 8 > len(data):
        return
    data[4:8] = (len(data) - 8).to_bytes(4, "little")
    data[data_index + 4:data_index + 8] = (len(data) - (data_index + 8)).to_bytes(4, "little")
    path.write_bytes(data)


class FileWriter(ResultCallback):
    def __init__(self, output_path):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(self.output_path, "wb")
        self.error = None
        self.completed = False

    def on_data(self, data: bytes):
        self.file.write(data)

    def on_error(self, message):
        self.error = message

    def on_complete(self):
        self.completed = True

    def on_close(self):
        if not self.file.closed:
            self.file.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Generate one CosyVoice TTS file through DashScope.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="cosyvoice-v3-plus")
    parser.add_argument("--url", default="wss://dashscope.aliyuncs.com/api-ws/v1/inference")
    parser.add_argument("--language-hint", default="zh")
    return parser.parse_args()


def main():
    args = parse_args()
    dashscope.api_key = get_api_key()
    callback = FileWriter(args.output)
    synthesizer = SpeechSynthesizer(
        model=args.model,
        voice=args.voice,
        format=AudioFormat.WAV_24000HZ_MONO_16BIT,
        language_hints=[args.language_hint] if args.language_hint else None,
        callback=callback,
        url=args.url,
    )
    synthesizer.async_call = False
    try:
        synthesizer.call(args.text, timeout_millis=120000)
        synthesizer.close()
    finally:
        callback.on_close()
    if callback.error:
        raise RuntimeError(callback.error)
    output = Path(args.output)
    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError(f"No audio written: {output}")
    fix_wav_sizes(output)
    print(str(output))
    print(output.stat().st_size)
    print("request_id=" + str(synthesizer.get_last_request_id()))


if __name__ == "__main__":
    main()
