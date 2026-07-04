"""CRUD over the `stream` config table."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import DictRow


def upsert(conn: psycopg.Connection[DictRow], name: str, source_type: str, config_json: str) -> None:
    conn.execute(
        "INSERT INTO stream (name, source_type, config_json, updated_at) "
        "VALUES (%s, %s, %s::jsonb, NOW()) "
        "ON CONFLICT(name) DO UPDATE SET "
        "    source_type = excluded.source_type, "
        "    config_json = excluded.config_json, "
        "    updated_at  = NOW()",
        (name, source_type, config_json),
    )


def add(conn: psycopg.Connection[DictRow], name: str, source_type: str, config_json: str) -> None:
    if get(conn, name):
        raise ValueError(f"Stream {name!r} already exists.")
    upsert(conn, name, source_type, config_json)


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
    upsert(conn, name, row["source_type"], json.dumps(data))
