# Scoring rubric

Every solution is scored by the same reviewer model (Claude Opus 5.5, high
effort) with this rubric, the same prompt, and the same evidence: the source,
the solution's own test output, and the shared black-box probe results
(`assessment/probe.py`, run identically against every server by
`assessment/run_all.sh`).

Each dimension is scored 1–5. Half points are allowed. The weighted total is
out of 100: `sum(score/5 * weight)`.

| Dimension | Weight | 5 = | 3 = | 1 = |
| --- | --- | --- | --- | --- |
| **Correctness & brief conformance** | 20 | Every requirement met, including edge cases (limits, status codes, JSON errors, persistence, atomic visit counts) | Core flows work; some edge cases or response fields wrong | Core flows broken |
| **Architecture & design** | 15 | Clear separation (HTTP / validation / storage / config), appropriate stack for the size, concurrency handled correctly | Works but tangled or over/under-engineered | Ad hoc, single blob, unsafe concurrency |
| **Code quality** | 15 | Idiomatic, readable, small functions, consistent error handling, no dead code | Readable but with duplication, inconsistency or awkward spots | Hard to follow, fragile |
| **Security** | 25 | Fail-closed auth with constant-time compare, strict URL/slug validation (schemes, control chars), body limits and timeouts, unguessable slugs, parameterised queries, safe defaults (loopback bind, no token logging), reserved paths protected, pinned deps | Main controls present; one or two medium gaps | Auth bypass, injection, or other high-severity flaw |
| **Tests** | 15 | Covers every endpoint and edge case, real HTTP and persistence/restart, concurrency, fast and deterministic | Happy paths plus some errors | Few or no meaningful tests |
| **Docs & operability** | 10 | README commands work as written; config documented; sensible defaults, graceful shutdown, logging | README adequate with gaps | Missing or wrong |

Severity guide for security findings: **High** = exploitable without the
token or leaks the token; **Medium** = weak control that matters in a
realistic deployment (no body limit, no timeouts, accepts control
characters into stored URLs, token compared non-constant-time); **Low** =
hardening or defence in depth.
