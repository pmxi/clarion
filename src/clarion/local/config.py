"""Local runtime settings loaded from PostgreSQL-backed app_settings."""

from __future__ import annotations

import os
from typing import Any, TYPE_CHECKING, Optional

from dotenv import load_dotenv

if TYPE_CHECKING:
    from clarion.local.database import LocalDatabase

load_dotenv()


class LocalSettings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"
    DISABLE_FILE_LOGGING: bool = False

    SESSION_SECRET: Optional[str] = None

    @classmethod
    def require_database_url(cls) -> str:
        if not cls.DATABASE_URL:
            raise ValueError(
                "DATABASE_URL is required. Set it in .env or the service environment."
            )
        return cls.DATABASE_URL

    @classmethod
    def load(cls, db: "LocalDatabase") -> None:
        for key, raw in db.get_all_app_settings().items():
            if not hasattr(cls, key):
                continue
            default = getattr(cls, key)
            target = type(default) if default is not None else str
            setattr(cls, key, _coerce(raw, target))


def _coerce(raw: str, target: type) -> Any:
    if target is bool:
        return str(raw).strip().lower() in ("true", "1", "yes", "on")
    if target is int:
        return int(raw)
    return raw


settings = LocalSettings()
