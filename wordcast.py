#!/usr/bin/env python3
"""
Read vocabulary from a Markdown file, synthesize British English (Edge TTS),
and merge into one long MP3 for passive listening.

Needs ffmpeg on PATH (merge + encode): macOS `brew install ffmpeg`

Usage:
  python wordcast.py example-words.md -o listen.mp3
  python wordcast.py words.md -o out.mp3 --voice en-GB-RyanNeural --pause-ms 900
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

DEFAULT_VOICE = "en-GB-SoniaNeural"

BULLET = re.compile(r"^\s*[-*+]\s+(.+?)\s*$")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.+?)\s*$")


def strip_md_inline(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = re.sub(r"\*(.+?)\*", r"\1", s)
    s = re.sub(r"`(.+?)`", r"\1", s)
    return s.strip()


def extract_phrases_from_markdown(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        m = BULLET.match(raw) or NUMBERED.match(raw)
        if not m:
            continue
        phrase = strip_md_inline(m.group(1))
        if not phrase:
            continue
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
    return out


async def synth_one(text: str, voice: str, out_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(str(out_path))


async def synth_all(phrases: list[str], voice: str, tmpdir: Path) -> list[Path]:
    paths: list[Path] = []
    for i, phrase in enumerate(phrases):
        p = tmpdir / f"seg_{i:04d}.mp3"
        await synth_one(phrase, voice, p)
        paths.append(p)
        await asyncio.sleep(0.15)
    return paths


def merge_mp3s_ffmpeg(paths: list[Path], pause_ms: int, out_file: Path) -> None:
    """Pad each segment with trailing silence, then concat into one MP3."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install it (e.g. macOS: brew install ffmpeg) "
            "to merge segments into one MP3."
        )

    n = len(paths)
    if n == 0:
        raise RuntimeError("No segments to merge.")

    pause_sec = max(0.0, pause_ms / 1000.0)
    inputs: list[str] = []
    for p in paths:
        inputs.extend(["-i", str(p)])

    pad_labels = [f"p{i}" for i in range(n)]
    pad_chain = ";".join(
        f"[{i}:a]apad=pad_dur={pause_sec}[{pad_labels[i]}]" for i in range(n)
    )
    concat_in = "".join(f"[{pad_labels[i]}]" for i in range(n))
    filter_complex = f"{pad_chain};{concat_in}concat=n={n}:v=0:a=1[out]"

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(out_file),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{proc.stderr or proc.stdout}")


async def render_markdown_to_mp3(markdown: str, voice: str, pause_ms: int, output: Path) -> int:
    """
    Parse markdown, synthesize phrases with Edge TTS, merge to one MP3.
    Returns number of phrases spoken.
    """
    phrases = extract_phrases_from_markdown(markdown)
    if not phrases:
        raise ValueError(
            "No list items found. Use Markdown bullets (- word) or numbered (1. word) lines."
        )
    with tempfile.TemporaryDirectory(prefix="wordcast_") as td:
        tmp = Path(td)
        paths = await synth_all(phrases, voice, tmp)
        output.parent.mkdir(parents=True, exist_ok=True)
        merge_mp3s_ffmpeg(paths, pause_ms, output)
    return len(phrases)


def main() -> None:
    ap = argparse.ArgumentParser(description="Markdown vocab → one British-English MP3.")
    ap.add_argument("markdown", type=Path, help="Input .md file (bullets / numbered lines).")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Output .mp3 path.")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"edge-tts voice id (default: {DEFAULT_VOICE}).")
    ap.add_argument(
        "--pause-ms",
        type=int,
        default=700,
        help="Silence after each item in milliseconds (default: 700).",
    )
    args = ap.parse_args()

    if not args.markdown.is_file():
        print(f"Not found: {args.markdown}", file=sys.stderr)
        sys.exit(1)

    text = args.markdown.read_text(encoding="utf-8")

    async def run() -> int:
        return await render_markdown_to_mp3(text, args.voice, args.pause_ms, args.output)

    try:
        n = asyncio.run(run())
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(f"Found {n} items; voice={args.voice}")
    print(f"Wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
