"""
Local web UI for Wordcast: POST markdown → merged British-English MP3.

Run from repo root:
  uvicorn server:app --reload --host 127.0.0.1 --port 8765
Then open http://127.0.0.1:8765/ (若端口占用，改用 --port 8766 等).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import aiohttp
import edge_tts
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

import db
from wordcast import (
    BULLET,
    NUMBERED,
    DEFAULT_VOICE,
    render_markdown_to_mp3,
    strip_md_inline,
)

WEB_DIR = Path(__file__).resolve().parent / "web"


class RenderRequest(BaseModel):
    markdown: str = Field(..., min_length=1)
    voice: str = DEFAULT_VOICE
    pause_ms: int = Field(700, ge=0, le=5000)


class LibraryAddRequest(BaseModel):
    text: str = Field(..., min_length=1)


class RandomRenderRequest(BaseModel):
    count: int = Field(20, ge=1, le=200)
    voice: str = DEFAULT_VOICE
    pause_ms: int = Field(700, ge=0, le=5000)


class SettingsRequest(BaseModel):
    db_path: str = Field(..., min_length=1)
    migrate: bool = False


def parse_words(text: str) -> list[str]:
    """Extract words from bullet/numbered or plain lines (deduped, order-preserving)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("<!--"):
            continue
        m = BULLET.match(raw) or NUMBERED.match(raw)
        phrase = strip_md_inline(m.group(1) if m else line)
        if not phrase:
            continue
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
    return out


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


app = FastAPI(title="Wordcast")

db.init_db()


# ── Word library (independent module) ──────────────────────────────────────
def _settings_state() -> dict:
    p = db.get_db_path()
    return {
        "db_path": str(p),
        "default_path": str(db.default_db_path()),
        "exists": p.exists(),
        "total": db.count(),
    }


@app.get("/api/library/settings")
async def api_library_settings_get() -> dict:
    """Where the word library is stored on disk."""
    return _settings_state()


@app.post("/api/library/settings")
async def api_library_settings_set(body: SettingsRequest) -> dict:
    """Choose a different local file/folder for the word library."""
    try:
        db.set_db_path(body.db_path, migrate=body.migrate)
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Cannot use that path: {e}") from e
    return _settings_state()


@app.get("/api/library")
async def api_library_list() -> dict:
    """Current library size and recent words (newest first)."""
    return {"total": db.count(), "words": db.all_words(limit=500)}


@app.post("/api/library/add")
async def api_library_add(body: LibraryAddRequest) -> dict:
    """Save words (bullets, numbered, or one-per-line) into the local library."""
    words = parse_words(body.text)
    if not words:
        raise HTTPException(status_code=400, detail="No words found to add.")
    added = db.add_words(words)
    return {"added": added, "total": db.count()}


@app.delete("/api/library/{word_id}")
async def api_library_delete(word_id: int) -> dict:
    db.delete_word(word_id)
    return {"total": db.count()}


@app.post("/api/library/clear")
async def api_library_clear() -> dict:
    db.clear()
    return {"total": db.count()}


@app.post("/api/library/random-render")
async def api_library_random_render(body: RandomRenderRequest) -> FileResponse:
    """Pick N random words from the library and render them to one MP3."""
    words = db.random_words(body.count)
    if not words:
        raise HTTPException(status_code=400, detail="Word library is empty. Add words first.")

    markdown = "\n".join(f"- {w}" for w in words)
    fd, raw_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    path = Path(raw_path)
    try:
        n = await render_markdown_to_mp3(markdown, body.voice, body.pause_ms, path)
    except ValueError as e:
        _unlink(path)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        _unlink(path)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename="vocast-random.mp3",
        headers={"X-Phrase-Count": str(n)},
        background=BackgroundTask(_unlink, path),
    )


@app.get("/api/voices")
async def api_voices() -> list[dict[str, str]]:
    """British English neural voices for the picker."""
    try:
        voices = await edge_tts.list_voices()
    except (aiohttp.ClientError, OSError, RuntimeError, ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=502, detail=f"Could not load voices: {e}") from e
    out: list[dict[str, str]] = []
    for v in voices:
        locale = (v.get("Locale") or "").lower()
        name = v.get("ShortName") or ""
        if not locale.startswith("en-gb") or "neural" not in name.lower():
            continue
        out.append(
            {
                "id": name,
                "label": v.get("FriendlyName") or name,
            }
        )
    out.sort(key=lambda x: x["label"])
    return out


@app.post("/api/render")
async def api_render(body: RenderRequest) -> FileResponse:
    fd, raw_path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    path = Path(raw_path)
    try:
        n = await render_markdown_to_mp3(body.markdown, body.voice, body.pause_ms, path)
    except ValueError as e:
        _unlink(path)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        _unlink(path)
        raise HTTPException(status_code=500, detail=str(e)) from e

    return FileResponse(
        path,
        media_type="audio/mpeg",
        filename="vocast.mp3",
        headers={"X-Phrase-Count": str(n)},
        background=BackgroundTask(_unlink, path),
    )


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
