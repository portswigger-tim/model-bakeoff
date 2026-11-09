# Model bake-off: quality and cost

**Date:** 2026-11-09 · **Brief:** [`BRIEF.md`](BRIEF.md), a small, production-minded URL-shortener HTTP API ("snip") · **Entrants:** every launchable Agent Wrangler session model (4 Claude, 7 Codex)

## TL;DR

| Rank | Model | Score /100 | Build cost | Wall time | Points per $ |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | **Codex gpt-6.1-sol** | **93.5** | $0.33 | 6m16s | 281 |
| 2 | Claude Opus 5.5 | 92.5 | $1.46 | 7m10s | 63 |
| 3 | **Claude Haiku 5.5** | **92.0** | **$0.07** | 5m59s | **1,316** |
| 4 | Claude Fable 5.1 | 88.0 | $0.33 | **1m37s** | 269 |
| 5 | Claude Sonnet 5.5 | 87.5 | $0.35 | 2m00s | 251 |
| 6 | Codex gpt-6-sol | 84.0 | $0.34 | 5m17s | 250 |
| 7 | Codex gpt-6.1-terra | 82.0 | $0.06 | 1m56s | 1,353 |
| 8 | Codex gpt-5.6-sol | 80.0 | $0.73 | 6m00s | 110 |
| 9 | Codex gpt-5.6-luna | 75.5 | $0.03 | 4m28s | 2,374 |
| 10 | Codex gpt-6-luna | 74.5 | **$0.015** | 3m52s | 4,934 |
| 11 | Codex gpt-5.6-terra | 69.5 | $0.34 | 5m19s | 206 |

- **Best overall: gpt-6.1-sol.** It was the only entry to score 5/5 on tests: 33 tests, including a real server subprocess, restart, concurrency and collision exhaustion. It also had strict, layered URL validation.
- **Best value: Claude Haiku 5.5.** It scored within 1.5 points of the top for about a fifth of gpt-6.1-sol's cost and a twentieth of Opus's. It used zero dependencies, had a clean five-layer split and 72 real-HTTP tests.
- **Opus 5.5 produced the most production-ready service.** It was the only one with fully tuned server timeouts, an SHA-256 digest compare, rejection of userinfo in URLs, and a health check that tests the DB. It was also the most expensive, by about 4×.
- **Fastest: Fable 5.1 and Sonnet 5.5,** both under 2 minutes for 88 points.
- **Cheapest that is still acceptable: gpt-6.1-terra.** It scored 82 for $0.06 in under 2 minutes, as a single file.
- **Weakest: gpt-5.6-terra.** It was the only entry with a black-box correctness failure (CRLF accepted, then a 500 on redirect) and the only non-constant-time token compare. Its JSON-file store rewrites the whole database on every visit.
- **No entry had a High-severity security finding.** All 11 enforce authentication, use parameterised storage access and generate slugs from a CSPRNG.

## Method

1. **Same brief, isolated builds.** Each model ran as its own child session at `effort: high`, in `solutions/<agent>-<model>/`, with an identical launch prompt. Each was told to make every decision itself, not to look at sibling directories, and to finish with passing tests and a `NOTES.md`.
2. **Cost.** Cost was recomputed from each session's on-disk transcript with Agent Wrangler's `scripts/cost-report.mjs`, the same pricing the board uses. Claude figures are from billed token usage. **Codex figures are estimates** priced from reported token counts. Wall time is first to last transcript activity.
3. **Objective checks, run identically on all 11** ([`assessment/run_all.sh`](assessment/run_all.sh)):
   - Install the entry, then run its own test suite.
   - Start its server and drive it with [`assessment/probe.py`](assessment/probe.py). That is a 51-check black-box HTTP conformance probe covering auth, every status code, URL and slug edge cases (CRLF, `javascript:`, `data:`, 2048/2049 lengths, 3/32-character slugs), a 2 MB body, 30 concurrent visits, and `/healthz` shadowing.
   - Restart the server on the same data and check persistence.
4. **Blind expert review.** Each solution was copied to an anonymised folder (`S01`–`S11`, shuffled) with nothing identifying the model. A fresh **Claude Opus 5.5** reviewer scored each one with the identical prompt and the [`assessment/RUBRIC.md`](assessment/RUBRIC.md) matrix. The reviewer read every source file, saw the test and probe output, and could run experiments to confirm bugs. Raw scores are in [`assessment/scores.json`](assessment/scores.json).

### Scoring matrix

