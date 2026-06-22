# Clarion
> News monitoring that finds the signal

Clarion monitors news sources, classifies new items, and alerts the user when
something important happens.

The active runtime can poll RSS/Atom feeds and publisher news sitemaps, ingest
the Bluesky firehose, and materialize large source lists from the Media Cloud
catalog. Incoming items flow through a classifier and appear in a live web
dashboard. Important items can trigger Telegram notifications.

Classification criteria are plain-English notes you control.

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

You'll be asked for:
- **OpenAI API key** (required) — from
  [platform.openai.com](https://platform.openai.com/api-keys)
- **Telegram bot** (optional) — create one via
  [`@BotFather`](https://t.me/BotFather), paste the token + bot username
- **Monitoring preferences** — poll interval, max lookback hours

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
