import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class SlugTaken(Exception):
    pass


@dataclass(frozen=True)
class Link:
    slug: str
    url: str
    created_at: str
    visits: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS links (
    slug       TEXT PRIMARY KEY,
    url        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    visits     INTEGER NOT NULL DEFAULT 0
) WITHOUT ROWID;
"""


class LinkStore:
    """SQLite-backed store. One connection guarded by a lock; WAL for durability."""

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create(self, slug: str, url: str) -> Link:
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO links (slug, url, created_at) VALUES (?, ?, ?)",
                    (slug, url, created_at),
                )
            except sqlite3.IntegrityError:
                raise SlugTaken(slug) from None
        return Link(slug, url, created_at, 0)

    def get(self, slug: str) -> Link | None:
        with self._lock:
            row = self._db.execute(
                "SELECT slug, url, created_at, visits FROM links WHERE slug = ?", (slug,)
            ).fetchone()
        return Link(*row) if row else None

    def visit(self, slug: str) -> str | None:
        """Atomically count a visit and return the target URL, or None if unknown."""
        with self._lock:
            row = self._db.execute(
                "UPDATE links SET visits = visits + 1 WHERE slug = ? RETURNING url", (slug,)
            ).fetchone()
        return row[0] if row else None

    def delete(self, slug: str) -> bool:
        with self._lock:
            return self._db.execute("DELETE FROM links WHERE slug = ?", (slug,)).rowcount > 0
