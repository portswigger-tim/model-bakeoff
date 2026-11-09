# snip

A small HTTP URL shortener with SQLite persistence. Python 3.9 or later is required; no packages or external services are needed.

## Run

```sh
export SNIP_API_TOKEN='replace-with-a-long-random-secret'
python3 snip.py
```

The default listener is `127.0.0.1:8000`, the database is `snip.db` in the current directory, and returned links use `http://localhost:8000`. Set `SNIP_HOST`, `SNIP_PORT`, `SNIP_DB`, and `SNIP_BASE_URL` to change these. `SNIP_BASE_URL` must be the public HTTP(S) origin, without a path; configure it explicitly when the service is accessed remotely or behind a reverse proxy. The token is required at startup. Use TLS at a trusted reverse proxy when exposing the service beyond localhost.

```sh
curl -X POST http://localhost:8000/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/","slug":"example"}'
curl -i http://localhost:8000/example
curl http://localhost:8000/api/links/example
curl -i -X DELETE http://localhost:8000/api/links/example -H "Authorization: Bearer $SNIP_API_TOKEN"
curl http://localhost:8000/healthz
```

Custom slugs are case-sensitive, contain 3–32 ASCII letters, digits, underscores or hyphens, and `healthz` is reserved for the health endpoint. Omitting `slug` generates a random one. Deletion returns 204, and a missing link returns 404. Redirects increment the visit counter atomically. Keep the SQLite file and its directory writable and back it up to preserve data.

## Test

```sh
python3 -m unittest -v
```
