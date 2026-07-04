"""Key-value app settings (`app_setting`)."""

from __future__ import annotations

from typing import Dict, Optional

import psycopg
from psycopg.rows import DictRow


def get(conn: psycopg.Connection[DictRow], key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_setting WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else None


def set(conn: psycopg.Connection[DictRow], key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_setting (key, value, updated_at) "
        "VALUES (%s, %s, NOW()) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=NOW()",
        (key, value),
    )


def all(conn: psycopg.Connection[DictRow]) -> Dict[str, str]:
    rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
    return {r["key"]: r["value"] for r in rows}
