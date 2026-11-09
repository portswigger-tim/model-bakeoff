"""HTTP API and SQLite storage for Snip."""

from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048
MAX_BODY_LENGTH = 8192
SLUG_RE = re.compile(r"\A[A-Za-z0-9_-]{3,32}\Z")
DEFAULT_DB_PATH = Path("data/snip.sqlite3")


def database_path() -> Path:
    return Path(os.environ.get("SNIP_DB_PATH", str(DEFAULT_DB_PATH)))


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def database(path: Path):
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(path: Path) -> None:
    with database(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS links (
                slug TEXT PRIMARY KEY,
                target_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                visits INTEGER NOT NULL DEFAULT 0 CHECK (visits >= 0)
            )"""
        )


def validate_url(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_URL_LENGTH:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        # Accessing .port also rejects malformed ports.
        _ = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    # Avoid storing credentials that can be leaked in a redirect or analytics.
    if parsed.username is not None or parsed.password is not None:
        return None
    return value


def record_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "slug": row["slug"],
        "url": row["target_url"],
        "created_at": row["created_at"],
        "visits": row["visits"],
    }


class SnipHandler(BaseHTTPRequestHandler):
    """Handler whose configuration is set by ``make_handler``."""

    db_path = DEFAULT_DB_PATH
    api_token = ""
    base_url = "http://localhost:8000"
    server_version = "Snip/1.0"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:
        # Keep request logs useful while never logging headers or credentials.
        super().log_message(format, *args)

    def send_json(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json(status, {"error": message})

    def authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        scheme, separator, token = supplied.partition(" ")
        return bool(
            self.api_token
            and separator
            and scheme.lower() == "bearer"
            and token
            and hmac.compare_digest(token, self.api_token)
        )

    def read_json(self) -> dict[str, object] | None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            return None
        if length < 0 or length > MAX_BODY_LENGTH:
            return None
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return

        if path.startswith("/api/links/"):
            slug = path[len("/api/links/") :]
            if not SLUG_RE.fullmatch(slug):
                self.send_error_json(404, "link not found")
                return
            with database(self.db_path) as connection:
                row = connection.execute(
                    "SELECT slug, target_url, created_at, visits FROM links WHERE slug = ?",
                    (slug,),
                ).fetchone()
            if row is None:
                self.send_error_json(404, "link not found")
            else:
                self.send_json(200, record_from_row(row))
            return

        slug = path.removeprefix("/")
        if "/" in slug or not SLUG_RE.fullmatch(slug):
            self.send_error_json(404, "link not found")
            return
        with database(self.db_path) as connection:
            with connection:
                row = connection.execute(
                    "SELECT target_url FROM links WHERE slug = ?", (slug,)
                ).fetchone()
                if row is not None:
                    connection.execute(
                        "UPDATE links SET visits = visits + 1 WHERE slug = ?", (slug,)
                    )
        if row is None:
            self.send_error_json(404, "link not found")
            return
        self.send_response(302)
        self.send_header("Location", row["target_url"])
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlsplit(self.path).path != "/api/links":
            self.send_error_json(404, "not found")
            return
        if not self.authorized():
            self.send_error_json(401, "unauthorized")
            return
        body = self.read_json()
        if body is None:
            self.send_error_json(400, "request body must be a JSON object")
            return
        target = validate_url(body.get("url"))
        if target is None:
            self.send_error_json(400, "url must be an absolute http or https URL up to 2048 characters")
            return
        custom_slug = body.get("slug")
        if custom_slug is not None and (
            not isinstance(custom_slug, str) or not SLUG_RE.fullmatch(custom_slug)
        ):
            self.send_error_json(400, "slug must be 3-32 characters using letters, numbers, _ or -")
            return

        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        attempts = 1 if custom_slug is not None else 8
        for _ in range(attempts):
            slug = custom_slug if custom_slug is not None else secrets.token_urlsafe(9)
            try:
                with database(self.db_path) as connection:
                    connection.execute(
                        "INSERT INTO links (slug, target_url, created_at) VALUES (?, ?, ?)",
                        (slug, target, created_at),
                    )
            except sqlite3.IntegrityError:
                if custom_slug is not None:
                    self.send_error_json(409, "slug is already taken")
                    return
                continue
            self.send_json(
                201,
                {
                    "slug": slug,
                    "url": target,
                    "short_url": f"{self.base_url}/{slug}",
                    "created_at": created_at,
                },
            )
            return
        self.send_error_json(503, "could not allocate a unique slug; retry the request")

    def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        prefix = "/api/links/"
        if not path.startswith(prefix):
            self.send_error_json(404, "not found")
            return
        if not self.authorized():
            self.send_error_json(401, "unauthorized")
            return
        slug = path[len(prefix) :]
        if not SLUG_RE.fullmatch(slug):
            self.send_error_json(404, "link not found")
            return
        with database(self.db_path) as connection:
            cursor = connection.execute("DELETE FROM links WHERE slug = ?", (slug,))
        if cursor.rowcount == 0:
            self.send_error_json(404, "link not found")
        else:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()


def make_handler(db_path: Path, api_token: str, base_url: str) -> type[SnipHandler]:
    return type(
        "ConfiguredSnipHandler",
        (SnipHandler,),
        {"db_path": db_path, "api_token": api_token, "base_url": base_url.rstrip("/")},
    )


def main() -> None:
    host = os.environ.get("SNIP_HOST", "127.0.0.1")
    port = int(os.environ.get("SNIP_PORT", "8000"))
    token = os.environ.get("SNIP_API_TOKEN", "")
    if not token:
        raise SystemExit("SNIP_API_TOKEN must be set before starting Snip")
    path = database_path()
    initialize_database(path)
    base_url = os.environ.get("SNIP_BASE_URL", f"http://localhost:{port}")
    if not base_url.startswith(("http://", "https://")):
        raise SystemExit("SNIP_BASE_URL must begin with http:// or https://")
    server = ThreadingHTTPServer((host, port), make_handler(path, token, base_url))
    print(f"Snip listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

