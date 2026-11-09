"""One connection per operation, bounded lock waits, and database-enforced uniqueness."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Iterator


class SlugTaken(Exception):
    pass


class GenerationExhausted(Exception):
    pass


class Storage:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Set permissions at creation, before SQLite opens the database.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS links (
                    slug TEXT PRIMARY KEY NOT NULL,
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    visits INTEGER NOT NULL DEFAULT 0 CHECK (visits >= 0)
                )
            """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, url: str, slug: str | None = None) -> dict:
        created_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        for _ in range(8):
            candidate = slug if slug is not None else secrets.token_urlsafe(9)
            try:
                with self.connection() as db:
                    db.execute(
                        "INSERT INTO links (slug, url, created_at) VALUES (?, ?, ?)",
                        (candidate, url, created_at),
                    )
            except sqlite3.IntegrityError:
                if slug is not None:
                    raise SlugTaken from None
                continue
            return {"slug": candidate, "url": url, "created_at": created_at}
        raise GenerationExhausted

    def get(self, slug: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM links WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None

    def visit(self, slug: str) -> str | None:
        # UPDATE RETURNING makes lookup + count one atomic operation, including
        # races with deletion. A failed commit never results in a redirect.
        with self.connection() as db:
            row = db.execute(
                "UPDATE links SET visits = visits + 1 WHERE slug = ? RETURNING url", (slug,)
            ).fetchone()
        return row["url"] if row else None

    def delete(self, slug: str) -> bool:
        with self.connection() as db:
            return db.execute("DELETE FROM links WHERE slug = ?", (slug,)).rowcount > 0

