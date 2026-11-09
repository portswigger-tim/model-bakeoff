# Notes

- **Stack:** Python 3.10+ standard library (`http.server`, `sqlite3`,
  `unittest`) keeps installation simple and storage local.
- **Tests:** run `python3 -m unittest discover -s tests -v`.
- **Known gaps:** this is a small single-process service; deploy it behind a
  production reverse proxy for TLS, request limits and operational monitoring.

