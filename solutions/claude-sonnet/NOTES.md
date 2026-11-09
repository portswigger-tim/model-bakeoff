# Notes

**Stack:** Go 1.22 stdlib `net/http` (method-aware ServeMux) + SQLite via `modernc.org/sqlite` (pure Go, no cgo, single binary, local file persistence in WAL mode). Chosen for minimal dependencies and easy deployment.

**Layout:** `cmd/snip` (wiring, env config, graceful shutdown), `internal/server` (handlers, validation, auth), `internal/store` (SQLite).

**Safety defaults:** refuses to start without `SNIP_API_TOKEN`; constant-time token compare; binds to loopback; body size limit; server timeouts; reserved slugs (`api`, `healthz`); atomic visit counter; crypto/rand slugs with collision retry.

**Tests:** `make test` (or `go vet ./... && go test -race ./...`). Covers create/validation/conflict/auth/redirect/visit counting/delete/healthz, persistence across reopen, and concurrent visits.

**Known gaps:** no rate limiting, link expiry, listing endpoint, or metrics; HEAD is not counted as a visit; `url` with embedded credentials is accepted; empty-string `slug` is treated as absent.
