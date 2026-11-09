# snip

A small URL-shortener HTTP service. It stores links in a local SQLite file,
counts visits, and redirects short slugs to their targets.

It has no runtime dependencies. It uses Node's built-in `http`, `crypto` and
`node:sqlite` modules, so there is nothing to `npm install`.

## Requirements

- Node.js 22.13 or newer (`node:sqlite` is available without a flag from 22.13)

## Configuration

All configuration comes from environment variables.

| Variable         | Default                    | Purpose                                                                                       |
| ---------------- | -------------------------- | --------------------------------------------------------------------------------------------- |
| `SNIP_API_TOKEN` | *(unset)*                  | Bearer token required by `POST` and `DELETE`. If unset, those endpoints reject every request. |
| `PORT`           | `3000`                     | HTTP port to listen on.                                                                       |
| `SNIP_DB_PATH`   | `data/snip.db`             | Path to the SQLite database file. The directory is created if needed.                         |
| `SNIP_BASE_URL`  | `http://localhost:$PORT`   | Public origin used to build `short_url` in responses. Trailing slashes are removed.           |

Generate a token and keep it out of version control:

```sh
export SNIP_API_TOKEN="$(openssl rand -hex 32)"
```

## Run

```sh
SNIP_API_TOKEN="$(openssl rand -hex 32)" npm start
```

Or without npm:

```sh
SNIP_API_TOKEN=change-me node --disable-warning=ExperimentalWarning src/index.js
```

The server logs its port and database path on startup and shuts down cleanly
on `SIGINT` or `SIGTERM`. Data lives in `SNIP_DB_PATH` and survives restarts.

## Use

Create a link with a generated slug:

```sh
curl -s -X POST http://localhost:3000/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/some/long/path"}'
# 201 {"slug":"aZ3kP9qL","url":"https://example.com/some/long/path",
#      "short_url":"http://localhost:3000/aZ3kP9qL","created_at":"2026-01-01T00:00:00.000Z"}
```

Create a link with a custom slug:

```sh
curl -s -X POST http://localhost:3000/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "slug": "docs"}'
```

Follow a link (this counts a visit):

```sh
curl -i http://localhost:3000/docs
# HTTP/1.1 302 Found
# Location: https://example.com
```

Read metadata, including the visit count (no token needed):

```sh
curl -s http://localhost:3000/api/links/docs
# {"slug":"docs","url":"https://example.com","short_url":"http://localhost:3000/docs",
#  "created_at":"...","visits":1}
```

Delete a link:

```sh
curl -i -X DELETE http://localhost:3000/api/links/docs \
  -H "Authorization: Bearer $SNIP_API_TOKEN"
# HTTP/1.1 204 No Content
```

Health check:

```sh
curl -i http://localhost:3000/healthz
# HTTP/1.1 200 OK
```

## API reference

| Method   | Path               | Auth   | Success                | Errors                                              |
| -------- | ------------------ | ------ | ---------------------- | --------------------------------------------------- |
| `POST`   | `/api/links`       | Bearer | `201` link JSON        | `400` invalid input, `401`, `409` slug taken, `413` body too large |
| `GET`    | `/{slug}`          | none   | `302` to target        | `404` unknown slug                                  |
| `GET`    | `/api/links/{slug}`| none   | `200` link + `visits`  | `404`                                               |
| `DELETE` | `/api/links/{slug}`| Bearer | `204`                  | `401`, `404`                                        |
| `GET`    | `/healthz`         | none   | `200` `{"status":"ok"}`| `503` if the database cannot be read                |

Errors are JSON of the form `{"error": "<message>"}`.

### Validation rules

- **Target URL:** absolute `http` or `https` URL, at most 2048 characters.
  Only printable ASCII is accepted with no whitespace. Percent-encode any
  other characters. The URL is stored exactly as submitted.
- **Custom slug:** 3 to 32 characters from `A-Z a-z 0-9 _ -`. The names `api`
  and `healthz` are reserved.
- **Generated slug:** 8 random base62 characters, drawn from `crypto.randomInt`.
  Collisions are retried.
- **Body:** a JSON object, at most 8 KiB. The `Content-Type` header is not
  enforced.

### Authentication

Write endpoints require `Authorization: Bearer <SNIP_API_TOKEN>`. The token is
compared using SHA-256 digests and `crypto.timingSafeEqual`. A missing or wrong
token returns `401` with `WWW-Authenticate: Bearer`.

## Test

```sh
npm test
```

This runs the Node built-in test runner over `test/*.test.js`. There are
unit tests for validation, slugs, auth, config and the store, plus end-to-end
tests that start a real server on an ephemeral port against a temporary
database. The end-to-end tests include a restart test that checks data survives
a process restart.

No extra tooling is needed. Tests create and remove their own temporary
databases and do not touch `data/`.

## Layout

```
src/
  index.js     entry point: reads config, starts the server, handles shutdown
  app.js       HTTP server, routing, body parsing, JSON responses
  links.js     business logic: create, read, delete, slug retry
  store.js     SQLite persistence (node:sqlite, WAL mode)
  validation.js URL and slug rules
  slug.js      random slug generation
  auth.js      bearer token check
  config.js    environment variable parsing
  errors.js    HttpError, which maps to a status code
test/          node:test suites
```

## Notes for production

- Put a TLS-terminating reverse proxy in front of the service and set
  `SNIP_BASE_URL` to the public `https://` origin.
- Back up the SQLite file with `sqlite3 data/snip.db ".backup backup.db"`
  while the service runs. Copying the `.db` file alone can miss data still in
  the `-wal` file.
- The service is single-process. SQLite handles one writer at a time, which is
  fine for this scale.
