"""A small persistent URL shortener using only the Python standard library."""
import hmac
from contextlib import contextmanager
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlsplit

SLUG = re.compile(r"[A-Za-z0-9_-]{3,32}\Z")
MAX_BODY = 16 * 1024


def valid_url(value):
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme.lower() in ("http", "https") and bool(parsed.hostname)
                and parsed.port != 0 and "\\" not in parsed.netloc)
    except ValueError:
        return False


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS links (slug TEXT PRIMARY KEY, url TEXT NOT NULL, created_at TEXT NOT NULL, visits INTEGER NOT NULL DEFAULT 0)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, url, slug=None):
        created = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        for _ in range(20):
            candidate = slug if slug is not None else secrets.token_urlsafe(9)
            try:
                with self.connect() as db:
                    db.execute("INSERT INTO links (slug, url, created_at) VALUES (?, ?, ?)", (candidate, url, created))
                return {"slug": candidate, "url": url, "created_at": created}
            except sqlite3.IntegrityError:
                if slug is not None:
                    return None
        raise RuntimeError("Unable to generate a unique slug")

    def get(self, slug, visit=False):
        with self.connect() as db:
            if visit:
                db.execute("UPDATE links SET visits = visits + 1 WHERE slug = ?", (slug,))
            row = db.execute("SELECT slug, url, created_at, visits FROM links WHERE slug = ?", (slug,)).fetchone()
            return dict(row) if row else None

    def delete(self, slug):
        with self.connect() as db:
            return db.execute("DELETE FROM links WHERE slug = ?", (slug,)).rowcount > 0


class Server(ThreadingHTTPServer):
    def __init__(self, address, store, token, base_url):
        super().__init__(address, Handler)
        self.store, self.token, self.base_url = store, token, base_url.rstrip('/')


class Handler(BaseHTTPRequestHandler):
    server_version = "snip"
    sys_version = ""

    def respond(self, status, data=None, headers=None):
        body = json.dumps(data, ensure_ascii=True).encode() if data is not None else b''
        self.send_response(status)
        if data is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def error(self, status, message):
        self.respond(status, {"error": message})

    def authorized(self):
        supplied = self.headers.get('Authorization', '')
        expected = 'Bearer ' + self.server.token
        if not hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
            self.error(401, 'Unauthorized')
            return False
        return True

    def metadata(self, row):
        return {**row, 'short_url': self.server.base_url + '/' + row['slug']}

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            self.respond(200, {'status': 'ok'})
        elif path.startswith('/api/links/'):
            slug = path[len('/api/links/'):]
            row = self.server.store.get(slug)
            self.respond(200, self.metadata(row)) if row else self.error(404, 'Not found')
        elif path.count('/') == 1 and path.startswith('/'):
            row = self.server.store.get(path[1:], visit=True)
            self.respond(302, headers={'Location': quote(row['url'], safe=":/?#[]@!$&'()*+,;=%")}) if row else self.error(404, 'Not found')
        else:
            self.error(404, 'Not found')

    def do_POST(self):
        if urlsplit(self.path).path != '/api/links':
            self.error(404, 'Not found')
            return
        if not self.authorized():
            return
        try:
            if self.headers.get('Transfer-Encoding'):
                raise ValueError()
            length = int(self.headers.get('Content-Length', ''))
            if length < 0 or length > MAX_BODY:
                raise ValueError()
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not valid_url(body.get('url')):
                raise ValueError()
            slug = body.get('slug')
            if 'slug' in body and (not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug == 'healthz'):
                raise ValueError()
        except (ValueError, UnicodeDecodeError, RecursionError):
            self.close_connection = True
            self.error(400, 'Invalid request')
            return
        row = self.server.store.create(body['url'], slug)
        if row is None:
            self.error(409, 'Slug already taken')
        else:
            self.respond(201, self.metadata(row))

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if not path.startswith('/api/links/'):
            self.error(404, 'Not found')
            return
        if not self.authorized():
            return
        if self.server.store.delete(path[len('/api/links/'):]):
            self.respond(204)
        else:
            self.error(404, 'Not found')


def main():
    token = os.environ.get('SNIP_API_TOKEN', '')
    if not token:
        raise SystemExit('SNIP_API_TOKEN must be set to a non-empty secret')
    host = os.environ.get('SNIP_HOST', '127.0.0.1')
    port = int(os.environ.get('SNIP_PORT', '8000'))
    base_url = os.environ.get('SNIP_BASE_URL', f'http://localhost:{port}').rstrip('/')
    if not valid_url(base_url) or urlsplit(base_url).query or urlsplit(base_url).fragment or urlsplit(base_url).path:
        raise SystemExit('SNIP_BASE_URL must be an absolute HTTP(S) origin')
    server = Server((host, port), Store(os.environ.get('SNIP_DB', 'snip.db')), token, base_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
