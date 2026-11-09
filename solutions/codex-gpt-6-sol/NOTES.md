# Notes

**Stack:** Python 3 standard library HTTP server and SQLite. This keeps installation and operation simple, persists links locally, and uses SQLite transactions to count concurrent visits safely. Generated slugs use cryptographic randomness with collision retries.

**Tests:** `python3 -m unittest discover -s tests -v` from this directory. The tests cover the HTTP API, authorization, validation, collisions, redirects, visit counts, concurrent requests, and restart persistence.

**Known gaps:** This is a single-node service. Public use needs an HTTPS reverse proxy and operational controls such as rate limiting and database backups. No built-in TLS or distributed storage is provided.
