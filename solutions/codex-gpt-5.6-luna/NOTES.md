Stack: Python 3.11+ standard-library HTTP server with SQLite. This keeps the service dependency-free while providing threaded request handling, durable local storage, parameterized queries, and atomic visit increments. Tests use `python3 -m unittest discover -s tests -v` and exercise the API over real local HTTP connections.

Known gaps: there is no rate limiting, admin UI, or rotation mechanism for `SNIP_API_TOKEN`; deployment should place the service behind TLS and a process supervisor.

