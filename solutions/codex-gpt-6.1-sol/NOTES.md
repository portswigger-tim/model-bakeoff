# Implementation notes

Python 3.11+, Flask, Waitress, and SQLite keep the service small and entirely
local. Waitress provides a production WSGI entry point; SQLite WAL, atomic
increments, unique constraints, and bounded retries handle concurrent traffic.
Dependencies are pinned in `requirements.txt`; tests use standard-library
`unittest` with no additional test dependencies.

Install and run using the README. Test from this directory after installing:

```sh
python -m unittest discover -v
```

The suite covers the API contract, invalid inputs, auth, persistence, collision
handling, concurrent visits/creation, and an actual HTTP server restart.

Known limits: one host/local disk; no per-user ownership, rate limiting, expiry,
or idempotency keys. `healthz` is reserved as a slug. Health checks measure
process liveness. Production TLS and traffic limiting belong at the reverse
proxy. SQLite 3.35+ is required for `UPDATE RETURNING`. Public metadata and
GET-based visit counts are intentional; HEAD does not increment visits.
