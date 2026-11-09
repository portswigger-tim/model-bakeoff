"""HTTP API for the snip URL shortener."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import re
from urllib.parse import quote, urlsplit, urlunsplit

from .store import Store


SLUG_RE = re.compile(r"[A-Za-z0-9_-]{3,32}\Z")
MAX_BODY_BYTES = 16_384


def validate_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 or ch == "\\" for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        value.encode("utf-8")
        if parsed.hostname:
            parsed.hostname.encode("idna")
        # User information makes links misleading and is rarely useful here.
        return (
            parsed.scheme in ("http", "https")
            and bool(parsed.netloc)
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.port != 0
        )
    except (ValueError, UnicodeError):
        return False


def redirect_location(url):
    """Encode Unicode for an ASCII Location header without changing stored URL."""
    parsed = urlsplit(url)
    host = parsed.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{parsed.port}" if parsed.port is not None else "")
    safe = "/%:@!$&'()*+,;=~"
    return urlunsplit(
        (parsed.scheme, netloc, quote(parsed.path, safe=safe),
         quote(parsed.query, safe=safe + "?"), quote(parsed.fragment, safe=safe + "?"))
    )


class SnipServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store, token, base_url):
        if not token:
            raise ValueError("SNIP_API_TOKEN must be set")
        if not validate_url(base_url):
            raise ValueError("SNIP_BASE_URL must be an absolute HTTP or HTTPS URL")
        parsed = urlsplit(base_url)
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("SNIP_BASE_URL must be an origin without a path or query")
        self.store = store
        self.token = token
        self.base_url = base_url.rstrip("/")
        super().__init__(address, SnipHandler)


class SnipHandler(BaseHTTPRequestHandler):
    server: SnipServer
    server_version = "snip"
    sys_version = ""

    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, message):
        self._json(status, {"error": message})

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.token
        if not hmac.compare_digest(header.encode("utf-8"), expected.encode("utf-8")):
            self._error(401, "Unauthorized")
            return False
        return True

    def _body(self):
        media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media_type != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as exc:
            raise ValueError("Content-Length is required") from exc
        if length < 1 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid body size")
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON body") from exc
        if not isinstance(body, dict) or set(body) - {"url", "slug"}:
            raise ValueError("Expected an object with url and optional slug")
        return body

    def do_POST(self):
        if self.path != "/api/links":
            return self._error(404, "Not found")
        if not self._authorized():
            return
        try:
            body = self._body()
        except ValueError as exc:
            return self._error(400, str(exc))
        url = body.get("url")
        slug = body.get("slug")
        if not validate_url(url):
            return self._error(400, "url must be an absolute HTTP or HTTPS URL of at most 2048 characters")
        if "slug" in body and (not isinstance(slug, str) or not SLUG_RE.fullmatch(slug) or slug == "healthz"):
            return self._error(400, "slug must be 3-32 ASCII letters, digits, underscores or hyphens, and cannot be healthz")
        try:
            link = self.server.store.create(url, slug)
        except RuntimeError:
            return self._error(503, "Could not allocate a slug")
        if link is None:
            return self._error(409, "Slug already taken")
        link["short_url"] = f"{self.server.base_url}/{link['slug']}"
        self._json(201, link)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/healthz":
            return self._json(200, {"status": "ok"})
        if path.startswith("/api/links/"):
            slug = path[len("/api/links/"):]
            if not SLUG_RE.fullmatch(slug):
                return self._error(404, "Not found")
            link = self.server.store.get(slug)
            if link is None:
                return self._error(404, "Not found")
            link["short_url"] = f"{self.server.base_url}/{slug}"
            return self._json(200, link)
        if path.startswith("/") and SLUG_RE.fullmatch(path[1:]):
            url = self.server.store.visit(path[1:])
            if url is None:
                return self._error(404, "Not found")
            location = redirect_location(url)
            self.send_response(302)
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self._error(404, "Not found")

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if not path.startswith("/api/links/") or not SLUG_RE.fullmatch(path[len("/api/links/"):]):
            return self._error(404, "Not found")
        if not self._authorized():
            return
        if not self.server.store.delete(path[len("/api/links/"):]):
            return self._error(404, "Not found")
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
