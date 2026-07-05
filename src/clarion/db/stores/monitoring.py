"""Collector heartbeats (`monitoring_state`)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg
from psycopg.rows import DictRow

from clarion.timeutils import format_iso_datetime, parse_iso_datetime


def _get_ts(conn: psycopg.Connection[DictRow], key: str) -> Optional[datetime]:
    row = conn.execute(
        "SELECT value FROM monitoring_state WHERE key=%s", (key,)
    ).fetchone()
    if not row or row["value"] is None:
        return None
    # Values are always the ISO strings _set_ts wrote.
    return parse_iso_datetime(row["value"])


def _set_ts(conn: psycopg.Connection[DictRow], key: str, timestamp: datetime) -> None:
    conn.execute(
        "INSERT INTO monitoring_state (key, value) VALUES (%s, %s) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=NOW()",
        (key, format_iso_datetime(timestamp)),
    )


def get_monitoring_start_time(conn: psycopg.Connection[DictRow]) -> Optional[datetime]:
    return _get_ts(conn, "monitoring_start_time")


def set_monitoring_start_time(conn: psycopg.Connection[DictRow], timestamp: datetime) -> None:
    _set_ts(conn, "monitoring_start_time", timestamp)


def get_last_check_time(conn: psycopg.Connection[DictRow]) -> Optional[datetime]:
    return _get_ts(conn, "last_check_time")


def set_last_check_time(conn: psycopg.Connection[DictRow], timestamp: datetime) -> None:
    _set_ts(conn, "last_check_time", timestamp)
