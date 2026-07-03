"""CRUD over the `stream` config table."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import psycopg


def upsert(conn: psycopg.Connection, name: str, stream_type: str, config_json: str) -> None:
    conn.execute(
        "INSERT INTO stream (name, stream_type, config_json, updated_at) "
        "VALUES (%s, %s, %s::jsonb, NOW()) "
        "ON CONFLICT(name) DO UPDATE SET "
        "    stream_type = excluded.stream_type, "
        "    config_json = excluded.config_json, "
        "    updated_at  = NOW()",
        (name, stream_type, config_json),
    )


def add(conn: psycopg.Connection, name: str, stream_type: str, config_json: str) -> None:
    if get(conn, name):
        raise ValueError(f"Stream {name!r} already exists.")
    upsert(conn, name, stream_type, config_json)


def get(conn: psycopg.Connection, name: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT name, stream_type, config_json::text AS config_json "
        "FROM stream WHERE name=%s",
        (name,),
    ).fetchone()
    return dict(row) if row else None


def list_all(conn: psycopg.Connection) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT name, stream_type, config_json::text AS config_json "
        "FROM stream ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def delete(conn: psycopg.Connection, name: str) -> None:
    if not get(conn, name):
        raise ValueError(f"No stream named {name!r}")
    conn.execute("DELETE FROM stream WHERE name=%s", (name,))


def toggle(conn: psycopg.Connection, name: str) -> None:
    row = get(conn, name)
    if not row:
        raise ValueError(f"No stream named {name!r}")
    data = json.loads(row["config_json"])
    data["enabled"] = not data.get("enabled", True)
    upsert(conn, name, row["stream_type"], json.dumps(data))
