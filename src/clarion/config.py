"""Runtime configuration: DATABASE_URL from the environment (.env honored)."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def require_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError(
            "DATABASE_URL is required. Set it in .env or the service environment."
        )
    return url
