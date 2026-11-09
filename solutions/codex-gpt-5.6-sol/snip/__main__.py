"""Command-line entry point for ``python -m snip``."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from urllib.parse import urlsplit

from .app import SnipApplication, SnipServer
from .storage import LinkStore


@dataclass(frozen=True, slots=True)
class Config:
    host: str
    port: int
    database_path: str
    api_token: str
    base_url: str

    @classmethod
    def from_environment(cls) -> "Config":
        host = os.environ.get("SNIP_HOST", "127.0.0.1")
        raw_port = os.environ.get("SNIP_PORT", "8000")
        try:
            port = int(raw_port)
        except ValueError as error:
            raise ValueError("SNIP_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ValueError("SNIP_PORT must be between 1 and 65535")
        api_token = os.environ.get("SNIP_API_TOKEN", "")
        if not api_token:
            raise ValueError("SNIP_API_TOKEN must be set and non-empty")
        database_path = os.environ.get("SNIP_DB_PATH", "snip.db")
        default_host = "localhost" if host in {"0.0.0.0", "::"} else host
        if ":" in default_host and not default_host.startswith("["):
            default_host = f"[{default_host}]"
        base_url = os.environ.get("SNIP_BASE_URL", f"http://{default_host}:{port}").rstrip("/")
        parsed_base = urlsplit(base_url)
        if (
            parsed_base.scheme not in {"http", "https"}
            or not parsed_base.netloc
            or parsed_base.path not in {"", "/"}
            or parsed_base.query
            or parsed_base.fragment
        ):
            raise ValueError("SNIP_BASE_URL must be an absolute http(s) origin without a path")
        return cls(host, port, database_path, api_token, base_url)


def main() -> int:
    try:
        config = Config.from_environment()
        store = LinkStore(config.database_path)
        application = SnipApplication(store, config.api_token, config.base_url)
        server = SnipServer((config.host, config.port), application)
    except (OSError, ValueError) as error:
        print(f"snip: configuration error: {error}", file=sys.stderr)
        return 2

    print(f"snip listening on {config.host}:{config.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

