"""Generic poll loop — the one place the polling contract lives.

A stream type is just a config model plus an async fetch function; this
loop owns everything around the fetch: the enabled check, cross-poll
dedup, first-poll backlog priming, entry capping, per-poll error
handling, and the sleep cadence.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import aiohttp

from clarion.ingest.streams.base import Fetcher, Item, PollConfig
from clarion.logging import get_logger

logger = get_logger(__name__)


async def poll_stream(
    *,
    name: str,
    config: PollConfig,
    fetch: Fetcher,
    session: aiohttp.ClientSession,
    emit: Callable[[Item], Awaitable[None]],
) -> None:
    """Run one stream's poll loop until cancelled.

    The first successful poll primes the seen set without emitting —
    otherwise every (re)start would flood the event table with the
    stream's whole backlog. A poll that raises keeps priming pending.
    The in-memory seen set is belt-and-suspenders: the event table's
    UNIQUE (source_type, item_id) is the real cross-restart dedup.
    """
    if not config.enabled:
        logger.info(f"[{name}] disabled; not starting")
        return

    seen: set[str] = set()
    priming = True
    while True:
        try:
            items = await fetch(session, name, config)
            for item in items[: config.max_entries_per_poll]:
                if item.id in seen:
                    continue
                seen.add(item.id)
                if priming:
                    continue
                await emit(item)
            priming = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"[{name}] poll failed: {exc}")
        await asyncio.sleep(config.poll_seconds)
