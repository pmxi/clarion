"""CRUD over the `stream` config table."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import psycopg
from psycopg.rows import DictRow

_UPSERT_SQL = (
    "INSERT INTO stream (name, source_type, config_json, updated_at) "
    "VALUES (%s, %s, %s::jsonb, NOW()) "
    "ON CONFLICT(name) DO UPDATE SET "
    "    source_type = excluded.source_type, "
    "    config_json = excluded.config_json, "
    "    updated_at  = NOW()"
)


def _upsert(conn: psycopg.Connection[DictRow], name: str, source_type: str, config_json: str) -> None:
    conn.execute(_UPSERT_SQL, (name, source_type, config_json))


def upsert_many(
    conn: psycopg.Connection[DictRow], rows: Sequence[Tuple[str, str, str]]
) -> None:
    """Bulk (name, source_type, config_json) upsert. One executemany so
    materializing 1000s of streams round-trips once over a slow link
    instead of once per row."""
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(_UPSERT_SQL, rows)


def delete_many(conn: psycopg.Connection[DictRow], names: Sequence[str]) -> None:
    """Bulk delete; missing names are ignored (unlike delete())."""
    if not names:
        return
    conn.execute("DELETE FROM stream WHERE name = ANY(%s)", (list(names),))


def list_by_prefix(
    conn: psycopg.Connection[DictRow], prefixes: Sequence[str]
) -> List[Dict[str, Any]]:
    """Stream rows whose name starts with any of the given prefixes."""
    if not prefixes:
        return []
    rows = conn.execute(
        "SELECT name, source_type, config_json::text AS config_json "
        "FROM stream WHERE name LIKE ANY(%s) ORDER BY name",
        ([p + "%" for p in prefixes],),
    ).fetchall()
    return [dict(r) for r in rows]


def add(conn: psycopg.Connection[DictRow], name: str, source_type: str, config_json: str) -> None:
    if get(conn, name):
        raise ValueError(f"Stream {name!r} already exists.")
    _upsert(conn, name, source_type, config_json)


def get(conn: psycopg.Connection[DictRow], name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT name, source_type, config_json::text AS config_json "
        "FROM stream WHERE name=%s",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def list_all(conn: psycopg.Connection[DictRow]) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT name, source_type, config_json::text AS config_json "
        "FROM stream ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def delete(conn: psycopg.Connection[DictRow], name: str) -> None:
    if not get(conn, name):
        raise ValueError(f"No stream named {name!r}")
    conn.execute("DELETE FROM stream WHERE name=%s", (name,))


def toggle(conn: psycopg.Connection[DictRow], name: str) -> None:
    row = get(conn, name)
    if not row:
        raise ValueError(f"No stream named {name!r}")
    data = json.loads(row["config_json"])
    data["enabled"] = not data.get("enabled", True)
    _upsert(conn, name, row["source_type"], json.dumps(data))
