"""HTTP application for snip, built on the Python standard library."""

from __future__ import annotations

import hmac
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import quote, urlsplit

from .storage import LinkStore, SlugConflictError, SlugGenerationError

SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
MAX_REQUEST_BYTES = 16 * 1024
MAX_URL_CHARACTERS = 2048


class InputError(ValueError):
    pass


def validate_url(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_URL_CHARACTERS:
        raise InputError("url must be a non-empty string of at most 2048 characters")
    if "\\" in value or any(character.isspace() or ord(character) < 32 for character in value):
        raise InputError("url must not contain whitespace or control characters")
    try:
        parsed = urlsplit(value)
        # Accessing these properties performs additional bracket and port checks.
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise InputError("url is not a valid absolute URL") from error
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
        raise InputError("url must be an absolute http or https URL")
    return value


def validate_slug(value: Any) -> str:
    if not isinstance(value, str) or SLUG_PATTERN.fullmatch(value) is None:
        raise InputError("slug must be 3-32 characters using A-Z, a-z, 0-9, _ or -")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise InputError(f"invalid JSON constant: {value}")


def destination_header(url: str) -> str:
    """Encode an IRI to an ASCII-safe Location header."""
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise InputError("url hostname cannot be encoded") from error
    if ":" in ascii_hostname and not ascii_hostname.startswith("["):
        ascii_hostname = f"[{ascii_hostname}]"
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = quote(parsed.netloc.rsplit("@", 1)[0], safe=":%") + "@"
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{userinfo}{ascii_hostname}{port}"
    path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
    query = quote(parsed.query, safe="/?@:!$&'()*+,;=%-._~")
    fragment = quote(parsed.fragment, safe="/?@:!$&'()*+,;=%-._~")
    return parsed._replace(netloc=netloc, path=path, query=query, fragment=fragment).geturl()


class SnipApplication:
    def __init__(self, store: LinkStore, api_token: str, base_url: str) -> None:
        if not api_token:
            raise ValueError("api_token must not be empty")
        self.store = store
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")


class SnipServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], application: SnipApplication) -> None:
        self.application = application
        super().__init__(address, SnipRequestHandler)


class SnipRequestHandler(BaseHTTPRequestHandler):
    server: SnipServer
    server_version = "snip/1.0"
    sys_version = ""

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return

        api_slug = self._slug_after(path, "/api/links/")
        if api_slug is not None:
            link = self.server.application.store.get(api_slug)
            if link is None:
                self._error(HTTPStatus.NOT_FOUND, "not_found", "link not found")
                return
            self._send_json(HTTPStatus.OK, link.as_dict())
            return

        slug = path.removeprefix("/")
        if "/" in slug or SLUG_PATTERN.fullmatch(slug) is None:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "link not found")
            return
        target = self.server.application.store.record_visit(slug)
        if target is None:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "link not found")
            return
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", destination_header(target))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/links":
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        if not self._authorized():
            return
        try:
            body = self._read_json_object()
            unknown_fields = set(body) - {"url", "slug"}
            if unknown_fields:
                raise InputError(f"unknown JSON field: {sorted(unknown_fields)[0]}")
            if "url" not in body:
                raise InputError("url is required")
            url = validate_url(body["url"])
            slug = validate_slug(body["slug"]) if "slug" in body else None
        except InputError as error:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))
            return

        try:
            link = self.server.application.store.create(url, slug)
        except SlugConflictError:
            self._error(HTTPStatus.CONFLICT, "slug_conflict", "slug is already taken")
            return
        except SlugGenerationError:
            self._error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "slug_unavailable",
                "could not allocate a slug; please retry",
            )
            return
        payload = {
            "slug": link.slug,
            "url": link.url,
            "short_url": f"{self.server.application.base_url}/{link.slug}",
            "created_at": link.created_at,
        }
        self._send_json(HTTPStatus.CREATED, payload)

    def do_DELETE(self) -> None:
        path = urlsplit(self.path).path
        slug = self._slug_after(path, "/api/links/")
        if slug is None:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "route not found")
            return
        if not self._authorized():
            return
        if not self.server.application.store.delete(slug):
            self._error(HTTPStatus.NOT_FOUND, "not_found", "link not found")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self) -> None:
        self._method_not_allowed("GET, POST, DELETE")

    def do_PUT(self) -> None:
        self._method_not_allowed("GET, POST, DELETE")

    def do_PATCH(self) -> None:
        self._method_not_allowed("GET, POST, DELETE")

    def _method_not_allowed(self, allow: str) -> None:
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"error": {"code": "method_not_allowed", "message": "method not allowed"}},
            {"Allow": allow},
        )

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.application.api_token}"
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode(), expected.encode()):
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"code": "unauthorized", "message": "valid bearer token required"}},
                {"WWW-Authenticate": "Bearer"},
            )
            return False
        return True

    def _read_json_object(self) -> dict[str, Any]:
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise InputError("Content-Type must be application/json")
        if self.headers.get("Transfer-Encoding"):
            raise InputError("transfer-encoded request bodies are not supported")
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError as error:
            raise InputError("Content-Length is invalid") from error
        if length < 0:
            raise InputError("Content-Length is required")
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            raise InputError("request body is too large")
        try:
            raw = self.rfile.read(length)
            value = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InputError("request body must be valid UTF-8 JSON") from error
        if not isinstance(value, dict):
            raise InputError("request body must be a JSON object")
        return value

    @staticmethod
    def _slug_after(path: str, prefix: str) -> str | None:
        if not path.startswith(prefix):
            return None
        slug = path[len(prefix) :]
        if "/" in slug or SLUG_PATTERN.fullmatch(slug) is None:
            return None
        return slug

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def _send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if headers:
            for name, value in headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

