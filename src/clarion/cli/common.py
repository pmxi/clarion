"""Shared helpers for the CLI command modules."""

from __future__ import annotations

from typing import Optional

from clarion.config import settings
from clarion.db import pool as db_pool
from clarion.db.pool import DictConnectionPool


def open_pool() -> DictConnectionPool:
    return db_pool.open_pool(settings.require_database_url())


def prompt(label: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def database_label() -> str:
    """The DATABASE_URL with the password elided, for display."""
    url = settings.require_database_url()
    if "@" not in url:
        return url
    scheme_and_user, host_and_db = url.rsplit("@", maxsplit=1)
    if ":" not in scheme_and_user:
        return url
    return f"{scheme_and_user.rsplit(':', maxsplit=1)[0]}:***@{host_and_db}"
