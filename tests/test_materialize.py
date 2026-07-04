"""The pure naming/cadence contract of catalog materialization.

Stream names must be stable across re-runs (idempotent upserts key on
them) and the src:/src-feed: prefixes are reserved for --prune.
"""

from __future__ import annotations

from clarion.catalog.materialize import (
    FEED_PREFIX,
    SITEMAP_PREFIX,
    Candidate,
    adaptive_poll_seconds,
    assign_names,
)


def make_candidate(
    source_type: str = "sitemap_news",
    domain: str = "example.com",
    target_url: str = "https://example.com/news.xml",
) -> Candidate:
    return Candidate(
        source_id=1,
        canonical_domain=domain,
        target_url=target_url,
        fresh_entries_24h=10,
        stories_per_week=100,
        publication_name="Example",
        primary_language="en",
        pub_country="USA",
        source_type=source_type,
    )


def test_poll_cadence_buckets():
    assert adaptive_poll_seconds(None) == 3600
    assert adaptive_poll_seconds(0) == 3600
    assert adaptive_poll_seconds(4) == 3600
    assert adaptive_poll_seconds(5) == 1800
    assert adaptive_poll_seconds(25) == 900
    assert adaptive_poll_seconds(100) == 300
    assert adaptive_poll_seconds(500) == 120
    assert adaptive_poll_seconds(10_000) == 120


def test_prefixes_by_source_type():
    sitemap = make_candidate("sitemap_news")
    feed = make_candidate("rss")
    assert sitemap.stream_name(suffix_if_collide=False) == f"{SITEMAP_PREFIX}example.com"
    assert feed.stream_name(suffix_if_collide=False) == f"{FEED_PREFIX}example.com"


def test_suffix_is_stable_hash_of_target_url():
    c = make_candidate()
    assert c.stream_name(suffix_if_collide=True) == c.stream_name(suffix_if_collide=True)
    other = make_candidate(target_url="https://example.com/other.xml")
    assert c.stream_name(suffix_if_collide=True) != other.stream_name(suffix_if_collide=True)


def test_assign_names_suffixes_only_on_collision():
    solo = make_candidate()
    names = assign_names([solo])
    assert names[solo] == f"{SITEMAP_PREFIX}example.com"

    a = make_candidate(target_url="https://example.com/a.xml")
    b = make_candidate(target_url="https://example.com/b.xml")
    names = assign_names([a, b])
    assert names[a] != names[b]
    assert all(n.startswith(f"{SITEMAP_PREFIX}example.com:") for n in names.values())


def test_same_domain_different_type_does_not_collide():
    sitemap = make_candidate("sitemap_news")
    feed = make_candidate("rss", target_url="https://example.com/feed")
    names = assign_names([sitemap, feed])
    assert names[sitemap] == f"{SITEMAP_PREFIX}example.com"
    assert names[feed] == f"{FEED_PREFIX}example.com"
