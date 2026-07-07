"""Queries over the append-only `event` table.

There is deliberately no prune/delete helper: events are kept
indefinitely and capacity is handled at the infrastructure level.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import psycopg
from psycopg.rows import DictRow


def insert_bulk(conn: psycopg.Connection[DictRow], rows: List[Dict[str, Any]]) -> List[int]:
    """Bulk-insert events; dict keys match the column names. Returns ids
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


def fetch_clusterable_since(
    conn: psycopg.Connection[DictRow], after_id: int, limit: int = 512
) -> List[Dict[str, Any]]:
    """The digest daemon's feed: events past the cursor whose titles are
    long enough to carry story signal (mirrors the backfill builder's
    LENGTH filter; ultra-short titles congeal into junk clusters)."""
    rows = conn.execute(
        """
        SELECT id, title, url, stream_name, observed_at
        FROM event
        WHERE id > %s AND LENGTH(title) >= 12
        ORDER BY id ASC LIMIT %s
        """,
        (after_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def latest_id(conn: psycopg.Connection[DictRow]) -> int:
    row = conn.execute("SELECT COALESCE(MAX(id), 0) AS mx FROM event").fetchone()
    return int(row["mx"]) if row else 0


def min_id_since(conn: psycopg.Connection[DictRow], since: Any) -> Optional[int]:
    row = conn.execute(
        "SELECT MIN(id) AS mn FROM event WHERE observed_at >= %s", (since,)
    ).fetchone()
    return int(row["mn"]) if row and row["mn"] is not None else None


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


