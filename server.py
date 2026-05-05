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

from wordcast import DEFAULT_VOICE, render_markdown_to_mp3

WEB_DIR = Path(__file__).resolve().parent / "web"


class RenderRequest(BaseModel):
    markdown: str = Field(..., min_length=1)
    voice: str = DEFAULT_VOICE
    pause_ms: int = Field(700, ge=0, le=5000)


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


app = FastAPI(title="Wordcast")


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
