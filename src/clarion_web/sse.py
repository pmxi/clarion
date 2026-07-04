"""Server-sent-events plumbing for the live feed."""

from __future__ import annotations

import json
import time
from typing import Any, Dict

from clarion.db import pool as db_pool
from clarion.db.stores import events as events_store


def row_to_payload(row: Dict[str, Any]) -> tuple[str, str]:
    """Render an event row into the (event_type, payload_json) pair the
    SSE client expects."""
    received_at = row.get("received_at")
    payload: Dict[str, Any] = {
        "source_type": row.get("source_type"),
        "item_id": row.get("item_id"),
        "stream_name": row.get("stream_name"),
        "title": row.get("title"),
        "body": row.get("body"),
        "url": row.get("url"),
        "author": row.get("author"),
        "received_at": received_at.isoformat() if received_at else None,
    }
    return "item_received", json.dumps(payload, default=str)


def frame(event_id: int, event_type: str, payload_json: str) -> str:
    return f"id: {event_id}\nevent: {event_type}\ndata: {payload_json}\n\n"


def poll_loop(database_url: str, cursor: int):
    """Each SSE client gets a dedicated connection outside the pool: the
    generator lives for the whole browser-tab lifetime and would starve a
    small pool."""

    def generate():
        nonlocal cursor
        yield "retry: 3000\n: connected\n\n"
        heartbeat_countdown = 30
        conn = db_pool.raw_connection(database_url)
        try:
            while True:
                rows = events_store.fetch_since(conn, cursor, limit=200)
                if rows:
                    for row in rows:
                        cursor = int(row["id"])
                        event_type, payload = row_to_payload(row)
                        yield frame(cursor, event_type, payload)
                    heartbeat_countdown = 30
                else:
                    heartbeat_countdown -= 1
                    if heartbeat_countdown <= 0:
                        yield ": keepalive\n\n"
                        heartbeat_countdown = 30
                time.sleep(0.5)
        finally:
            conn.close()

    return generate
