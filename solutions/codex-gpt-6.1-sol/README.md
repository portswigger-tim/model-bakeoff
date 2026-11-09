# snip

A small URL shortener with a JSON API, bearer-authenticated writes, and durable
SQLite storage. Flask handles HTTP, Waitress serves it without development mode,
and the test suite uses Python's built-in `unittest`. No external service is
required; redirect targets are never fetched by the server.

## Install and run

Use Python **3.11 or newer**, with SQLite **3.35 or newer** (for `UPDATE RETURNING`).
Run these commands from this directory on macOS/Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export SNIP_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m snip
```

The server binds to `127.0.0.1:8000`. It refuses to start without a token.
Keep the token in your environment or a secret manager; do not commit it.
The application does **not** load `.env` files automatically. Keep the generated
token available to API clients; creating a new token on startup changes access
to write endpoints, but does not affect stored links.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `SNIP_API_TOKEN` | Required | Shared bearer token for all writes; no whitespace |
| `SNIP_DB_PATH` | `data/snip.db` | SQLite file, relative to the working directory or absolute |
| `SNIP_BASE_URL` | `http://localhost:8000` | Public HTTP(S) origin used in returned short URLs |
| `SNIP_HOST` | `127.0.0.1` | Listen address; use `0.0.0.0` to expose the server |
| `SNIP_PORT` | `8000` | Listen port, from 1 to 65535 |

Set `SNIP_BASE_URL` explicitly when changing the port or deploying behind HTTPS.
It accepts an origin with an optional trailing slash, without credentials, path,
query, or fragment. Request `Host` and forwarded headers never determine short
URLs. Place the service behind a TLS reverse proxy for public deployments;
Waitress discards untrusted proxy headers. There is no Flask debug server.

## Use the API

In another terminal, export the **same** `SNIP_API_TOKEN` used by the server.

```sh
curl -i http://localhost:8000/healthz

curl -i -X POST http://localhost:8000/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs?lang=en","slug":"docs"}'

curl -i http://localhost:8000/docs
curl -i http://localhost:8000/api/links/docs

curl -i -X DELETE http://localhost:8000/api/links/docs \
  -H "Authorization: Bearer $SNIP_API_TOKEN"
```

The create response is `201`, with a `Location` header pointing to the metadata:

```json
{
  "slug": "docs",
  "url": "https://example.com/docs?lang=en",
  "short_url": "http://localhost:8000/docs",
  "created_at": "2026-11-09T12:00:00.000000Z"
}
```

| Endpoint | Result |
| --- | --- |
| `POST /api/links` | `201`; JSON object with `url` and optionally `slug`; requires bearer token |
| `GET /{slug}` | `302` to the stored URL; atomically increments `visits` |
| `GET /api/links/{slug}` | `200`; creation fields plus integer `visits`, initially zero |
| `DELETE /api/links/{slug}` | `204`, empty body; requires bearer token |
| `GET /healthz` | `200`, `{"status":"ok"}`; process liveness |

Missing or incorrect write credentials return `401` with `WWW-Authenticate`.
Invalid JSON/input returns `400`; duplicate slugs return `409`. Unknown links
return `404`, including repeated deletes. API errors have the form
`{"error":"human-readable message"}`. Request bodies over 32 KiB return `413`;
unsupported methods return `405`. Storage failures return `503` with
`Retry-After: 1`; retrying a create after an uncertain network failure may create
another link, since there is no idempotency-key API.

Targets must be absolute HTTP(S) URLs, up to 2048 characters, with a hostname and
valid port. Whitespace, control characters, backslashes, and invalid Unicode are
rejected. The original accepted URL is stored. Custom slugs are case-sensitive,
3–32 ASCII letters/digits/underscores/hyphens. `healthz` is reserved. Unknown
JSON fields and explicit `null` slugs are rejected; omit `slug` to generate one.
Generated slugs contain 72 bits of cryptographic randomness (12 URL-safe
characters), with uniqueness enforced by SQLite and bounded collision retries.

Metadata reads and `HEAD` requests do not count visits. Redirects and metadata
use `Cache-Control: no-store` so caches cannot silently skip visit counting or
keep deleted links alive. Counts measure received GET requests, including bots
and repeat requests, rather than unique people. Destinations with non-ASCII
characters may be URI-encoded in the HTTP `Location` header.

## Tests

After installation, run one command from this directory:

```sh
python -m unittest discover -v
```

Tests use temporary local databases, with no configured token or running service
required. They cover validation, authentication, all endpoints, collisions,
concurrent creation and visit counts, persistence, errors, and a real Waitress
HTTP lifecycle with a process restart. They never contact destination URLs.

## Storage and operation

The schema lives in `snip/storage.py`; routes and JSON errors are in
`snip/__init__.py`, and configuration is in `snip/config.py`. Each storage
operation has its own connection and transaction. SQLite WAL permits concurrent
readers; writes serialize with a five-second lock timeout. Redirect lookup and
visit increment use one SQL statement, preventing lost updates and deletion
races. The newly created database is mode `0600` and its new parent directory
is mode `0700` on POSIX. Existing permissions are preserved.

Keep the database on a local persistent disk. Restarting the server preserves
links, timestamps, and counts. Do not delete its `-wal`/`-shm` files while it is
running. For a simple consistent backup, stop the server and copy the database
and any associated WAL files together, or use SQLite's online backup API. Data,
virtual environments, build outputs, and local secrets are ignored by Git.

This is a single-host service: there is no per-user authorization, expiry,
analytics UI, abuse filtering, rate limiting, or distributed storage. Public
metadata is part of the API contract; short slugs are not an access-control
mechanism. Apply request/rate limits at the proxy if exposed to untrusted traffic.

