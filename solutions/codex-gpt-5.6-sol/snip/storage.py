"""SQLite persistence for snip."""

from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Iterator


class SlugConflictError(Exception):
    """Raised when a requested slug already exists."""


class SlugGenerationError(Exception):
    """Raised when no unique generated slug can be allocated."""


@dataclass(frozen=True, slots=True)
class Link:
    slug: str
    url: str
    created_at: str
    visits: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "slug": self.slug,
            "url": self.url,
            "created_at": self.created_at,
            "visits": self.visits,
        }


class LinkStore:
    """A small thread-safe-by-connection SQLite link store."""

    _GENERATE_ATTEMPTS = 12

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS links (
                    slug TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    visits INTEGER NOT NULL DEFAULT 0
                        CHECK (visits >= 0)
                ) WITHOUT ROWID
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

    def create(self, url: str, requested_slug: str | None = None) -> Link:
        created_at = self._now()
        if requested_slug is not None:
            try:
                self._insert(requested_slug, url, created_at)
            except sqlite3.IntegrityError as error:
                raise SlugConflictError(requested_slug) from error
            return Link(requested_slug, url, created_at, 0)

        for _ in range(self._GENERATE_ATTEMPTS):
            # Eight random bytes provide 64 bits of entropy and encode to 11
            # URL-safe characters without padding.
            slug = secrets.token_urlsafe(8)
            try:
                self._insert(slug, url, created_at)
            except sqlite3.IntegrityError:
                continue
            return Link(slug, url, created_at, 0)
        raise SlugGenerationError("could not allocate a unique slug")

    def _insert(self, slug: str, url: str, created_at: str) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO links (slug, url, created_at) VALUES (?, ?, ?)",
                (slug, url, created_at),
            )
            connection.commit()

    def get(self, slug: str) -> Link | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT slug, url, created_at, visits FROM links WHERE slug = ?",
                (slug,),
            ).fetchone()
        return self._to_link(row)

    def record_visit(self, slug: str) -> str | None:
        """Atomically increment a visit and return its destination URL."""
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE links SET visits = visits + 1 WHERE slug = ?", (slug,)
            )
            if cursor.rowcount == 0:
                connection.rollback()
                return None
            row = connection.execute(
                "SELECT url FROM links WHERE slug = ?", (slug,)
            ).fetchone()
            connection.commit()
        return str(row["url"])

    def delete(self, slug: str) -> bool:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute("DELETE FROM links WHERE slug = ?", (slug,))
            connection.commit()
        return cursor.rowcount == 1

    @staticmethod
    def _to_link(row: sqlite3.Row | None) -> Link | None:
        if row is None:
            return None
        return Link(
            slug=str(row["slug"]),
            url=str(row["url"]),
            created_at=str(row["created_at"]),
            visits=int(row["visits"]),
        )

