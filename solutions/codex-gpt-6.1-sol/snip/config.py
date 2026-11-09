"""Explicit configuration; never infer the public origin from request headers."""

from dataclasses import dataclass
from ipaddress import IPv6Address
import os
from pathlib import Path
import re
from urllib.parse import urlsplit


def valid_url(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    # urlsplit silently strips some controls; reject them before parsing.
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return False
    if "\\" in value:
        return False
    try:
        value.encode("utf-8")
        parts = urlsplit(value)
        host = parts.hostname
        if parts.scheme.lower() not in {"http", "https"} or not host or parts.port == 0:
            return False
        if ":" in host:
            IPv6Address(host)
        else:
            # Validate IDNA now: otherwise redirect header construction can fail
            # later for empty/oversized labels, after a link has been stored.
            ascii_host = host.encode("idna").decode("ascii")
            if not re.fullmatch(r"[A-Za-z0-9._-]+", ascii_host):
                return False
            if "[" in parts.netloc or "]" in parts.netloc:
                return False
        return True
    except (ValueError, UnicodeError):
        return False


@dataclass(frozen=True)
class Settings:
    api_token: str
    database: Path = Path("data/snip.db")
    base_url: str = "http://localhost:8000"

    def __post_init__(self) -> None:
        if not self.api_token or self.api_token.strip() != self.api_token:
            raise ValueError("SNIP_API_TOKEN must be set and have no surrounding whitespace")
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in self.api_token):
            raise ValueError("SNIP_API_TOKEN must not contain whitespace or control characters")
        if not valid_url(self.base_url):
            raise ValueError("SNIP_BASE_URL must be an absolute HTTP(S) origin")
        origin = urlsplit(self.base_url)
        if origin.path not in {"", "/"} or origin.query or origin.fragment or origin.username is not None:
            raise ValueError("SNIP_BASE_URL must be an origin without credentials, query, fragment or path")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_token=os.environ.get("SNIP_API_TOKEN", ""),
            database=Path(os.environ.get("SNIP_DB_PATH", "data/snip.db")),
            base_url=os.environ.get("SNIP_BASE_URL", "http://localhost:8000"),
        )

