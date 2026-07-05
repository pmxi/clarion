"""RSS/Atom streams: config schema, pure entry→Item mapping, one-poll fetch."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import aiohttp
import feedparser
from pydantic import BaseModel, HttpUrl

from clarion.ingest.streams.base import Item
from clarion.timeutils import utc_now

SOURCE_TYPE = "rss"

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=30)


class RSSStreamConfig(BaseModel):
    """One RSS/Atom feed subscription."""

    feed_url: HttpUrl
    poll_seconds: int = 300          # default 5 minutes
    enabled: bool = True
    max_entries_per_poll: int = 50   # cap to avoid flooding on first poll

    model_config = {"use_enum_values": True}


async def fetch(
    session: aiohttp.ClientSession, name: str, config: RSSStreamConfig
) -> list[Item]:
    """One poll: async fetch + sync parse on bytes. feedparser.parse(URL)
    would do its own blocking urllib fetch, which under asyncio.to_thread
    exhausts the event loop's threadpool at thousands of streams; parsing
    bytes in a thread is pure-Python and cheap."""
    feed_url = str(config.feed_url)
    async with session.get(feed_url, timeout=_FETCH_TIMEOUT, allow_redirects=True) as resp:
        resp.raise_for_status()
        raw = await resp.read()
    parsed = await asyncio.to_thread(feedparser.parse, raw)
    return entries_to_items(parsed, stream_name=name, feed_url=feed_url)


def entries_to_items(parsed: Any, *, stream_name: str, feed_url: str) -> list[Item]:
    """Pure mapping from a feedparser result to Items (id-less entries dropped)."""
    entries = getattr(parsed, "entries", []) or []
    feed_meta = getattr(parsed, "feed", None)
    out: list[Item] = []
    for entry in entries:
        item = entry_to_item(entry, feed_meta, stream_name=stream_name, feed_url=feed_url)
        if item is not None:
            out.append(item)
    return out


def entry_to_item(
    entry: Any, feed_meta: Any, *, stream_name: str, feed_url: str
) -> Item | None:
    entry_id = (
        getattr(entry, "id", None)
        or getattr(entry, "guid", None)
        or getattr(entry, "link", None)
    )
    if not entry_id:
        return None

    title = getattr(entry, "title", "") or "(no title)"
    url = getattr(entry, "link", None)
    published = _entry_published(entry)

    summary = getattr(entry, "summary", "") or ""
    content_list = getattr(entry, "content", None) or []
    full_content = summary
    if content_list:
        full_content = "\n\n".join(
            c.get("value", "") for c in content_list if isinstance(c, dict)
        ) or summary

    feed_title = getattr(feed_meta, "title", "") or "RSS feed"
    author = (
        getattr(entry, "author", None)
        or feed_title
    )

    body = (
        f"Feed: {feed_title}\n"
        f"Title: {title}\n"
        f"Author: {author}\n"
        f"Published: {published.isoformat() if published else 'unknown'}\n"
        f"URL: {url or 'N/A'}\n\n"
        f"{full_content}"
    )

    return Item(
        id=str(entry_id),
        source_type=SOURCE_TYPE,
        title=title,
        body=body,
        author=author,
        url=url,
        received_at=published or utc_now(),
        metadata={
            "feed_title": feed_title,
            "feed_url": feed_url,
            "stream_name": stream_name,
        },
    )


def _entry_published(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            try:
                return datetime(*value[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None
