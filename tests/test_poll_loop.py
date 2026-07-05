"""The poll loop's contract: priming, dedup, capping, error recovery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from clarion.ingest.poll import poll_stream
from clarion.ingest.streams.base import Item


@dataclass
class _Config:
    poll_seconds: int = 0
    enabled: bool = True
    max_entries_per_poll: int = 50


def _item(item_id: str) -> Item:
    return Item(
        id=item_id,
        source_type="test",
        title=item_id,
        body="",
        author="tester",
        url=None,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _run(script: list, config: _Config | None = None) -> list[str]:
    """Drive poll_stream through scripted polls; return emitted item ids.

    Each script element is a list of item ids to return, or an exception
    to raise, one per poll. An exhausted script cancels the loop — the
    only way poll_stream terminates.
    """
    polls = iter(script)
    emitted: list[str] = []

    async def fetch(session, name, cfg):
        try:
            batch = next(polls)
        except StopIteration:
            raise asyncio.CancelledError from None
        if isinstance(batch, Exception):
            raise batch
        return [_item(i) for i in batch]

    async def emit(item: Item) -> None:
        emitted.append(item.id)

    async def main() -> None:
        try:
            await poll_stream(
                name="test-stream",
                config=config or _Config(),
                fetch=fetch,
                session=None,
                emit=emit,
            )
        except asyncio.CancelledError:
            pass

    asyncio.run(main())
    return emitted


def test_first_poll_primes_without_emitting():
    assert _run([["a", "b"]]) == []


def test_new_items_after_priming_are_emitted():
    assert _run([["a", "b"], ["a", "b", "c"]]) == ["c"]


def test_items_are_never_reemitted_across_polls():
    assert _run([["a"], ["a", "b"], ["a", "b"], ["b", "c"]]) == ["b", "c"]


def test_max_entries_caps_each_poll():
    config = _Config(max_entries_per_poll=2)
    # Priming sees only [a, b]; the second poll's cap keeps [a, c].
    assert _run([["a", "b", "x"], ["a", "c", "y"]], config) == ["c"]


def test_failed_first_poll_keeps_priming_pending():
    # The backlog must not flood out just because poll #1 errored.
    assert _run([RuntimeError("boom"), ["a"], ["a", "b"]]) == ["b"]


def test_poll_errors_do_not_kill_the_loop():
    assert _run([["a"], RuntimeError("boom"), ["a", "b"]]) == ["b"]


def test_disabled_stream_never_fetches():
    fetches: list[int] = []

    async def fetch(session, name, cfg):
        fetches.append(1)
        return []

    async def emit(item):
        raise AssertionError("nothing should be emitted")

    asyncio.run(
        poll_stream(
            name="off",
            config=_Config(enabled=False),
            fetch=fetch,
            session=None,
            emit=emit,
        )
    )
    assert fetches == []


def test_cancellation_propagates():
    async def fetch(session, name, cfg):
        raise asyncio.CancelledError

    async def emit(item):
        pass

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            poll_stream(
                name="t", config=_Config(), fetch=fetch, session=None, emit=emit
            )
        )
