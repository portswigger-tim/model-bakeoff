# NOTES

## Stack
- **Go, stdlib `net/http`**: Go 1.22+ method routing covers this API without a framework. It builds to a single binary, uses stdlib crypto (`crypto/rand`, `crypto/subtle`) and logs with `slog`.
- **SQLite via `modernc.org/sqlite`** (pure Go, no cgo): durable local storage with ACID guarantees. The primary key enforces slug uniqueness, so generated slugs are collision-safe without check-then-insert. Visits are counted with one atomic `UPDATE … RETURNING`.

## Tests
`make test` runs `go test ./...`. The suite covers every endpoint, validation edge cases, auth, collision retry, concurrent visits and persistence across a reopen.

## Safe defaults
- Binds to `127.0.0.1` and requires a token of at least 16 characters.
- Compares tokens in constant time.
- Builds `short_url` from configuration, never from the `Host` header.
- Limits body size and sets server timeouts.
- Rejects URLs containing credentials or control characters.
- Sends no-store redirects and never logs the token.

## Known gaps
- No rate limiting or URL reputation and blocklist checks.
- A single shared API token.
- Unmatched multi-segment routes return Go's plain-text 404/405, not JSON.
- No Dockerfile, metrics or migration tooling.
