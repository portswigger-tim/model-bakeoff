"""Run with python -m snip."""

import os
import sys

from .app import SnipServer
from .store import Store


def main():
    try:
        host = os.environ.get("SNIP_HOST", "127.0.0.1")
        port = int(os.environ.get("SNIP_PORT", "8000"))
        token = os.environ.get("SNIP_API_TOKEN", "")
        if not token:
            raise ValueError("SNIP_API_TOKEN must be set")
        base_url = os.environ.get("SNIP_BASE_URL", f"http://127.0.0.1:{port}")
        server = SnipServer(
            (host, port), Store(os.environ.get("SNIP_DB_PATH", "snip.db")), token, base_url
        )
    except (ValueError, OSError) as exc:
        print(f"snip: {exc}", file=sys.stderr)
        return 1
    print(f"snip listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
