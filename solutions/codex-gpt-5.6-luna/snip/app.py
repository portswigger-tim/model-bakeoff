"""HTTP application and SQLite persistence for snip."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlsplit


MAX_URL_LENGTH = 2048
MAX_BODY_LENGTH = 64 * 1024
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class SlugTakenError(Exception):
    """Raised when a requested custom slug already exists."""


class LinkStore:
    """Small SQLite repository with serialized writes and atomic visit counts."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 10000")
        if path != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                slug TEXT PRIMARY KEY,
                target_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                visits INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._connection.commit()

    def create(self, target_url: str, requested_slug: str | None) -> dict[str, Any]:
        for _ in range(20):
            slug = requested_slug or secrets.token_urlsafe(8)
            created_at = utc_now()
            try:
                with self._lock, self._connection:
                    self._connection.execute(
                        "INSERT INTO links (slug, target_url, created_at) VALUES (?, ?, ?)",
                        (slug, target_url, created_at),
                    )
            except sqlite3.IntegrityError as error:
                if requested_slug:
                    raise SlugTakenError from error
                continue
            return {"slug": slug, "url": target_url, "created_at": created_at}
        raise RuntimeError("could not generate a unique slug")

    def get(self, slug: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT slug, target_url, created_at, visits FROM links WHERE slug = ?", (slug,)
            ).fetchone()
        return row_to_dict(row) if row else None

    def visit(self, slug: str) -> dict[str, Any] | None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE links SET visits = visits + 1 WHERE slug = ?", (slug,)
            )
            if cursor.rowcount == 0:
                return None
            row = self._connection.execute(
                "SELECT slug, target_url, created_at, visits FROM links WHERE slug = ?", (slug,)
            ).fetchone()
        return row_to_dict(row) if row else None

    def delete(self, slug: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM links WHERE slug = ?", (slug,))
        return cursor.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "slug": row["slug"],
        "url": row["target_url"],
        "created_at": row["created_at"],
        "visits": row["visits"],
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_target(value: Any) -> str | None:
    if not isinstance(value, str) or not value or len(value) > MAX_URL_LENGTH:
        return None
    if any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        parsed.port
    except ValueError:
        return None
    return value


def validate_slug(value: Any) -> str | None:
    if not isinstance(value, str) or not SLUG_PATTERN.fullmatch(value):
        return None
    return value


class SnipServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], store: LinkStore, base_url: str | None) -> None:
        super().__init__(address, handler)
        self.store = store
        self.base_url = base_url.rstrip("/") if base_url else None

    def server_close(self) -> None:
        self.store.close()
        super().server_close()


class SnipHandler(BaseHTTPRequestHandler):
    server: SnipServer

    def do_GET(self) -> None:
        path = self._path()
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if path.startswith("/api/links/"):
            slug = self._slug_from_api_path(path)
            if slug is None:
                self._send_error(HTTPStatus.NOT_FOUND, "link not found")
                return
            link = self.server.store.get(slug)
            if link is None:
                self._send_error(HTTPStatus.NOT_FOUND, "link not found")
                return
            self._send_json(HTTPStatus.OK, self._public_link(link))
            return
        if path.startswith("/api/"):
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        slug = path.removeprefix("/")
        if not slug or "/" in slug:
            self._send_error(HTTPStatus.NOT_FOUND, "link not found")
            return
        link = self.server.store.visit(slug)
        if link is None:
            self._send_error(HTTPStatus.NOT_FOUND, "link not found")
            return
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", link["url"])
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        if self._path() != "/api/links":
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self._authorized():
            return
        payload = self._read_json()
        if payload is None or not isinstance(payload, dict):
            self._send_error(HTTPStatus.BAD_REQUEST, "request body must be a JSON object")
            return
        target = validate_target(payload.get("url"))
        if target is None:
            self._send_error(HTTPStatus.BAD_REQUEST, "url must be an absolute http(s) URL up to 2048 characters")
            return
        requested_slug: str | None = None
        if "slug" in payload:
            requested_slug = validate_slug(payload["slug"])
            if requested_slug is None:
                self._send_error(HTTPStatus.BAD_REQUEST, "slug must be 3-32 letters, digits, '_' or '-'")
                return
        try:
            link = self.server.store.create(target, requested_slug)
        except SlugTakenError:
            self._send_error(HTTPStatus.CONFLICT, "slug is already taken")
            return
        self._send_json(HTTPStatus.CREATED, self._public_link(link))

    def do_DELETE(self) -> None:
        path = self._path()
        slug = self._slug_from_api_path(path)
        if slug is None:
            self._send_error(HTTPStatus.NOT_FOUND, "not found")
            return
        if not self._authorized():
            return
        if not self.server.store.delete(slug):
            self._send_error(HTTPStatus.NOT_FOUND, "link not found")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _path(self) -> str:
        return unquote(urlsplit(self.path).path)

    def _slug_from_api_path(self, path: str) -> str | None:
        prefix = "/api/links/"
        if not path.startswith(prefix):
            return None
        slug = path[len(prefix) :]
        if not slug or "/" in slug:
            return None
        return slug

    def _authorized(self) -> bool:
        expected = getattr(self.server, "api_token", None)
        authorization = self.headers.get("Authorization", "")
        supplied = authorization.removeprefix("Bearer ")
        if not expected or not supplied or not secrets.compare_digest(supplied, expected):
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Bearer realm="snip"')
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = json.dumps({"error": "authentication required"}).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False
        return True

    def _read_json(self) -> Any | None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_LENGTH:
            return None
        try:
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _public_link(self, link: dict[str, Any]) -> dict[str, Any]:
        result = {key: link[key] for key in ("slug", "url", "created_at")}
        result["short_url"] = self._short_url(link["slug"])
        if "visits" in link:
            result["visits"] = link["visits"]
        return result

    def _short_url(self, slug: str) -> str:
        if self.server.base_url:
            return f"{self.server.base_url}/{slug}"
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_address[1]}"
        return f"http://{host}/{slug}"

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message})

    def log_message(self, format: str, *args: Any) -> None:
        return


def create_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: str = "snip.db",
    api_token: str | None = None,
    base_url: str | None = None,
) -> SnipServer:
    store = LinkStore(db_path)
    server = SnipServer((host, port), SnipHandler, store, base_url)
    server.api_token = api_token
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the snip URL shortener")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--db", default="snip.db")
    parser.add_argument("--base-url", default=None)
    args = parser.parse_args()

    import os

    server = create_server(
        host=args.host,
        port=args.port,
        db_path=args.db,
        api_token=os.environ.get("SNIP_API_TOKEN"),
        base_url=args.base_url,
    )
    print(f"snip listening on http://{args.host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

