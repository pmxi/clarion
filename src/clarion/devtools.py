"""Synthetic local firehose for exercising the web UI.

This bypasses slow upstream publishers by writing news events directly
into the `event` table at a configurable rate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from clarion.db import pool as db_pool
from clarion.db.stores import events as events_store
from clarion.db.stores import monitoring as monitoring_store
from clarion.timeutils import utc_now

_TOPICS = (
    "Breaking market update",
    "Security advisory",
    "Infra latency spike",
    "Build pipeline status",
    "Competitive launch",
    "Customer escalation",
    "Regulatory filing",
    "Service health change",
)

_AUTHORS = (
    "Wire Desk",
    "Ops Watch",
    "Market Feed",
    "Build Monitor",
    "Incident Bot",
    "Release Radar",
)


@dataclass(frozen=True)
class FirehoseConfig:
    rate: float = 20.0
    count: int | None = 200
    source_type: str = "rss"
    stream_name: str = "dev-firehose"


def run_firehose(database_url: str, config: FirehoseConfig) -> int:
    if config.rate <= 0:
        raise ValueError("rate must be greater than 0")
    if config.count is not None and config.count < 0:
        raise ValueError("count must be >= 0")

    emitted = 0
    interval_seconds = 1.0 / config.rate

    with db_pool.raw_connection(database_url) as conn:
        if monitoring_store.get_monitoring_start_time(conn) is None:
            monitoring_store.set_monitoring_start_time(conn, utc_now())

        while config.count is None or emitted < config.count:
            started = time.perf_counter()
            item_number = emitted + 1
            now = utc_now()
            topic = _TOPICS[(item_number - 1) % len(_TOPICS)]
            author = _AUTHORS[(item_number - 1) % len(_AUTHORS)]
            events_store.insert_bulk(
                conn,
                [{
                    "source_type": config.source_type,
                    "item_id": f"{config.stream_name}-{item_number:06d}",
                    "stream_name": config.stream_name,
                    "title": f"{topic} #{item_number}",
                    "body": None,
                    "url": f"https://example.test/{config.stream_name}/{item_number}",
                    "author": author,
                    "received_at": now,
                }],
            )
            monitoring_store.set_last_check_time(conn, now)

            emitted += 1
            remaining = interval_seconds - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)

    return emitted
