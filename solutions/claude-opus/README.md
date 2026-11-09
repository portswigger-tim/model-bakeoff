# snip

A small URL-shortener HTTP service written in Go. Links are stored in a local
SQLite database, so data survives restarts and there are no external services
to run.

## Requirements

- Go 1.26 or newer (`go version`)

There are no other dependencies. SQLite is provided by
[`modernc.org/sqlite`](https://pkg.go.dev/modernc.org/sqlite), a pure-Go
driver, so no C toolchain or system SQLite is needed.

## Install

```sh
go mod download
make build          # or: go build -o bin/snip ./cmd/snip
```

## Configure

All configuration comes from environment variables.

| Variable         | Required | Default                    | Description |
|------------------|----------|----------------------------|-------------|
| `SNIP_API_TOKEN` | yes      | none                       | Bearer token for `POST` and `DELETE`. At least 16 characters, no whitespace. The service will not start without it. |
| `SNIP_ADDR`      | no       | `127.0.0.1:8080`           | Listen address. Use `:8080` to listen on all interfaces. |
| `SNIP_DB_PATH`   | no       | `data/snip.db`             | SQLite database file. The directory is created if it is missing. |
| `SNIP_BASE_URL`  | no       | `http://localhost:<port>`  | Public base URL used to build `short_url`, e.g. `https://sn.ip`. |

`short_url` is always built from `SNIP_BASE_URL` and never from the request's
`Host` header, so clients cannot spoof it. In production, set it to the
public origin.

Generate a token with, for example:

```sh
export SNIP_API_TOKEN="$(openssl rand -hex 32)"
```

## Run

```sh
export SNIP_API_TOKEN="$(openssl rand -hex 32)"
make run            # or: go run ./cmd/snip   or: ./bin/snip
```

Logs are structured JSON on stderr. `SIGINT` or `SIGTERM` shuts the server
down gracefully.

## API

Write endpoints need `Authorization: Bearer $SNIP_API_TOKEN`. All error
responses are JSON shaped like `{"error": "..."}`.

| Method & path             | Auth | Success | Errors |
|---------------------------|------|---------|--------|
| `POST /api/links`         | yes  | `201` with link JSON and a `Location` header | `400` invalid input, `401`, `409` slug taken, `415` non-JSON content type |
| `GET /{slug}`             | no   | `302` to the target, counts a visit | `404` |
| `GET /api/links/{slug}`   | no   | `200` with link JSON including `visits` | `404` |
| `DELETE /api/links/{slug}`| yes  | `204` | `401`, `404` |
| `GET /healthz`            | no   | `200 {"status":"ok"}` | `503` if storage is unavailable |

### Examples

```sh
BASE=http://localhost:8080
AUTH="Authorization: Bearer $SNIP_API_TOKEN"

# Create with a generated slug
curl -s -X POST "$BASE/api/links" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/some/long/path"}'
# {"slug":"aB3xK9mPqR","url":"https://example.com/some/long/path","short_url":"http://localhost:8080/aB3xK9mPqR","created_at":"2026-11-09T12:00:00Z"}

# Create with a custom slug
curl -s -X POST "$BASE/api/links" -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","slug":"docs"}'

curl -si "$BASE/docs"                 # 302, Location: https://example.com
curl -s  "$BASE/api/links/docs"       # {..., "visits":1}
curl -s -X DELETE "$BASE/api/links/docs" -H "$AUTH" -o /dev/null -w '%{http_code}\n'   # 204
```

### Validation rules

- `url` is required. It must be an absolute `http` or `https` URL with a
  host, at most 2048 characters, with no whitespace, no control characters
  and no embedded credentials (`user:pass@`).
- `slug` is optional. It must be 3–32 characters from `[A-Za-z0-9_-]`. Slugs
  are case-sensitive. `api` and `healthz` are reserved in any case. If you
  leave the slug out, or send `""` or `null`, one is generated for you.
- The request body must be a single JSON object no larger than 16 KiB. Unknown
  fields are rejected.

### Behaviour notes

- **Generated slugs** are 10 characters drawn uniformly, using `crypto/rand`,
  from a 57-character alphabet without look-alike characters (about 58 bits
  of entropy). Uniqueness is enforced by the database primary key. If a
  generated slug collides, the service retries with a new one.
- **Visits** are counted with a single atomic `UPDATE ... RETURNING`, so
  concurrent hits are never lost. `HEAD` requests resolve the link without
  counting a visit. Redirects send `Cache-Control: private, no-store` so
  browsers don't skip the counter on repeat visits.
- `GET /api/links/{slug}` is unauthenticated, as the brief only requires auth
  on writes.

## Test

```sh
make test           # or: go test ./...
go test -race ./... # with the race detector (needs cgo)
```

The tests cover every endpoint, the validation edge cases, authentication,
generated-slug collision handling, concurrent visit counting and persistence
across a store reopen. They use temporary SQLite files and need no setup.

## Layout

```
cmd/snip/          entrypoint: config, HTTP server, graceful shutdown
internal/config/   environment parsing and validation
internal/server/   HTTP handlers, validation, auth and middleware
internal/store/    SQLite persistence
```
