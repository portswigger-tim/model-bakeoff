# snip: notes

## Stack
- **Node.js 22.13+, ESM, zero runtime dependencies.** Built-in `http` does routing, `node:sqlite` does storage, `crypto` covers random slugs and token comparison. Nothing to install and no native build step.
- **SQLite via `node:sqlite`** in WAL mode. The primary key on `slug` enforces uniqueness, and `UPDATE ... RETURNING` counts a visit atomically.
- **`node:test`** for tests, so there is no test framework to install.

## Tests
```sh
npm test
```
Runs `test/*.test.js`: unit tests for validation, slugs, auth, config and the store, plus end-to-end tests against a real server on an ephemeral port, including a restart test. Last run: 72 pass, 0 fail.

## Known gaps
- No rate limiting; put a reverse proxy in front.
- No update, listing or expiry endpoints, since the brief did not ask for them.
- Single process only, which suits SQLite at this scale.
- URLs must be printable ASCII; percent-encode IRIs.
- Every `GET /{slug}` counts a visit, with no deduplication.