| Dimension | Weight |
| --- | ---: |
| Correctness & brief conformance | 20 |
| Architecture & design | 15 |
| Code quality | 15 |
| **Security** | **25** |
| Tests | 15 |
| Docs & operability | 10 |

Each dimension is scored 1–5, and the total is `Σ score/5 × weight`. The anchors for 1, 3 and 5 on each dimension are in `RUBRIC.md`.

### Detailed scores

| Model | Correct. | Arch. | Code | Security | Tests | Docs | **Total** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Codex gpt-6.1-sol | 5 | 4.5 | 4.5 | 4.5 | **5** | 4.5 | **93.5** |
| Claude Opus 5.5 | 4.5 | **5** | 4.5 | 4.5 | 4.5 | **5** | 92.5 |
| Claude Haiku 5.5 | 5 | **5** | 4.5 | 4.5 | 4 | 4.5 | 92.0 |
| Claude Fable 5.1 | 5 | 4.5 | 4.5 | 4 | 4 | 4.5 | 88.0 |
| Claude Sonnet 5.5 | 4.5 | 4.5 | 4.5 | 4.5 | 4 | 4 | 87.5 |
| Codex gpt-6-sol | 5 | 4 | 4 | 4 | 4 | 4 | 84.0 |
| Codex gpt-6.1-terra | 4.5 | 4 | 4 | 4 | 4 | 4 | 82.0 |
| Codex gpt-5.6-sol | 4 | 4 | 4.5 | 4 | 3.5 | 4 | 80.0 |
| Codex gpt-5.6-luna | 4.5 | 4 | 4 | 3.5 | 3 | 3.5 | 75.5 |
| Codex gpt-6-luna | 4 | 3.5 | 4 | 4 | 3 | 3.5 | 74.5 |
| Codex gpt-5.6-terra | 4 | 3.5 | 4 | 3 | 3 | 3.5 | 69.5 |

### Objective results

| Model | Own tests | Probe (51 checks) | Probe failures |
| --- | --- | ---: | --- |
| Claude Fable 5.1 | 61 pass | 51 | none |
| Claude Haiku 5.5 | 72 pass | 51 | none |
| Claude Opus 5.5 | pass (3 pkgs, `-race`) | 51 | none |
| Claude Sonnet 5.5 | pass (`-race`) | 51 | none |
| Codex gpt-6.1-sol | 33 pass | 51 | none |
| Codex gpt-6.1-terra | 5 pass | 51 | none |
| Codex gpt-6-sol | 7 pass | 51 | none |
| Codex gpt-6-luna | 7 pass | 50 | `GET /api/links/{slug}` omits `short_url` |
| Codex gpt-5.6-sol | 11 pass | 50 | `GET /api/links/{slug}` omits `short_url` |
| Codex gpt-5.6-luna | 4 pass | 51 | none |
| Codex gpt-5.6-terra | 11 pass | 50 | accepts a URL containing CRLF (201), and the redirect then returns 500 |

Every entry's own suite passed, and every README's run and test commands worked as written.

## Cost detail

| Model | USD | Output tokens | Cache-read tokens | Basis |
| --- | ---: | ---: | ---: | --- |
| Claude Opus 5.5 | 1.459 | 32.6k | 1.65M | billed |
| Codex gpt-5.6-sol | 0.730 | 17.4k | 0.59M | estimated |
| Claude Sonnet 5.5 | 0.349 | 15.4k | 0.42M | billed |
| Codex gpt-5.6-terra | 0.337 | 11.4k | 0.52M | estimated |
| Codex gpt-6-sol | 0.335 | 14.3k | 0.66M | estimated |
| Codex gpt-6.1-sol | 0.332 | 17.0k | 0.35M | estimated |
| Claude Fable 5.1 | 0.327 | 12.2k | 0.60M | billed |
| Claude Haiku 5.5 | 0.070 | 54.6k | 2.50M | billed |
| Codex gpt-6.1-terra | 0.061 | 5.0k | 0.17M | estimated |
| Codex gpt-5.6-luna | 0.032 | 13.4k | 0.38M | estimated |
| Codex gpt-6-luna | 0.015 | 11.3k | 0.47M | estimated |

All 11 builds together cost about **$4.06**. Haiku did the most work of any entrant: 3.4× Opus's output tokens and 1.5× its cache reads. It still cost 5% of Opus's price.

## Architecture and tooling chosen

