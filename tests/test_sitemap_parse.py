"""parse_sitemap_bytes and entry_to_item: the pure core of sitemap_news."""

from __future__ import annotations

import gzip

import pytest

from clarion.ingest.streams.sitemap_news import entry_to_item, parse_sitemap_bytes

CANONICAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://example.com/story-one</loc>
    <news:news>
      <news:publication>
        <news:name>Example Times</news:name>
        <news:language>en</news:language>
      </news:publication>
      <news:publication_date>2026-07-03T01:00:00Z</news:publication_date>
      <news:title>Story One</news:title>
      <news:keywords>alpha, beta,  </news:keywords>
    </news:news>
  </url>
  <url>
    <loc>https://example.com/notitle-story</loc>
    <news:news>
      <news:publication_date>not-a-date</news:publication_date>
    </news:news>
  </url>
</urlset>
"""

# Asahi serves news under the pre-sitemaps.org root namespace; the news
# namespace itself is unchanged.
OLD_ROOT_NS = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.google.com/schemas/sitemap/0.84"
        xmlns:n="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://asahi.example/article</loc>
    <n:news><n:title>Old NS</n:title></n:news>
  </url>
</urlset>
"""

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/news-1.xml</loc></sitemap>
</sitemapindex>
"""


def test_parses_canonical_urlset():
    entries = parse_sitemap_bytes(CANONICAL)
    assert len(entries) == 2

    first = entries[0]
    assert first.url == "https://example.com/story-one"
    assert first.title == "Story One"
    assert first.published is not None and first.published.isoformat().startswith("2026-07-03T01:00:00")
    assert first.keywords == ["alpha", "beta"]
    assert first.publication_name == "Example Times"
    assert first.language == "en"


def test_missing_title_falls_back_to_url_segment_and_bad_date_is_none():
    entries = parse_sitemap_bytes(CANONICAL)
    second = entries[1]
    assert second.title == "notitle story"
    assert second.published is None
    assert second.publication_name is None


def test_gzipped_body_is_decompressed():
    entries = parse_sitemap_bytes(gzip.compress(CANONICAL))
    assert [e.url for e in entries] == [
        "https://example.com/story-one",
        "https://example.com/notitle-story",
    ]


def test_old_google_root_namespace():
    entries = parse_sitemap_bytes(OLD_ROOT_NS)
    assert len(entries) == 1
    assert entries[0].title == "Old NS"


def test_sitemap_index_raises_with_child_hint():
    with pytest.raises(RuntimeError, match="news-1.xml"):
        parse_sitemap_bytes(INDEX)


def test_invalid_xml_raises():
    with pytest.raises(RuntimeError, match="invalid XML"):
        parse_sitemap_bytes(b"this is not xml")


def test_unexpected_root_raises():
    with pytest.raises(RuntimeError, match="unexpected root"):
        parse_sitemap_bytes(b"<rss/>")


def test_item_has_no_body_and_prefers_per_entry_publication():
    entries = parse_sitemap_bytes(CANONICAL)
    item = entry_to_item(entries[0], stream_name="src:example.com", fallback_publication="Config Name")
    # A sitemap carries no article text; everything it does carry has a column.
    assert item.body is None
    assert item.author == "Example Times"  # XML wins over the fallback
    assert item.metadata["publication"] == "Example Times"
    assert item.metadata["language"] == "en"


def test_item_publication_falls_back_to_config():
    entries = parse_sitemap_bytes(CANONICAL)
    item = entry_to_item(entries[1], stream_name="src:example.com", fallback_publication="Config Name")
    assert item.author == "Config Name"
