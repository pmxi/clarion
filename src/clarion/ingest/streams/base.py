"""Stream abstraction — transport-agnostic source of Items.

Every datastream (RSS, publisher sitemaps, Bluesky
firehose, ...) implements `Stream`. The async-generator contract hides whether
a stream is poll-based (RSS, sitemaps) or push-based (WebSocket, SSE) — the
supervisor consumes both identically:

    async for item in stream.items():
        ...

The Item is what crosses the stream boundary. Source-specific types
(RSSEntry, sitemap records) stay inside each stream's implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Protocol

import aiohttp

# One User-Agent for every outbound fetch. Some publishers serve bots an
# empty or blocked response, so we look like a current desktop browser.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass
class Item:
    """A single unit produced by a Stream.

    Fields mirror the `event` table columns the writer persists; the
    consumers are the digest builder and the web UI:
    - `title` is the first-line summary (subject, post title, headline)
    - `body` is the full text, when it adds anything beyond the title
    - `author` is who/what published the item
    - `url` is the deep link if the source provides one
    - `metadata` carries source-specific extras consumers may render
    """

    id: str
    source_type: str
    title: str
    body: str
    author: str
    url: str | None
    received_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class PollConfig(Protocol):
    """The fields every stream config must carry for the generic poll
    loop (clarion.ingest.poll); everything else is per-type."""

    poll_seconds: int
    enabled: bool
    max_entries_per_poll: int


# One poll = one fetch. A stream type is a config model plus a function
# of this shape: (shared session, stream name, config) -> current Items.
# Freshness filtering, dedup, and cadence live in the poll loop, not here.
Fetcher = Callable[[aiohttp.ClientSession, str, Any], Awaitable["list[Item]"]]


class Stream(ABC):
    """Base class for any datastream.

    Subclasses declare their `source_type` class attribute and implement
    `items()` as an async generator that yields Items indefinitely. Pull
    sources internally poll + sleep; push sources hold a connection and
    yield as events arrive. The supervisor doesn't care which.
    """

    source_type: str = ""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def items(self) -> AsyncIterator[Item]:
        """Yield Items as they become available. Runs indefinitely.

        Must be resilient — catch and log internal errors rather than
        letting them propagate. The supervisor treats a raised exception
        as "this stream is dead, restart it".
        """
        raise NotImplementedError