| Model | Language | HTTP layer | Storage | Tests | Runtime deps | Tooling |
| --- | --- | --- | --- | --- | --- | --- |
| Claude Fable 5.1 | Python 3.11 | FastAPI + uvicorn | SQLite (WAL), lock-serialised | pytest + TestClient | 2 (locked via `uv.lock`) | uv, hatchling |
| Claude Opus 5.5 | Go | stdlib `net/http` | SQLite (`modernc.org/sqlite`, pure Go) | `go test` + httptest | 1 (`go.sum`) | Makefile, go vet, gofmt |
| Claude Sonnet 5.5 | Go | stdlib `net/http` | SQLite (`modernc.org/sqlite`) | `go test -race` | 1 (`go.sum`) | Makefile, go vet |
| Claude Haiku 5.5 | Node 22 (ESM) | `node:http` | SQLite (`node:sqlite`, WAL) | `node:test`, real HTTP | **0** | npm scripts |
| Codex gpt-6.1-sol | Python 3.11 | Flask + Waitress | SQLite (WAL) | unittest + subprocess server | 8 (pinned `requirements.txt`) | pip/venv |
| Codex gpt-6.1-terra | Python 3.9 | `http.server` | SQLite | unittest, real HTTP | 0 | none (single file) |
| Codex gpt-6-sol | Python 3 | `http.server` | SQLite (WAL) | unittest, real HTTP | 0 | none |
| Codex gpt-6-luna | Python 3.10 | `http.server` | SQLite (WAL) | unittest, real HTTP | 0 | none |
| Codex gpt-5.6-sol | Python 3.11 | `http.server` | SQLite (WAL) | unittest, real HTTP | 0 | none |
| Codex gpt-5.6-luna | Python 3.11 | `http.server` | SQLite (WAL), RLock | unittest, real HTTP | 0 | pyproject (setuptools) |
| Codex gpt-5.6-terra | Node 20 | `node:http` | **JSON file**, atomic rename | `node:test`, real HTTP | 0 | npm scripts |

Patterns:

- **Claude models chose a real framework or language runtime and a layered package layout.** Opus and Sonnet both independently chose Go, stdlib `net/http` and pure-Go SQLite. Fable chose FastAPI. Haiku chose zero-dependency Node with built-in SQLite.
- **Codex models chose Python's stdlib `http.server` six times out of seven,** usually as one or two modules. gpt-6.1-sol was the exception: it used Flask with a production WSGI server, Waitress.
- **10 of 11 chose SQLite.** Only gpt-5.6-terra chose a JSON file, and that choice cost it on architecture and scalability.
- **No entrant added lint, format or CI config.** The brief didn't ask for it, but "code you'd be happy to ship" arguably implies it.

## Security comparison

| Control | Fable | Opus | Sonnet | Haiku | 6.1-sol | 6.1-terra | 6-sol | 6-luna | 5.6-sol | 5.6-luna | 5.6-terra |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| Fails closed with no token | ✅ | ✅ startup refuses, ≥16 chars | ✅ startup refuses | ✅ | ✅ startup refuses | ✅ startup refuses | ✅ startup refuses | ✅ startup refuses | ✅ startup refuses | ✅ (silent) | ✅ |
| Constant-time compare | ✅ | ✅ SHA-256 digests | ✅ | ✅ SHA-256 digests | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ `===` |
| Rejects CRLF/control chars in URL | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (not DEL) | ✅ | ❌ |
| Rejects userinfo (`a@evil.com`) | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ✅ | ❌ |
| Body size limit | ✅ (after read) | ✅ 16 KiB | ✅ 16 KiB | ✅ 8 KiB | ✅ 32 KiB | ✅ 16 KiB | ✅ 16 KiB | ✅ 8 KiB | ✅ 16 KiB | ✅ 64 KiB | ✅ 16 KiB |
| Server/socket timeouts | ❌ **M** | ✅ all four | ✅ | ✅ | defaults | ❌ **M** | ❌ **M** | ❌ **M** | ❌ **M** | ❌ **M** | defaults |
| Loopback bind by default | ✅ | ✅ | ✅ | ❌ 0.0.0.0 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ 0.0.0.0 |
| Reserved slugs (`healthz`, `api`) | ✅ | ✅ | ✅ | ✅ | healthz only | healthz only | healthz only | ❌ | ❌ | ❌ | ❌ |
| `short_url` from config, not Host | Host fallback | ✅ always config | Host fallback | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Host fallback | Host fallback |
| Slug entropy | ~47 bits | ~58 bits | ~47 bits | ~47 bits | 72 bits | 72 bits | 72 bits | 72 bits | 64 bits | 64 bits | 72 bits |

