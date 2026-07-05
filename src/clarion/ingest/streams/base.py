"""The cross-type stream contract.

A stream type is a pydantic config model plus an async fetch function;
the generic poll loop (clarion.ingest.poll) runs the pair. The Item is
what crosses the stream boundary — source-specific types (RSS entries,
sitemap records) stay inside each stream module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Protocol

import aiohttp

# One User-Agent for every outbound fetch. Some publishers serve bots an
# empty or blocked response, so we look like a current desktop browser.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


@dataclass
class Item:
    """A single unit produced by one poll of a stream.

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


# One poll = one fetch. A stream type's fetch function has this shape:
# (shared session, stream name, config) -> the source's current Items.
# Freshness filtering, dedup, and cadence live in the poll loop, not here.
Fetcher = Callable[[aiohttp.ClientSession, str, Any], Awaitable["list[Item]"]]
