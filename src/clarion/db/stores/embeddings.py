"""The `event_embedding` window cache: title vectors the digest daemon
needs to resume clustering after a restart. Prunable — regenerable by
re-embedding titles."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Sequence, Tuple

import psycopg
from psycopg.rows import DictRow


def put_many(
    conn: psycopg.Connection[DictRow],
    rows: Sequence[Tuple[int, bytes, datetime]],
) -> None:
    """(event_id, vec_bytes, observed_at) upserts; re-embeds win."""
    if not rows:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO event_embedding (event_id, vec, observed_at) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (event_id) DO UPDATE SET vec = excluded.vec",
            rows,
        )


def unassigned_since(
    conn: psycopg.Connection[DictRow], since: datetime
) -> List[Dict[str, Any]]:
    """Window events that are in no story — the daemon's singleton pool
    after a restart. Joined to event for the fields clustering needs."""
    rows = conn.execute(
        """
        SELECT ee.event_id, ee.vec, ee.observed_at,
               e.title, e.url, e.stream_name
        FROM event_embedding ee
        JOIN event e ON e.id = ee.event_id
        LEFT JOIN story_event se ON se.event_id = ee.event_id
        WHERE se.event_id IS NULL AND ee.observed_at >= %s
        ORDER BY ee.event_id
        """,
        (since,),
    ).fetchall()
    return [dict(r) for r in rows]


def prune_before(conn: psycopg.Connection[DictRow], cutoff: datetime) -> int:
    cur = conn.execute(
        "DELETE FROM event_embedding WHERE observed_at < %s", (cutoff,)
    )
    return cur.rowcount or 0
