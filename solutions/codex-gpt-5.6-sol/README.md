# snip

`snip` is a small, production-minded URL-shortener HTTP service. It uses only
the Python standard library and persists links in a local SQLite database.

## Requirements and installation

- Python 3.11 or newer

There are no third-party runtime dependencies. From the project directory,
optionally create an isolated environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
```

## Configuration

`SNIP_API_TOKEN` is required. Other settings have safe local defaults:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNIP_API_TOKEN` | required | Bearer token for create and delete requests |
| `SNIP_HOST` | `127.0.0.1` | Listen address |
| `SNIP_PORT` | `8000` | Listen port |
| `SNIP_DB_PATH` | `snip.db` | SQLite database path |
| `SNIP_BASE_URL` | derived from host/port | Public origin used in `short_url` |

Use a long random token in a real deployment, for example:

```sh
export SNIP_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SNIP_BASE_URL="https://snip.example.com"
```

Keep TLS termination in a reverse proxy and set `SNIP_BASE_URL` to its public
HTTPS origin. The service binds only to loopback unless configured otherwise.

## Run

```sh
SNIP_API_TOKEN=development-only-token python3 -m snip
```

Create and use a link:

```sh
curl -sS -X POST http://127.0.0.1:8000/api/links \
  -H 'Authorization: Bearer development-only-token' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs","slug":"docs"}'
curl -i http://127.0.0.1:8000/docs
curl -sS http://127.0.0.1:8000/api/links/docs
curl -i -X DELETE http://127.0.0.1:8000/api/links/docs \
  -H 'Authorization: Bearer development-only-token'
```

`GET /healthz` is unauthenticated and suitable for a health probe. Error
responses are JSON objects with a stable code and a human-readable message.

## Test

Run the complete suite with one command:

```sh
python3 -m unittest discover -s tests -v
```

The tests start the real HTTP server on an ephemeral loopback port and cover
authentication, validation, collisions, redirects, visit counting,
concurrency, deletion, and persistence.

