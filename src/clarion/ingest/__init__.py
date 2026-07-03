"""Ingest: the collection domain.

`supervisor` runs one task per enabled stream; `sources` holds the
stream framework (base Item/Stream contract, registry, and the built-in
RSS + news-sitemap implementations); `writer` batches yielded items
into the append-only `event` table.
"""
