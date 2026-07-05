# Clarion
> News monitoring that finds the signal

Clarion solves information overload: it collects news at scale, then
aggregates each day's articles into a ranked digest of stories. Ranking is
by breadth of coverage (how many distinct publications wrote about it) —
a neutral editorial signal, not engagement.

The active runtime polls RSS/Atom feeds and publisher news sitemaps, and
materializes large source lists from the Media Cloud catalog. Incoming items
are written to Postgres as an append-only event log.

It is split into processes that share only the Postgres database:
- **`clarion`** — the headless collector (one task per stream).
- **`clarion digest build`** — a batch job that clusters one day's articles
  into stories (multilingual title embeddings + cosine clustering).
- **`clarion-web`** — a reader for the daily digest.

## Installation

Tested with Python 3.14.2 on macOS. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/), then sync
dependencies:

```bash
uv sync
```

---

## Quick start

The only setup is `DATABASE_URL` (see [Configuration](#configuration));
every command creates the schema itself on first contact with a fresh
database. Single-user; there is no app-level login.

### 1. Add a stream

```bash
uv run clarion stream add --type rss            # any RSS or Atom feed
uv run clarion stream add --type sitemap_news   # publisher news sitemap
```

For RSS, paste the feed URL and a poll interval. The source catalog can also
materialize sitemap and RSS streams in bulk:

```bash
uv run clarion catalog materialize --limit 500 --min-fresh 50
```

### 2. Run the collector

```bash
uv run clarion run
```

This starts the supervisor: one task per enabled stream, writing every
item into the append-only `event` table. It is headless — check on it
any time with `clarion status` (stream count, event total, heartbeat).

### 3. Build the daily digest

```bash
uv sync --extra digest     # once: pulls torch + sentence-transformers
uv run clarion digest build --day yesterday
```

This clusters one UTC day's articles into stories: titles are embedded
with a multilingual encoder (EmbeddingGemma-300m by default), grouped by
cosine similarity, and ranked by how many distinct publications covered
them. Results land in the `story` / `story_event` tables; rebuilding a
day is idempotent. Use `--dry-run` to preview the top clusters in the
terminal, and `--day today` to rebuild the current day as it grows.

### 4. Read the digest (separate process)

```bash
uv run clarion-web
```

The digest reader is a separate process that reads the same Postgres
database. It does one thing: serve each day's stories as a page of cards —
ranked by breadth of coverage, with distinct member headlines under each
story. Open `http://127.0.0.1:8766`. No login; it binds to localhost.
Everything else (streams, collector, digest builds) is operated through
the `clarion` CLI.

For local testing without real RSS publishers, emit a synthetic firehose
straight into the database, then build a digest from it:

```bash
uv run clarion dev firehose --rate 20 --count 200
```

Use `--count 0` to run until you stop it.

## Configuration

Clarion uses PostgreSQL for the active single-user runtime. Configure it with
`DATABASE_URL`:

```bash
export DATABASE_URL=postgresql://clarion_user:REDACTED@localhost:5433/clarion
```
