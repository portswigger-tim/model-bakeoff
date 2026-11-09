# snip

A small URL shortener backed by a local SQLite database. It uses Python's standard library, so there are no packages or external services to install.

## Requirements and setup

Install Python 3.9 or later. From this directory, set a long, private API token:

```sh
export SNIP_API_TOKEN='replace-with-a-long-random-secret'
python3 -m snip
```

The server listens on `127.0.0.1:8000` by default and creates `snip.db` in the current directory. The token is required at startup. Keep the database on a persistent local disk and back it up like any other application data.

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNIP_HOST` | `127.0.0.1` | Listen address. Keep it on loopback unless a trusted proxy provides TLS. |
| `SNIP_PORT` | `8000` | Listen port. |
| `SNIP_DB_PATH` | `snip.db` | SQLite file path. |
| `SNIP_BASE_URL` | `http://127.0.0.1:$SNIP_PORT` | Public HTTP(S) origin used in `short_url`. Set this when using a proxy or custom hostname. |

For a public deployment, put the server behind an HTTPS reverse proxy and set `SNIP_BASE_URL` to its public origin. The API token grants create and delete access; do not expose it in client-side code.

## API

Create a link:

```sh
curl -i -X POST http://127.0.0.1:8000/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/page","slug":"example"}'
```

Omit `slug` to generate a random one. Custom slugs have 3–32 ASCII letters, digits, underscores, or hyphens; `healthz` is reserved. URLs must be absolute HTTP(S) URLs of at most 2048 characters. A successful create returns `201` with `slug`, `url`, `short_url`, and `created_at`. Invalid input returns a JSON `400` error; a taken custom slug returns `409`.

```sh
curl -i http://127.0.0.1:8000/example
curl http://127.0.0.1:8000/api/links/example
curl -i -X DELETE http://127.0.0.1:8000/api/links/example \
  -H "Authorization: Bearer $SNIP_API_TOKEN"
curl http://127.0.0.1:8000/healthz
```

`GET /{slug}` redirects with `302` and increments the visit count. `GET /api/links/{slug}` returns metadata with `visits`. Delete returns `204`; missing links return `404`. Create and delete require the bearer token and return `401` if it is missing or wrong.

## Tests

```sh
python3 -m unittest discover -s tests -v
```
