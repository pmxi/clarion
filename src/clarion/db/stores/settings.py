"""Key-value app settings (`app_setting`)."""

from __future__ import annotations

from typing import Dict, Optional

import psycopg


def get(conn: psycopg.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM app_setting WHERE key=%s", (key,)).fetchone()
    return row["value"] if row else None


def set(conn: psycopg.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO app_setting (key, value, updated_at) "
        "VALUES (%s, %s, NOW()) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=NOW()",
        (key, value),
    )


def all(conn: psycopg.Connection) -> Dict[str, str]:
    rows = conn.execute("SELECT key, value FROM app_setting").fetchall()
    return {r["key"]: r["value"] for r in rows}


def delete(conn: psycopg.Connection, key: str) -> None:
    conn.execute("DELETE FROM app_setting WHERE key=%s", (key,))
