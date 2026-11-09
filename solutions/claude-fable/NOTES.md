# Notes

**Stack:** Python 3.11+, FastAPI + uvicorn, stdlib `sqlite3` (WAL) for storage, pytest + FastAPI TestClient. Chosen for a tiny dependency set, no external services, and durable local persistence with atomic visit counting (`UPDATE ... RETURNING`). Managed with uv/pyproject.

**Layout:** `snip/` (`app.py` routes/auth, `validation.py`, `storage.py`, `config.py`, `__main__.py`), `tests/` (API + unit, 61 tests).

**Safe defaults:** fail-closed auth (unset token → 401), constant-time token compare, localhost bind, 8 KB body cap, reserved slugs, no-store on redirects, auto-docs disabled, consistent JSON errors.

**Run tests:** `uv sync && uv run pytest` — 61 passed.

**Known gaps:**
- No rate limiting or link expiry; put a proxy in front for that.
- Single SQLite connection behind a lock: fine for small deployments, not horizontally scalable.
- Tests emit a Starlette deprecation warning about `httpx` (harmless).
- No Dockerfile/CI config.
