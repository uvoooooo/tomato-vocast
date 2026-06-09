"""
Local SQLite word library for Wordcast.

This is an *independent* feature: it stores a history of words the user has
saved, so they can later generate audio from a random sample of the library.
It does not touch the existing Markdown -> MP3 flow.

Uses Python's stdlib ``sqlite3`` (no extra dependency).

Storage location (the user can choose where the ``.db`` file lives):
    1. a path set at runtime via the web UI / ``set_db_path()`` (persisted to
       ``vocast_config.json``)
    2. otherwise the path saved in ``vocast_config.json``
    3. otherwise the ``VOCAST_DB`` environment variable
    4. otherwise the default ``vocast.db`` next to this module
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "vocast_config.json"
DEFAULT_DB_PATH = BASE_DIR / "vocast.db"

# Path chosen during this process (takes precedence over config/env).
_override: Path | None = None


def default_db_path() -> Path:
    return DEFAULT_DB_PATH


def _read_config_path() -> Path | None:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = data.get("db_path") if isinstance(data, dict) else None
    return Path(raw).expanduser() if raw else None


def get_db_path() -> Path:
    """Resolve the active database file path."""
    if _override is not None:
        return _override
    cfg = _read_config_path()
    if cfg is not None:
        return cfg
    env = os.environ.get("VOCAST_DB")
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB_PATH


def _resolve_target(path: str | os.PathLike) -> Path:
    """Turn user input into a concrete .db file path.

    A directory (existing, or a value ending in a path separator) becomes
    ``<dir>/vocast.db``; anything else is used as the file path verbatim.
    """
    raw = str(path).strip()
    if not raw:
        raise ValueError("empty path")
    p = Path(raw).expanduser()
    if p.is_dir() or raw.endswith(("/", os.sep)):
        p = p / "vocast.db"
    return p


def set_db_path(path: str | os.PathLike, *, persist: bool = True, migrate: bool = False) -> Path:
    """Switch the active database file, creating its folder and table.

    If ``migrate`` is true and the previous database has words that the target
    does not yet contain, copy them into the new file. The choice is saved to
    ``vocast_config.json`` when ``persist`` is true so it survives restarts.
    """
    global _override
    target = _resolve_target(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    old_path = get_db_path()
    old_words: list[str] = []
    if migrate and old_path != target and old_path.exists():
        try:
            with sqlite3.connect(old_path) as src:
                src.row_factory = sqlite3.Row
                old_words = [r["text"] for r in src.execute("SELECT text FROM words")]
        except sqlite3.Error:
            old_words = []

    _override = target
    init_db()
    if old_words:
        add_words(old_words)

    if persist:
        try:
            CONFIG_PATH.write_text(
                json.dumps({"db_path": str(target)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
    return target


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the words table if it does not exist."""
    get_db_path().parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS words (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                text       TEXT NOT NULL,
                text_key   TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


def add_words(words: list[str]) -> int:
    """Insert words, skipping case-insensitive duplicates. Returns count added."""
    added = 0
    with _connect() as conn:
        for w in words:
            text = w.strip()
            if not text:
                continue
            key = text.casefold()
            try:
                conn.execute(
                    "INSERT INTO words (text, text_key) VALUES (?, ?)",
                    (text, key),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass
    return added


def count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM words").fetchone()
        return int(row["c"])


def all_words(limit: int | None = None) -> list[dict]:
    sql = "SELECT id, text, created_at FROM words ORDER BY created_at DESC, id DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def random_words(n: int) -> list[str]:
    """Return up to ``n`` randomly chosen words from the library."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT text FROM words ORDER BY RANDOM() LIMIT ?", (int(n),)
        ).fetchall()
        return [r["text"] for r in rows]


def delete_word(word_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM words WHERE id = ?", (word_id,))
        return cur.rowcount > 0


def clear() -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM words")
        return cur.rowcount
