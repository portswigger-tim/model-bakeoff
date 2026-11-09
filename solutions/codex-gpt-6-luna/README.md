# Snip

Snip is a small HTTP URL shortener with an SQLite database stored on the local
filesystem. It uses only Python's standard library.

## Requirements

Python 3.10 or newer. No package installation is required.

## Configure and run

Set a private API token before starting the service. The default listener is
`127.0.0.1:8000`; the default database is `data/snip.sqlite3`.

```sh
export SNIP_API_TOKEN='replace-this-with-a-long-random-token'
python3 -m snip
```

Optional settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SNIP_HOST` | `127.0.0.1` | Interface to bind |
| `SNIP_PORT` | `8000` | Listening port |
| `SNIP_DB_PATH` | `data/snip.sqlite3` | SQLite database file |
| `SNIP_BASE_URL` | `http://localhost:<port>` | Public URL used in create responses |

When deploying behind a reverse proxy or on another host, set `SNIP_BASE_URL`
to the externally reachable HTTPS origin. Put the service behind TLS and keep
the token secret.

## API

Create a link (requires `Authorization: Bearer <SNIP_API_TOKEN>`):

```sh
curl -i -X POST http://localhost:8000/api/links \
  -H 'Authorization: Bearer replace-this-with-a-long-random-token' \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs","slug":"docs"}'
```

Omit `slug` to receive a random URL-safe slug. Custom slugs are 3–32 ASCII
letters, numbers, underscores or hyphens. A conflict returns `409`; invalid
URLs or request bodies return `400`.

* `GET /{slug}` redirects with `302` and increments the visit count.
* `GET /api/links/{slug}` returns link metadata and its visit count.
* `DELETE /api/links/{slug}` deletes a link and requires the bearer token.
* `GET /healthz` returns `{"status":"ok"}`.

## Tests

Run the test suite with:

```sh
python3 -m unittest discover -s tests -v
```

