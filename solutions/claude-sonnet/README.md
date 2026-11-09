# snip

A small URL-shortener HTTP service. Go, stdlib `net/http`, SQLite (pure-Go driver, no cgo).

## Install

Requires Go 1.22+.

```sh
make build        # produces ./bin/snip
```

## Configure

All configuration is via environment variables.

| Variable         | Required | Default            | Meaning                                              |
|------------------|----------|--------------------|------------------------------------------------------|
| `SNIP_API_TOKEN` | yes      | –                  | Bearer token for `POST`/`DELETE`. Service refuses to start without it. |
| `SNIP_ADDR`      | no       | `127.0.0.1:8080`   | Listen address (loopback by default).                |
| `SNIP_DB_PATH`   | no       | `data/snip.db`     | SQLite file; parent directory is created.            |
| `SNIP_BASE_URL`  | no       | from request Host  | Public base URL used to build `short_url`.           |

## Run

```sh
export SNIP_API_TOKEN="$(openssl rand -hex 32)"
./bin/snip            # or: make run
```

## API

```sh
# create (slug optional)
curl -X POST localhost:8080/api/links \
  -H "Authorization: Bearer $SNIP_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/some/long/path","slug":"demo"}'
# -> 201 {"slug":"demo","url":"...","short_url":"http://localhost:8080/demo","created_at":"..."}

curl -i localhost:8080/demo                 # 302 to the target, counts a visit
curl localhost:8080/api/links/demo          # metadata incl. "visits"
curl -X DELETE localhost:8080/api/links/demo -H "Authorization: Bearer $SNIP_API_TOKEN"   # 204
curl localhost:8080/healthz                 # 200
```

Rules: URLs must be absolute `http`/`https`, ≤ 2048 chars. Custom slugs are 3–32 chars of
`[A-Za-z0-9_-]` (`api` and `healthz` are reserved). Errors are JSON `{"error": "..."}`:
`400` invalid input, `401` bad/missing token, `404` unknown slug, `409` slug taken,
`413` oversized body. Generated slugs are 8 random base62 characters from `crypto/rand`
(~47 bits), retried on collision. Reads (`GET`) are unauthenticated.

## Test

```sh
make test         # go vet + go test -race ./...
```

## Notes

- Visit counting is a single atomic `UPDATE ... RETURNING`; `HEAD` does not count.
- SQLite runs in WAL mode with one connection, which serialises writes safely.
- Run behind a TLS-terminating reverse proxy in production; set `SNIP_BASE_URL` accordingly.
- No rate limiting is built in; apply it at the proxy.
