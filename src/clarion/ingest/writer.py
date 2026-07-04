"""Async batched writer for the `event` table.

One shared instance across every stream: the per-stream writer pattern
was a non-starter at hundreds of streams because each instance would
run its own batcher task and contend on the DB connection.

Items flow through a bounded asyncio.Queue and are flushed as multi-row
INSERTs (the UNIQUE (source_type, item_id) constraint gives cross-restart
dedup for free). On overflow we drop and count rather than block the
supervising stream tasks — producers never see back-pressure.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from clarion.db.pool import DictConnectionPool
from clarion.db.stores import events as events_store
from clarion.ingest.streams import Item
from clarion.logging import get_logger

logger = get_logger(__name__)

_RESERVED_METADATA_KEYS = {"stream_name"}


class EventWriter:
    BATCH_MAX = 500
    BATCH_INTERVAL_S = 0.25
    QUEUE_MAX = 50_000

    def __init__(self, pool: DictConnectionPool):
        self.pool = pool
        self._queue: "asyncio.Queue[Item]" = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self._task: Optional[asyncio.Task] = None
        self._dropped: int = 0
        self._last_dropped_log: float = 0.0

    def _ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush_loop(), name="event-batcher")

    async def put(self, item: Item) -> None:
        self._ensure_started()
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1
            now = asyncio.get_running_loop().time()
            if now - self._last_dropped_log > 10:
                logger.warning("event queue full; dropped %d so far", self._dropped)
                self._last_dropped_log = now

    async def _flush_loop(self) -> None:
        while True:
            try:
                batch = await self._drain_one_batch()
                if not batch:
                    continue
                rows = [
                    {
                        "source_type": item.source_type,
                        "item_id": item.id,
                        "stream_name": (item.metadata or {}).get("stream_name", "") or "",
                        "title": item.title or "(no title)",
                        "body": _effective_body(item),
                        "url": item.url,
                        "author": item.author or None,
                        "received_at": item.received_at,
                        "metadata": _filter_metadata(item.metadata),
                    }
                    for item in batch
                ]
                await asyncio.to_thread(self._write_rows, rows)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("event batch flush failed: %s", exc)
                await asyncio.sleep(0.5)

    def _write_rows(self, rows: List[Dict[str, Any]]) -> None:
        with self.pool.connection() as conn:
            events_store.insert_bulk(conn, rows)

    async def _drain_one_batch(self) -> List[Item]:
        first = await self._queue.get()
        batch: List[Item] = [first]
        deadline = asyncio.get_running_loop().time() + self.BATCH_INTERVAL_S
        while len(batch) < self.BATCH_MAX:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(self._queue.get(), timeout=remaining))
            except asyncio.TimeoutError:
                break
        return batch


# Bodies that duplicate the title verbatim waste space without information
# gain; store them as NULL and let consumers fall back to the title.
def _effective_body(item: Item) -> Optional[str]:
    body = (item.body or "").strip()
    title = (item.title or "").strip()
    if not body or body == title:
        return None
    return body


def _filter_metadata(md: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not md:
        return None
    out = {k: v for k, v in md.items() if k not in _RESERVED_METADATA_KEYS}
    return out or None
