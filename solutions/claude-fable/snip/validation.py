import re
import secrets
from urllib.parse import urlsplit

MAX_URL_LEN = 2048
SLUG_RE = re.compile(r"[A-Za-z0-9_-]{3,32}")
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
GENERATED_SLUG_LEN = 8

# Paths owned by the service; a custom slug may not shadow them.
RESERVED_SLUGS = frozenset({"api", "healthz", "docs", "redoc", "openapi"})


class ValidationError(ValueError):
    pass


def validate_url(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValidationError("url is required and must be a string")
    if len(value) > MAX_URL_LEN:
        raise ValidationError(f"url must be at most {MAX_URL_LEN} characters")
    if value != value.strip() or any(ord(c) < 33 or ord(c) == 127 for c in value):
        raise ValidationError("url must not contain whitespace or control characters")
    try:
        parts = urlsplit(value)
        host = parts.hostname
        parts.port  # raises ValueError on a bad port
    except ValueError:
        raise ValidationError("url is malformed") from None
    if parts.scheme.lower() not in ("http", "https"):
        raise ValidationError("url must be an absolute http or https URL")
    if not host:
        raise ValidationError("url must include a host")
    return value


def validate_slug(value: object) -> str:
    if not isinstance(value, str) or not SLUG_RE.fullmatch(value):
        raise ValidationError("slug must be 3-32 characters of [A-Za-z0-9_-]")
    if value.lower() in RESERVED_SLUGS:
        raise ValidationError("slug is reserved")
    return value


def generate_slug() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(GENERATED_SLUG_LEN))
