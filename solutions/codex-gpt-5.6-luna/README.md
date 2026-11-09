# snip

`snip` is a small URL-shortener HTTP service backed by local SQLite storage. It uses only Python’s standard library at runtime, so it has no external service or dependency requirement.

## Requirements and setup

- Python 3.11 or newer

An optional virtual environment keeps local tooling isolated:

```sh
python3 -m venv .venv
. .venv/bin/activate
```

## Run

Write operations require a bearer token from `SNIP_API_TOKEN`. The database defaults to `snip.db`, which is ignored by Git.

```sh
SNIP_API_TOKEN=change-me python -m snip --host 127.0.0.1 --port 8000
```

Useful options are `--db PATH` for a different SQLite file and `--base-url URL` to make the `short_url` response use a public base URL. `GET /healthz` is unauthenticated.

Create and use a link:

```sh
curl -i -X POST http://127.0.0.1:8000/api/links \
  -H 'Authorization: Bearer change-me' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.example.com/docs","slug":"docs"}'
curl -i http://127.0.0.1:8000/docs
curl -s http://127.0.0.1:8000/api/links/docs
curl -i -X DELETE http://127.0.0.1:8000/api/links/docs \
  -H 'Authorization: Bearer change-me'
```

URLs must be absolute `http` or `https` URLs no longer than 2048 characters. Custom slugs are 3–32 characters from letters, digits, `_`, and `-`; omitted slugs are generated randomly.

## Test

Run the complete test suite with one command from this directory:

```sh
python3 -m unittest discover -s tests -v
```

The tests use temporary databases and an in-process HTTP server, so they need no network or external services.

