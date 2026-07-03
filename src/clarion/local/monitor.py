"""Async supervisor for the local single-user runtime.

Supervises one task per enabled stream, hot-reloads the stream set from the
DB, and persists every yielded item into the append-only `event` table via a
batched writer. Pure collection — no classification, scoring, or notify.
"""

from __future__ import annotations

import asyncio
import signal
import time
from typing import Any, Dict, List, Optional

from clarion.logging import get_logger
from clarion.core import ProcessingEvent
from clarion.core.processing import ProcessingObserver
from clarion.core.streams import Item, Stream, build_stream, ensure_loaded
from clarion.timeutils import utc_now
from clarion.local.database import LocalDatabase
from clarion.local.services.streams import LocalStreamService

logger = get_logger("clarion.local.monitor")

_RESTART_DELAY_SECONDS = 30
_STREAM_REFRESH_SECONDS = 30
# The event table is append-only and intentionally kept indefinitely — we
# never prune it. It grows fast under high-volume traffic, so capacity is
# managed at the infrastructure level (bigger volume, table partitioning,
# archiving), NOT by deleting history. Do not reintroduce a time-based prune
# here: a previous one silently failed for weeks, and "fixing" it would have
# deleted everything older than its cutoff.


class LocalMonitor:
    def __init__(self, database: LocalDatabase):
        ensure_loaded()
        self.db = database
        self.stream_service = LocalStreamService(database)
        self._shutdown = asyncio.Event()
        # Live registry of running stream tasks.  Hot-reload diffs this
        # against the DB snapshot every _STREAM_REFRESH_SECONDS.
        self._stream_tasks: Dict[str, asyncio.Task] = {}
        # (stream_type, config_json) per running stream — config drift
        # detection without re-parsing JSON every refresh.
        self._stream_config_sig: Dict[str, tuple[str, str]] = {}
        # Throttle for the per-item liveness write to monitoring_state.
        # Without this, every emitted item at scale (50+/s across thousands
        # of streams) triggers a serialized DB upsert.
        self._last_check_ts_monotonic: float = 0.0
        self._last_check_min_interval_s: float = 5.0
        # One batching observer shared across every stream. The per-stream
        # observer pattern was a non-starter at thousands of streams because
        # each instance would run its own batcher task and contend on the
        # DB lock.
        self._observer: Optional[_LocalProcessingObserver] = None

    async def run(self) -> None:
        logger.info("Starting local Clarion supervisor")
        self._install_signal_handlers()

        if self.db.get_monitoring_start_time() is None:
            self.db.set_monitoring_start_time(utc_now())

        await self._refresh_streams(initial=True)

        refresh_task = asyncio.create_task(self._refresh_loop(), name="stream-refresh")
        try:
            await self._shutdown.wait()
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except (asyncio.CancelledError, Exception):
                pass
            await self._cancel_all()

    async def _refresh_loop(self) -> None:
        """Periodically diff DB-configured streams against running tasks."""
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=_STREAM_REFRESH_SECONDS)
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self._refresh_streams()
            except Exception as exc:
                logger.warning("stream refresh failed: %s", exc)

    async def _refresh_streams(self, initial: bool = False) -> None:
        rows = await asyncio.to_thread(self.db.list_streams)
        supported_types = self.stream_service.specs()
        unsupported = [r for r in rows if r["stream_type"] not in supported_types]
        if initial and unsupported:
            logger.warning(
                "Ignoring %d unsupported stream row(s): %s",
                len(unsupported),
                ", ".join(sorted({r["stream_type"] for r in unsupported})),
            )
        desired: Dict[str, Dict[str, Any]] = {
            r["name"]: r for r in rows if r["stream_type"] in supported_types
        }

        # Cancel tasks for streams that no longer exist.
        removed = [n for n in self._stream_tasks if n not in desired]
        for name in removed:
            await self._stop_stream(name, reason="removed from DB")

        added = 0
        updated = 0
        for name, row in desired.items():
            sig = (row["stream_type"], row["config_json"])
            running = self._stream_tasks.get(name)
            if running is None or running.done():
                self._start_stream(name, row)
                added += 1
                continue
            if self._stream_config_sig.get(name) != sig:
                await self._stop_stream(name, reason="config changed")
                self._start_stream(name, row)
                updated += 1

        if initial:
            logger.info("Supervising %d local stream task(s)", len(self._stream_tasks))
        elif added or updated or removed:
            logger.info(
                "Stream refresh: +%d  ~%d  -%d  (running=%d)",
                added, updated, len(removed), len(self._stream_tasks),
            )

    def _start_stream(self, name: str, row: Dict[str, Any]) -> None:
        try:
            stream = build_stream(
                stream_type=row["stream_type"],
                name=row["name"],
                config_json=row["config_json"],
            )
        except Exception as exc:
            logger.error(
                "Failed to build stream %r (type=%s): %s",
                name, row["stream_type"], exc,
            )
            return
        task = asyncio.create_task(
            self._run_stream(stream),
            name=f"local-stream:{name}",
        )
        self._stream_tasks[name] = task
        self._stream_config_sig[name] = (row["stream_type"], row["config_json"])

    async def _stop_stream(self, name: str, *, reason: str) -> None:
        task = self._stream_tasks.pop(name, None)
        self._stream_config_sig.pop(name, None)
        if task is None or task.done():
            return
        logger.info("Stopping stream %r (%s)", name, reason)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    async def _run_stream(self, stream: Stream) -> None:
        while not self._shutdown.is_set():
            try:
                if self._observer is None:
                    self._observer = _LocalProcessingObserver(self.db)
                observer = self._observer
                # Concurrency cap per stream. With many streams (700+),
                # 64-per-stream multiplied = 45k+ items potentially in-flight.
                # 8 is enough to overlap I/O without ballooning queue memory.
                sem = asyncio.Semaphore(8)
                in_flight: set[asyncio.Task] = set()

                async def _handle(item: Item) -> None:
                    async with sem:
                        try:
                            await observer.publish(
                                ProcessingEvent(event_type="item_received", item=item)
                            )
                        finally:
                            # Coalesce monitoring_state.last_check_time writes so
                            # high-rate streams don't serialize on the connection.
                            self._maybe_update_last_check_time()

                async for item in stream.items():
                    if self._shutdown.is_set():
                        break
                    t = asyncio.create_task(_handle(item))
                    in_flight.add(t)
                    t.add_done_callback(in_flight.discard)

                if in_flight:
                    await asyncio.gather(*in_flight, return_exceptions=True)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(
                    "Local stream %r crashed: %s. Restarting in %ss",
                    stream.name,
                    exc,
                    _RESTART_DELAY_SECONDS,
                )
                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=_RESTART_DELAY_SECONDS,
                    )
                    return
                except asyncio.TimeoutError:
                    continue

    def _install_signal_handlers(self) -> None:
        import threading

        if threading.current_thread() is not threading.main_thread():
            return
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown, sig)
            except (NotImplementedError, RuntimeError):
                pass

    def _request_shutdown(self, sig: int) -> None:
        logger.info("Received signal %s. Initiating local shutdown.", sig)
        self._shutdown.set()

    def _maybe_update_last_check_time(self) -> None:
        """Coalesce monitoring_state writes. Benign race across streams: the
        UPSERT is idempotent so duplicate writes within the window are
        harmless. Avoids one DB round-trip per emitted item."""
        now = time.monotonic()
        if now - self._last_check_ts_monotonic < self._last_check_min_interval_s:
            return
        self._last_check_ts_monotonic = now
        try:
            self.db.update_last_check_time(utc_now())
        except Exception as exc:
            logger.warning("update_last_check_time failed: %s", exc)

    async def _cancel_all(self) -> None:
        tasks = list(self._stream_tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._stream_tasks.clear()
        self._stream_config_sig.clear()


# Bodies that duplicate the title verbatim waste space without information
# gain; store them as NULL and let consumers fall back to the title.
def _effective_body(item: Item) -> Optional[str]:
    body = (item.body or "").strip()
    title = (item.title or "").strip()
    if not body or body == title:
        return None
    return body


class _LocalProcessingObserver(ProcessingObserver):
    """Async batched writer for the `event` table.

    item_received -> insert into event (the UNIQUE (source_type, item_id)
    constraint also gives us cross-restart dedup for free).

    Uses a batched multi-row INSERT through a 50k-bounded asyncio.Queue.
    Drops events on overflow rather than blocking the supervising stream
    tasks. Producers do not see back-pressure.
    """

    BATCH_MAX = 500
    BATCH_INTERVAL_S = 0.25
    QUEUE_MAX = 50_000

    def __init__(self, db: LocalDatabase):
        self.db = db
        self._queue: "asyncio.Queue[Item]" = asyncio.Queue(maxsize=self.QUEUE_MAX)
        self._task: Optional[asyncio.Task] = None
        self._dropped: int = 0
        self._last_dropped_log: float = 0.0

    def _ensure_started(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush_loop(), name="event-batcher")

    async def publish(self, event: ProcessingEvent) -> None:
        self._ensure_started()
        if event.event_type != "item_received":
            return
        try:
            self._queue.put_nowait(event.item)
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
                await asyncio.to_thread(self.db.insert_events_bulk, rows)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("event batch flush failed: %s", exc)
                await asyncio.sleep(0.5)

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


_RESERVED_METADATA_KEYS = {"stream_name"}


def _filter_metadata(md: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not md:
        return None
    out = {k: v for k, v in md.items() if k not in _RESERVED_METADATA_KEYS}
    return out or None
