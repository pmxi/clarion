"""entries_to_items: the pure core of the rss stream."""

from __future__ import annotations

from datetime import UTC, datetime

import feedparser

from clarion.ingest.streams.rss import entries_to_items

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Wire</title>
    <item>
      <title>First story</title>
      <link>https://example.com/first</link>
      <guid>tag:example.com,2026:first</guid>
      <author>alice@example.com</author>
      <pubDate>Sat, 04 Jul 2026 12:30:00 GMT</pubDate>
      <description>Something happened.</description>
    </item>
    <item>
      <title>No id or link here</title>
      <description>Unaddressable item.</description>
    </item>
    <item>
      <link>https://example.com/untitled</link>
    </item>
  </channel>
</rss>
"""


def _items(raw: bytes = FEED):
    return entries_to_items(
        feedparser.parse(raw),
        stream_name="wire",
        feed_url="https://example.com/feed.xml",
    )


def test_entry_maps_identity_and_content():
    first = _items()[0]
    assert first.id == "tag:example.com,2026:first"
    assert first.source_type == "rss"
    assert first.title == "First story"
    assert first.url == "https://example.com/first"
    assert first.author == "alice@example.com"
    assert first.received_at == datetime(2026, 7, 4, 12, 30, tzinfo=UTC)


def test_entry_metadata_carries_feed_context():
    first = _items()[0]
    assert first.metadata == {
        "feed_title": "Example Wire",
        "feed_url": "https://example.com/feed.xml",
        "stream_name": "wire",
    }


def test_idless_entries_are_dropped():
    items = _items()
    assert [i.url for i in items] == [
        "https://example.com/first",
        "https://example.com/untitled",
    ]


def test_link_serves_as_id_and_title_gets_a_default():
    untitled = _items()[1]
    assert untitled.id == "https://example.com/untitled"
    assert untitled.title == "(no title)"


def test_missing_date_falls_back_to_now():
    untitled = _items()[1]
    assert untitled.received_at.tzinfo is not None
    assert untitled.received_at.year >= 2026
