"""Ingest: the collection domain.

`supervisor` runs one task per enabled stream; `poll` is the generic
poll loop; `streams` holds the stream contract (Item, config + fetch
specs) and the built-in RSS + news-sitemap types; `writer` batches
emitted items into the append-only `event` table.
"""
