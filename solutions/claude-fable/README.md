# snip

A small URL-shortener HTTP service. Python 3.11+, FastAPI, SQLite (stdlib) for local persistence.

## Install

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync
```

## Configure

All configuration is via environment variables (see `.env.example`; no secrets are committed).

| Variable | Default | Purpose |
|---|---|---|
| `SNIP_API_TOKEN` | *(unset)* | Bearer token required for `POST`/`DELETE`. If unset, all writes return `401` (fail closed). |
| `SNIP_DB_PATH` | `data/snip.db` | SQLite file; parent directory is created. |
| `SNIP_BASE_URL` | request's base URL | Public origin used to build `short_url` (set this behind a proxy). |
| `SNIP_HOST` / `SNIP_PORT` | `127.0.0.1` / `8000` | Bind address. |

## Run

```sh
export SNIP_API_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run python -m snip
```

## API

```sh
# create (slug optional)
curl -X POST localhost:8000/api/links -H "Authorization: Bearer $SNIP_API_TOKEN" \
  -H 'Content-Type: application/json' -d '{"url":"https://example.com","slug":"hello"}'
# -> 201 {"slug","url","short_url","created_at"}

curl -i localhost:8000/hello            # 302 to the target, counts a visit
curl localhost:8000/api/links/hello     # metadata incl. "visits"
curl -X DELETE localhost:8000/api/links/hello -H "Authorization: Bearer $SNIP_API_TOKEN"  # 204
curl localhost:8000/healthz             # 200
```

- URLs: absolute `http`/`https`, max 2048 chars, no whitespace/control characters.
- Slugs: 3–32 of `[A-Za-z0-9_-]`; taken → `409`; `api`, `healthz`, `docs`, `redoc`, `openapi` are reserved. Generated slugs are 8 chars from a CSPRNG (~47 bits) and retried on collision.
- Errors are JSON: `{"error": "..."}` with `400`/`401`/`404`/`409`.

## Test

```sh
uv run pytest
```
