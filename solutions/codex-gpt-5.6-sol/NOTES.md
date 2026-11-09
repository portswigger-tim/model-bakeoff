# Implementation notes

I chose Python 3.11’s standard-library HTTP server with a small application
layer and SQLite storage. This keeps installation dependency-free while
providing durable local data, atomic visit counts, WAL-mode concurrency, and
transactional collision handling. Generated slugs use 64 bits of entropy from
`secrets`; write authentication uses constant-time bearer-token comparison.

Run the tests with:

```sh
python3 -m unittest discover -s tests -v
```

All 11 tests pass. They exercise the live threaded HTTP server, including
authentication, validation, custom and generated slugs, conflicts, redirects,
concurrent visit counting, deletion, and persistence.

Known gaps: TLS and rate limiting belong in a fronting reverse proxy. SQLite is
well suited to this single-host service, but this implementation is not meant
for multi-host horizontal scaling.
