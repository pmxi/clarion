"""Queries over the append-only `event` table.

There is deliberately no prune/delete helper: events are kept
indefinitely and capacity is handled at the infrastructure level.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import DictRow


def insert(
    conn: psycopg.Connection[DictRow],
    *,
    source_type: str,
    item_id: str,
    stream_name: str,
    title: str,
    body: Optional[str],
    url: Optional[str],
    author: Optional[str],
    received_at: datetime,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Insert one event. Returns its id, or None on a dedup hit."""
    row = conn.execute(
        """
        INSERT INTO event (source_type, item_id, stream_name, title, body,
                           url, author, received_at, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (source_type, item_id) DO NOTHING
        RETURNING id
        """,
        (source_type, item_id, stream_name, title, body, url, author,
         received_at, json.dumps(metadata) if metadata else None),
    ).fetchone()
    return int(row["id"]) if row else None


def insert_bulk(conn: psycopg.Connection[DictRow], rows: List[Dict[str, Any]]) -> List[int]:
    """Bulk-insert events; dict keys match insert()'s kwargs. Returns ids
    of rows actually inserted (dedup hits are omitted)."""
    if not rows:
        return []
    params = []
    for r in rows:
        md = r.get("metadata")
        params.append((
            r["source_type"], r["item_id"], r["stream_name"], r["title"],
            r.get("body"), r.get("url"), r.get("author"),
            r["received_at"],
            json.dumps(md) if md else None,
        ))
    placeholders = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)"] * len(params))
    flat: List[Any] = [v for row in params for v in row]
    inserted = conn.execute(
        f"""
        INSERT INTO event (source_type, item_id, stream_name, title, body,
                           url, author, received_at, metadata)
        VALUES {placeholders}
        ON CONFLICT (source_type, item_id) DO NOTHING
        RETURNING id
        """,
        flat,
    ).fetchall()
    return [int(r["id"]) for r in inserted]


def recent(conn: psycopg.Connection[DictRow], limit: int = 25) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, source_type, item_id, stream_name, title, url, author, "
        "received_at, observed_at "
        "FROM event ORDER BY observed_at DESC LIMIT %s",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def count(conn: psycopg.Connection[DictRow]) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM event").fetchone()
    return int(row["c"]) if row else 0


def latest_id(conn: psycopg.Connection[DictRow]) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS mx FROM event").fetchone()
    return int(row["mx"]) if row else 0


def fetch_since(
    conn: psycopg.Connection[DictRow], after_id: int, limit: int = 200
) -> List[Dict[str, Any]]:
    """Used by the SSE poll loop."""
    rows = conn.execute(
        """
        SELECT id, source_type, item_id, stream_name, title,
               body, url, author, received_at, observed_at, metadata
        FROM event
        WHERE id > %s
        ORDER BY id ASC LIMIT %s
        """,
        (after_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