**M** marks a Medium finding. A stdlib `http.server` with no socket timeout lets an unauthenticated client hold a thread forever (slowloris). All five stdlib-Python entries had this flaw. It is the most common Medium finding in the bake-off, and it comes straight from the framework choice. Fable's uvicorn deployment had no explicit timeouts either.

## Where each model excelled and fell down

### Codex gpt-6.1-sol — 93.5, $0.33 — overall winner
- **Excelled:** It had the best test suite of the field: 33 tests, including a real Waitress subprocess with restart, concurrent visits *and* concurrent creates, collision exhaustion, a check that errors don't leak, and DB file permissions. It created the DB file `0600` in a `0700` directory. URL validation was the most thorough (control characters, backslash, IDNA, port 0). Every dependency was pinned. It fails fast at startup on bad config.
- **Fell down:** It accepts userinfo URLs, and it has a test asserting `user:pass@` is valid. Waitress timeouts are left at defaults. Waitress returns its own 413 for oversized bodies, which is probably not JSON. There is no access logging and no lint tooling.

### Claude Opus 5.5 — 92.5, $1.46 — most production-ready, most expensive
- **Excelled:** It had the strongest security posture: a token of at least 16 characters required at startup, a constant-time compare of SHA-256 digests, userinfo rejected, all four server timeouts plus `MaxHeaderBytes`, `short_url` never taken from the Host header, and request logs that deliberately omit headers. The architecture was the cleanest (`config`/`server`/`store`, with test hooks injected). It used structured `slog` logging, and the health check returns 503 when the DB is down. Its `NOTES.md` was the most honest list of known gaps.
- **Fell down:** It cost 4–20× the other top finishers. A missing Content-Type returns 415 where the brief says 400. Unmatched routes return Go's plain-text 404/405. Its tests use `httptest.ResponseRecorder` rather than a real listener and never restart the process.

### Claude Haiku 5.5 — 92.0, $0.07 — best value
- **Excelled:** Zero runtime dependencies, using Node's built-in `node:sqlite`. It had a clean split into HTTP, service, validation, store and config. It rejects anything non-printable or non-ASCII in URLs before parsing. The body limit is enforced on both Content-Length and streamed bytes, with header and request timeouts set. It wrote 72 real-HTTP tests, including restart. It also smoke-tested its README against a live server unprompted, as did gpt-6-sol.
- **Fell down:** It binds `0.0.0.0` by default with no host option. It accepts userinfo URLs. It has no concurrent-visit or collision-retry test and no access logging. It relies on the experimental `node:sqlite` API, with the warning suppressed.

### Claude Fable 5.1 — 88.0, $0.33 — fastest
- **Excelled:** It finished in 1m37s, the fastest of the field, with a perfect black-box score. It produced a tidy FastAPI package with a reproducible `uv.lock`, a strict reserved-slug list that includes `docs`/`redoc`/`openapi`, auto-docs disabled, and `no-store` on redirects. It had 61 tests, including one checking that an unset or empty token fails closed.
- **Fell down:** uvicorn runs with no timeouts (Medium). The body is fully buffered before the 8 KiB check. A blocking SQLite lock inside an `async def` handler can stall the event loop. All tests run in-process, with no concurrency test.

### Claude Sonnet 5.5 — 87.5, $0.35
- **Excelled:** It reached nearly the same design as Opus (Go, stdlib, pure-Go SQLite) in 2 minutes for a quarter of the cost. Auth fails closed at two layers. It sets full server timeouts, a 16 KiB `MaxBytesReader` and case-insensitive reserved slugs. Its tests run under the race detector.
- **Fell down:** Graceful shutdown is broken: `main` returns before `Shutdown` drains connections. It accepts trailing garbage after the JSON body and userinfo URLs. The README says Go 1.22+ while `go.mod` requires 1.26.

### Codex gpt-6-sol — 84.0, $0.34
- **Excelled:** A perfect black-box score. URL validation was strong (it is one of three entries that reject userinfo). It requires `Content-Type: application/json`, rejects unknown keys, and re-encodes Unicode in `Location` safely.
- **Fell down:** No socket timeouts (Medium). Routing is hand-rolled with string prefixes and is inconsistent: `POST /api/links?x` returns 404. Only `healthz` is reserved. It has no SIGTERM handling and only 7 tests.

### Codex gpt-6.1-terra — 82.0, $0.06 — cheapest acceptable result
- **Excelled:** A complete, correct service in **one 158-line file** and under 2 minutes for 6 cents. Body handling was defensive: it rejects `Transfer-Encoding`, requires Content-Length, and catches `RecursionError`. It uses 72-bit slugs and a test mocks a slug collision.
- **Fell down:** No socket timeouts and unbounded threads (Medium). Uncaught store errors drop the connection without a JSON 500. Readability suffers from conditional expressions used only for their side effects. It has only 5 tests.

