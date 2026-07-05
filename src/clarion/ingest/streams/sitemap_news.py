"""Google News sitemap streams: config schema, pure XML parsing, one-poll fetch.

News orgs maintain a `<news:news>` sitemap (declared in robots.txt and
required by Google News) listing every article published in the last
~48h with publish timestamps. Polling it every minute or two gives a
near-real-time wire of headlines + URLs without scraping article HTML.

Supports gzipped sitemaps transparently (NYT, WaPo). Sitemap *index* files
(roots that list child sitemaps rather than article URLs) are rejected
with guidance — wire those by pointing at a leaf sitemap directly.
"""

from __future__ import annotations

import gzip
from dataclasses import dataclass
from datetime import datetime
from xml.etree import ElementTree as ET

import aiohttp
from pydantic import BaseModel

from clarion.ingest.streams.base import Item
from clarion.timeutils import parse_iso_datetime, utc_now

SOURCE_TYPE = "sitemap_news"

_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=30)

# The news namespace URI is canonical and consistent across publishers
# (we resolve by URI, not the `news:` / `n:` prefix the publisher uses).
# The urlset/sitemapindex namespace varies — `sitemaps.org/0.9` is most
# common but Asahi serves news under the older `google.com/.../0.84`
# namespace. We match those by local name + wildcard, not by URI.
_NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
_NS = {"news": _NEWS_NS}


class SitemapNewsStreamConfig(BaseModel):
    """Polls a publisher's Google News sitemap on a fixed interval."""

    sitemap_url: str
    publication_name: str = ""
    poll_seconds: int = 120
    enabled: bool = True
    max_entries_per_poll: int = 200


@dataclass(frozen=True, slots=True)
class SitemapEntry:
    url: str
    title: str
    published: datetime | None
    keywords: list[str]
    # Per-item publication metadata. Populated when <news:publication>
    # carries them; None otherwise. Multilingual feeds (BBC) put a
    # different name/language on every <url>, so trusting the stream
    # config alone would mislabel ~95% of items.
    publication_name: str | None
    language: str | None


async def fetch(
    session: aiohttp.ClientSession, name: str, config: SitemapNewsStreamConfig
) -> list[Item]:
    async with session.get(config.sitemap_url, timeout=_FETCH_TIMEOUT) as resp:
        resp.raise_for_status()
        raw = await resp.read()
    fallback = config.publication_name or name
    return [
        entry_to_item(entry, stream_name=name, fallback_publication=fallback)
        for entry in parse_sitemap_bytes(raw)
    ]


def entry_to_item(
    entry: SitemapEntry, *, stream_name: str, fallback_publication: str
) -> Item:
    # Per-item publication name from the XML wins; the config value (or
    # stream name) is just a fallback for publishers that omit
    # <news:publication><news:name>.
    publication = entry.publication_name or fallback_publication
    return Item(
        id=entry.url,
        source_type=SOURCE_TYPE,
        title=entry.title,
        # A news sitemap carries no article text — everything else it
        # gives us lives in the dedicated columns and metadata.
        body=None,
        author=publication,
        url=entry.url,
        received_at=entry.published or utc_now(),
        metadata={
            "stream_name": stream_name,
            "publication": publication,
            "language": entry.language,
            "keywords": entry.keywords,
        },
    )


def parse_sitemap_bytes(raw: bytes) -> list[SitemapEntry]:
    """Parse a Google News sitemap body into entries.

    Pure / synchronous so it's testable without a network. Handles:
      - gzipped bodies (NYT serves news.xml.gz)
      - the older google.com/.../sitemap/0.84 root namespace (Asahi)
      - the canonical sitemaps.org/0.9 root namespace
      - per-item <news:publication><news:name>/<news:language>
    Raises RuntimeError if the document is a sitemap index, not a leaf.
    """
    # aiohttp auto-decompresses gzipped HTTP responses, so don't trust
    # the URL suffix — only decompress when the bytes still carry the
    # gzip magic header.
    if _looks_gzipped(raw):
        raw = gzip.decompress(raw)

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid XML: {exc}") from exc

    tag = _local_name(root.tag)
    if tag == "sitemapindex":
        child = next(iter(root.findall("{*}sitemap/{*}loc")), None)
        child_url = child.text.strip() if child is not None and child.text else "(none)"
        raise RuntimeError(
            f"sitemap is an index, not a leaf — point at a child URL "
            f"(e.g. {child_url})"
        )
    if tag != "urlset":
        raise RuntimeError(f"unexpected root element: {tag!r}")

    out: list[SitemapEntry] = []
    for url_el in root.findall("{*}url"):
        loc_el = url_el.find("{*}loc")
        if loc_el is None or not loc_el.text:
            continue
        url = loc_el.text.strip()

        news_el = url_el.find("news:news", _NS)
        title = ""
        published: datetime | None = None
        keywords: list[str] = []
        publication_name: str | None = None
        language: str | None = None
        if news_el is not None:
            t = news_el.find("news:title", _NS)
            if t is not None and t.text:
                title = t.text.strip()
            pd = news_el.find("news:publication_date", _NS)
            if pd is not None and pd.text:
                published = _parse_iso(pd.text.strip())
            kw = news_el.find("news:keywords", _NS)
            if kw is not None and kw.text:
                keywords = [k.strip() for k in kw.text.split(",") if k.strip()]
            pub = news_el.find("news:publication", _NS)
            if pub is not None:
                n = pub.find("news:name", _NS)
                if n is not None and n.text:
                    publication_name = n.text.strip() or None
                lang = pub.find("news:language", _NS)
                if lang is not None and lang.text:
                    language = lang.text.strip() or None

        if not title:
            # Some publishers omit news:title; fall back to last URL segment.
            title = url.rsplit("/", 1)[-1].replace("-", " ").strip() or "(no title)"
        out.append(SitemapEntry(url, title, published, keywords, publication_name, language))
    return out


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _looks_gzipped(raw: bytes) -> bool:
    return len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B


def _parse_iso(value: str) -> datetime | None:
    """Lenient wrapper: publishers ship malformed dates; skip, don't crash."""
    try:
        return parse_iso_datetime(value)
    except ValueError:
        return None
