# Clarion
> News monitoring that finds the signal

Clarion collects news at scale and stores it in an append-only event log.

The active runtime polls RSS/Atom feeds and publisher news sitemaps, and
materializes large source lists from the Media Cloud catalog. Incoming items
are written to Postgres and appear in a live web dashboard.

It is split into two processes that share only the Postgres database:
- **`clarion`** — the headless collector (one task per stream).
- **`clarion-web`** — a separate web UI / control plane that reads the data
  and manages stream config.

## Installation

Tested with Python 3.14.2 on macOS. Install
[uv](https://docs.astral.sh/uv/getting-started/installation/), then sync
dependencies:

```bash
uv sync
```

---

## Quick start

### 1. Configure operator-level settings

```bash
uv run clarion init
```

This initializes runtime settings in the database (e.g. a web session
secret). The only thing you must provide yourself is `DATABASE_URL` (see
[Configuration](#configuration)).

Single-user; there is no app-level login.

### 2. Add a stream

```bash
uv run clarion stream add --type rss            # any RSS or Atom feed
uv run clarion stream add --type sitemap_news   # publisher news sitemap
```

For RSS, paste the feed URL and a poll interval. The source catalog can also
materialize sitemap and RSS streams in bulk:

```bash
uv run clarion sources materialize --limit 500 --min-fresh 50
```

You can add RSS streams through the web UI once it is running.

### 3. Run the collector

```bash
uv run clarion run
```

This starts the supervisor: one task per enabled stream, writing every
item into the append-only `event` table. It is headless — no web UI.

### 4. Open the web UI (separate process)

```bash
uv run clarion-web
```

The web UI is a separate process that reads the same Postgres database and
manages stream config. It does **not** collect anything itself — run
`clarion run` for that. Open `http://127.0.0.1:8765`. No login required.
From there you can:
- Watch the live feed as items arrive in real time
- See collector status and recently-collected items
- Add RSS streams and disable or delete configured streams

For UI load testing, you do not need to wait on real RSS publishers. Emit a
synthetic firehose straight into the local database:

```bash
uv run clarion dev firehose --rate 20 --count 200
```

This writes `item_received` events that the dashboard renders the same way
as real traffic. Use `--count 0` to run until you stop it.

## Configuration

Clarion uses PostgreSQL for the active single-user runtime. Configure it with
`DATABASE_URL`:

```bash
export DATABASE_URL=postgresql://clarion_user:REDACTED@localhost:5433/clarion
```
