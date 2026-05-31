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
uv run clarion stream add --type bluesky        # Bluesky firehose
```

For RSS, paste the feed URL and a poll interval. The source catalog can also
materialize sitemap and RSS streams in bulk:

```bash
uv run clarion sources materialize --limit 500 --min-fresh 50
```

You can add RSS streams through the web UI once it is running.

### 3. Run the monitor

```bash
uv run clarion web
```

This is the one command you need. `clarion web` runs the supervisor
in-process alongside the Flask app, so there's no second daemon to manage.
Open `http://127.0.0.1:8765`. No login required. From there you can:
- Watch the live feed as items arrive and get classified in real time
- See daemon status and recently-processed items
- Add RSS streams and disable or delete configured streams
- Edit your classification notes (appended to the LLM prompt every time)
- Link your Telegram chat in one click

For a purely headless deployment (no web UI), `clarion run` spawns just
the supervisor. Don't run both at once — you'll get two supervisors and
duplicate notifications.

For UI load testing, you do not need to wait on real RSS publishers. Emit a
synthetic firehose straight into the local database:

```bash
uv run clarion dev firehose --rate 20 --count 200
```

This produces `item_received` and `item_classified` events that the
dashboard renders the same way as real traffic. Use `--count 0` to run until
you stop it.

## Configuration

Clarion uses PostgreSQL for the active single-user runtime. Configure it with
`DATABASE_URL`:

```bash
export DATABASE_URL=postgresql://clarion_user:REDACTED@localhost:5433/clarion
```

---

## Multi-tenant runtime

The repo also includes a separate multi-tenant runtime (`clarion-hosted`)
with Google OAuth, per-user storage, and a worker/web split. It is **not in
active development** — use the single-user setup above unless you have a
reason to dig into the hosted code.
