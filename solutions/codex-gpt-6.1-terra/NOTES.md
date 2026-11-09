Python's standard library and SQLite keep installation and local persistence simple, with parameterized queries and transactional visit updates. Generated slugs use the secrets module and a database uniqueness constraint.

Run tests with `python3 -m unittest -v`.

Known gaps: the built-in HTTP server is intended for modest traffic; deploy behind a TLS-terminating reverse proxy for network use. There is no rate limiting or administrative interface. The health check reports process availability, not database health.
