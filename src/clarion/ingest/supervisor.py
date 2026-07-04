"""Async supervisor for the collector process.

Supervises one task per enabled stream, hot-reloads the stream set from
the DB every 30s, and hands every yielded item to the shared batched
EventWriter. Pure collection — no classification, scoring, or notify.
"""

from __future__ import annotations

import asyncio
import signal
import time
from typing import Any, Dict, Optional

from clarion.db.pool import DictConnectionPool
from clarion.db.stores import state as state_store
from clarion.db.stores import streams as streams_store
from clarion.ingest.sources import Item, Stream, all_specs, build_stream, ensure_loaded
from clarion.ingest.writer import EventWriter
from clarion.logging import get_logger
from clarion.timeutils import utc_now

logger = get_logger("clarion.ingest.supervisor")

_RESTART_DELAY_SECONDS = 30
_STREAM_REFRESH_SECONDS = 30
# The event table is append-only and intentionally kept indefinitely — we
# never prune it. It grows fast under high-volume traffic, so capacity is
# managed at the infrastructure level (bigger volume, table partitioning,
# archiving), NOT by deleting history. Do not reintroduce a time-based prune
# here: a previous one silently failed for weeks, and "fixing" it would have
# deleted everything older than its cutoff.


class Supervisor:
    def __init__(self, pool: DictConnectionPool):
        ensure_loaded()
        self.pool = pool
        self._shutdown = asyncio.Event()
        # Live registry of running stream tasks.  Hot-reload diffs this
        # against the DB snapshot every _STREAM_REFRESH_SECONDS.
        self._stream_tasks: Dict[str, asyncio.Task] = {}
        # (source_type, config_json) per running stream — config drift
        # detection without re-parsing JSON every refresh.
        self._stream_config_sig: Dict[str, tuple[str, str]] = {}
        # Throttle for the per-item liveness write to monitoring_state.
        # Without this, every emitted item at scale (50+/s across thousands
        # of streams) triggers a serialized DB upsert.
        self._last_check_ts_monotonic: float = 0.0
        self._last_check_min_interval_s: float = 5.0
        # One batching writer shared across every stream. The per-stream
        # writer pattern was a non-starter at thousands of streams because
        # each instance would run its own batcher task and contend on the
        # DB lock.
        self._writer: Optional[EventWriter] = None

    async def run(self) -> None:
        logger.info("Starting Clarion supervisor")
        self._install_signal_handlers()

        await asyncio.to_thread(self._init_monitoring_state)

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

    def _init_monitoring_state(self) -> None:
        with self.pool.connection() as conn:
            if state_store.get_monitoring_start_time(conn) is None:
                state_store.set_monitoring_start_time(conn, utc_now())

    def _list_streams(self):
        with self.pool.connection() as conn:
            return streams_store.list_all(conn)

    async def _refresh_streams(self, initial: bool = False) -> None:
        rows = await asyncio.to_thread(self._list_streams)
        supported_types = all_specs()
        unsupported = [r for r in rows if r["source_type"] not in supported_types]
        if initial and unsupported:
            logger.warning(
                "Ignoring %d unsupported stream row(s): %s",
                len(unsupported),
                ", ".join(sorted({r["source_type"] for r in unsupported})),
            )
        desired: Dict[str, Dict[str, Any]] = {
            r["name"]: r for r in rows if r["source_type"] in supported_types
        }

        # Cancel tasks for streams that no longer exist.
        removed = [n for n in self._stream_tasks if n not in desired]
        for name in removed:
            await self._stop_stream(name, reason="removed from DB")

        added = 0
        updated = 0
        for name, row in desired.items():
            sig = (row["source_type"], row["config_json"])
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
            logger.info("Supervising %d stream task(s)", len(self._stream_tasks))
        elif added or updated or removed:
            logger.info(
                "Stream refresh: +%d  ~%d  -%d  (running=%d)",
                added, updated, len(removed), len(self._stream_tasks),
            )

    def _start_stream(self, name: str, row: Dict[str, Any]) -> None:
        try:
            stream = build_stream(
                source_type=row["source_type"],
                name=row["name"],
                config_json=row["config_json"],
            )
        except Exception as exc:
            logger.error(
                "Failed to build stream %r (type=%s): %s",
                name, row["source_type"], exc,
            )
            return
        task = asyncio.create_task(
            self._run_stream(stream),
            name=f"stream:{name}",
        )
        self._stream_tasks[name] = task
        self._stream_config_sig[name] = (row["source_type"], row["config_json"])

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
                if self._writer is None:
                    self._writer = EventWriter(self.pool)
                writer = self._writer
                # Concurrency cap per stream. With many streams (700+),
                # 64-per-stream multiplied = 45k+ items potentially in-flight.
                # 8 is enough to overlap I/O without ballooning queue memory.
                sem = asyncio.Semaphore(8)
                in_flight: set[asyncio.Task] = set()

                async def _handle(item: Item) -> None:
                    async with sem:
                        try:
                            await writer.put(item)
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
                    "Stream %r crashed: %s. Restarting in %ss",
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
        logger.info("Received signal %s. Initiating shutdown.", sig)
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
            with self.pool.connection() as conn:
                state_store.set_last_check_time(conn, utc_now())
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