### Codex gpt-5.6-sol — 80.0, $0.73 — expensive for the result
- **Excelled:** The code was well typed and idiomatic, with careful JSON parsing that rejects duplicate keys and NaN, and it sends `no-referrer` and `no-store` on redirects.
- **Fell down:** Its metadata endpoint omits `short_url`, a brief miss. An accepted URL with an IDNA-invalid host crashes the redirect *after* counting the visit. It has no timeouts (Medium), allows the DEL character, and reserves no slugs. It was the second most expensive entry while scoring eighth.

### Codex gpt-5.6-luna — 75.5, $0.03
- **Excelled:** It passed all 51 probe checks for 3 cents. URL validation was strict, including userinfo and port. Visit counting is serialised with an RLock and an atomic UPDATE.
- **Fell down:** It accepts a bare token without the `Bearer ` prefix. A non-ASCII `Authorization` header crashes the handler. It has no timeouts (Medium), suppresses all logging, and does not warn when the token is unset. It has only 4 tests, with none for concurrency or generated slugs.

### Codex gpt-6-luna — 74.5, $0.015 — cheapest
- **Excelled:** A working, fail-closed service for a cent and a half. Its Bearer check is case-insensitive and constant-time, and it rejects userinfo.
- **Fell down:** Its metadata endpoint omits `short_url`. URLs with spaces or non-Latin-1 characters are accepted, and the redirect then crashes. It has no timeouts (Medium). SQL sits inline in the handlers. Its tests do not really restart the server.

### Codex gpt-5.6-terra — 69.5, $0.34 — last place
- **Excelled:** Zero dependencies. A null-prototype map means a `__proto__` slug is safe, and a test covers it. It writes the store atomically via temp file and rename with mode `0600`.
- **Fell down:** It is the **only entry with a black-box failure**: it validates the URL by parsing it but stores the raw string, so a CRLF-containing URL is stored and its redirect returns a 500 after the visit is counted. It is also the **only non-constant-time token compare** (`===`). It binds `0.0.0.0`, has no reserved slugs, and synchronously rewrites the whole JSON file on every redirect (O(n)). There is no fsync, although the README claims durability.

## Takeaways

1. **For a small, well-specified service, price barely predicts quality.** The spread from $0.015 to $1.46 (about 100×) maps to scores from 74.5 to 92.5. Haiku 5.5 and gpt-6.1-terra are the standout value picks.
2. **Newest-generation workhorses beat their predecessors.** gpt-6.1-sol scored 93.5 against gpt-6-sol's 84 and gpt-5.6-sol's 80, at the same or lower cost.
3. **Framework choice drove the most common security gap.** All five stdlib-`http.server` entries had no socket timeouts, while the Go and Node entries set them. A brief that says "production-minded" should probably also say "behind no proxy" if that matters.
4. **Claude models wrote more tests and more layered code.** Codex models wrote smaller, flatter code, and gpt-6.1-sol was the exception with the field's best tests.
5. **Universal misses:** 7 of 11 accept `https://trusted.com@evil.com`, and nobody added lint or CI.

## Caveats

- **n = 1 per model.** One run each. Expect run-to-run variance of several points, so treat gaps under about 5 points as ties.
- **The judge is also an entrant's model.** Opus 5.5 reviewed every solution. Blinding (anonymised, shuffled IDs with model names removed from all files) and a fixed rubric reduce but do not eliminate self-preference bias. Opus's own entry ranked second, not first. The probe results are objective and judge-independent.
- **Codex costs are estimates** from reported token counts, and Claude costs are billed figures. Cost varies with cache hit rate as well as model price.
- **Model availability:** `gpt-6-astra` and `gpt-5.5` appear in the docs but were rejected as not launchable on this board, so they are absent. `opusplan` (Opus planning, Sonnet executing) and `sonnet[1m]` (the same model with a larger context window) were left out because they are not separate models.
- **Assessment cost:** the orchestration and 11 Opus reviews cost about **$8.20**, on top of the $4.06 build cost.

## Reproduce

```sh
./assessment/run_all.sh                 # all entries
./assessment/run_all.sh claude-haiku    # one entry
```

Results are written to `assessment/results/`. They need `uv`, Go 1.26, Node 22.13+ and Python 3.11+.
