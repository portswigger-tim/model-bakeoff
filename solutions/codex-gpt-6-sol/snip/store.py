"""SQLite storage for links and visit counts."""

from contextlib import contextmanager
from datetime import datetime, timezone
import secrets
import sqlite3


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS links (
                    slug TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    visits INTEGER NOT NULL DEFAULT 0
                )"""
            )

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create(self, url, slug=None):
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        for _ in range(10):
            candidate = slug if slug is not None else secrets.token_urlsafe(9)
            try:
                with self._connection() as db:
                    db.execute(
                        "INSERT INTO links (slug, url, created_at) VALUES (?, ?, ?)",
                        (candidate, url, created_at),
                    )
                return {"slug": candidate, "url": url, "created_at": created_at}
            except sqlite3.IntegrityError:
                if slug is not None:
                    return None
        raise RuntimeError("Could not generate a unique slug")

    def get(self, slug):
        with self._connection() as db:
            row = db.execute(
                "SELECT slug, url, created_at, visits FROM links WHERE slug = ?", (slug,)
            ).fetchone()
            return dict(row) if row else None

    def visit(self, slug):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT url FROM links WHERE slug = ?", (slug,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE links SET visits = visits + 1 WHERE slug = ?", (slug,))
            return row["url"]

    def delete(self, slug):
        with self._connection() as db:
            result = db.execute("DELETE FROM links WHERE slug = ?", (slug,))
            return result.rowcount > 0
