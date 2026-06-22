"""Generic item-processing primitives shared by every runtime.

Clarion is a news collector: streams yield items, and the runtime persists
them. The only lifecycle event is `item_received`; an observer turns that
into a durable row. (Classification/notification used to live here and were
removed when Clarion narrowed to pure collection.)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from clarion.core.streams.base import Item


@dataclass(frozen=True)
class ProcessingEvent:
    event_type: str
    item: Item


@runtime_checkable
class ProcessingObserver(Protocol):
    async def publish(self, event: ProcessingEvent) -> None:
        """Observe processing lifecycle events."""
