import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_token: str | None
    db_path: str
    base_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("SNIP_API_TOKEN") or None
        base = os.environ.get("SNIP_BASE_URL") or None
        return cls(
            api_token=token,
            db_path=os.environ.get("SNIP_DB_PATH", "data/snip.db"),
            base_url=base.rstrip("/") if base else None,
        )
