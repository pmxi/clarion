"""Runtime settings.

DATABASE_URL comes from the environment (.env is honored); everything
else loads from the Postgres-backed `app_setting` table via load().
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Optional

from dotenv import load_dotenv

if TYPE_CHECKING:
    import psycopg
    from psycopg.rows import DictRow

load_dotenv()


class Settings:
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
    def load(cls, conn: "psycopg.Connection[DictRow]") -> None:
        from clarion.db.stores import settings as settings_store

        for key, raw in settings_store.all(conn).items():
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


settings = Settings()
