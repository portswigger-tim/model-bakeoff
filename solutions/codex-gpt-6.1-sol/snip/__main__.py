"""Run the production WSGI server with explicit, environment-based settings."""

import logging
import os
import sqlite3
import sys

from waitress import serve

from . import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        port = int(os.environ.get("SNIP_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("SNIP_PORT must be between 1 and 65535")
        app = create_app()
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    serve(
        app,
        host=os.environ.get("SNIP_HOST", "127.0.0.1"),
        port=port,
        threads=8,
        max_request_body_size=32768,
        expose_tracebacks=False,
        clear_untrusted_proxy_headers=True,
    )


if __name__ == "__main__":
    main()
