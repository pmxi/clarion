# Deployment

Clarion's single live deployment runs on **`oracle`** — an Ubuntu host
reachable as the SSH alias `oracle` from a maintainer's laptop. Postgres
runs natively on the same host. Everything below assumes you have SSH
access to that host as `ubuntu`.

## Where things live on oracle

| Path | What |
|---|---|
| `/home/ubuntu/clarion` | Git checkout (tracks `origin/master`) |
| `/home/ubuntu/clarion/.venv` | uv-managed venv; `clarion` console script lives here |
| `/home/ubuntu/.config/clarion/clarion.env` | Runtime env — holds `DATABASE_URL` (chmod 600, never check in) |
| `/home/ubuntu/.config/systemd/user/clarion.service` | systemd user unit — collector (`clarion run`) |
| `/home/ubuntu/.config/systemd/user/clarion-web.service` | systemd user unit — web UI (`clarion-web`) |
| `/var/log/postgresql/postgresql-*.log` | Postgres logs (root/postgres reads) |
| `/tmp/clarion-discovery/*.log` | Output of ad-hoc discovery walks (`discover_sitemaps`, `discover_feeds`) |

The web UI listens on **`127.0.0.1:8766`** — bound to localhost only.
Reach it from your laptop via an SSH tunnel (below). Port/host are
configurable via `CLARION_WEB_PORT` / `CLARION_WEB_HOST`. (Port 8765 on
oracle belongs to the **unrelated** `email_sentinel` app — `sentinel-web`
+ `sentinel-worker`, a separate product, separate DB. Do not touch it.)

## systemd units

The collector and the web UI are now **separate processes**, so they run as
two user-scoped units (`systemctl --user`, as the `ubuntu` user).

`~/.config/systemd/user/clarion.service` — the collector:

```ini
[Service]
Type=simple
WorkingDirectory=/home/ubuntu/clarion
EnvironmentFile=/home/ubuntu/.config/clarion/clarion.env
ExecStart=/home/ubuntu/clarion/.venv/bin/clarion run
Restart=always
RestartSec=5
LimitNOFILE=131072
MemoryHigh=3G
MemoryMax=4G
```

`~/.config/systemd/user/clarion-web.service` — the web UI:

```ini
[Service]
Type=simple
WorkingDirectory=/home/ubuntu/clarion
EnvironmentFile=/home/ubuntu/.config/clarion/clarion.env
Environment=CLARION_WEB_PORT=8766
ExecStart=/home/ubuntu/clarion/.venv/bin/clarion-web
Restart=always
RestartSec=5
```

`MemoryMax=4G` on the collector is a guardrail — under sustained ingest the
process slowly grows memory; systemd OOM-kills past 4G and `Restart=always`
brings it back. Per-stream `_seen` sets are in-memory only and rebuild on
first poll after a restart. The web UI is lightweight (stateless reads) and
needs no memory cap.

## Postgres

Runs natively on oracle, listens on `localhost:5432`. Version 18.3.

- Database: `clarion`
- Owner role used by the app: `clarion_user`
- `postgres` superuser available via `sudo -nu postgres psql`
- The schema lives in two namespaces: `public` (runtime) and `sources` (Media Cloud catalog).

`DATABASE_URL` in the env file points at `postgresql://clarion_user:...@localhost:5432/clarion`.

## Reaching the web UI from your laptop

```bash
# Open SSH tunnel — leaves running in background
ssh -fN -L 8766:localhost:8766 oracle

# Open in browser
open http://127.0.0.1:8766/
```

For postgres access (e.g. running a CLI like `clarion sources
materialize` from your laptop) tunnel 5433 -> 5432 since 5432 is
usually taken locally:

```bash
ssh -fN -L 5433:localhost:5432 oracle

# Then export a tunnel-aware DATABASE_URL for one-off commands
export DATABASE_URL='postgresql://clarion_user:<pw>@localhost:5433/clarion'
```

To close a tunnel: `pkill -f 'ssh -fN -L 8766'` (or the matching port).

## Web routes

| Path | What |
|---|---|
| `/` | Original dashboard (status + 2-column live feed). |
| `/live` | Multi-source live monitor with sidebar (filter by source type + top stream), full-text search, rate counters. |
| `/streams` | Stream-row management — search/filter/paginate; toggle/delete. |
| `/streams/activity` | Per-stream emission rates over a recent window. |
| `/streams/new` | Manually add a stream. |
| `/events/stream` | SSE feed used by `/`, `/live`. |

## Common management operations

All run **on oracle** (`ssh oracle` first). These target the collector
(`clarion.service`); the web UI is managed identically via
`clarion-web.service`.

```bash
# Status / health
systemctl --user status clarion.service
systemctl --user show clarion.service -p ActiveState,MainPID,MemoryCurrent

# Follow logs
journalctl --user -u clarion.service -f
journalctl --user -u clarion.service --since "5 minutes ago"

# Restart (picks up new code + systemd unit changes after daemon-reload)
systemctl --user restart clarion.service

# Stop / start
systemctl --user stop clarion.service
systemctl --user start clarion.service

# Apply a unit file change
systemctl --user daemon-reload
systemctl --user restart clarion.service
```

### Standard deploy

`/home/ubuntu/clarion` is a git checkout of `origin/master` with an editable
install (`uv sync`) into `.venv`. `.venv/`, `logs/`, and the env file (which
lives outside the tree, under `~/.config/clarion/`) are untracked, so a hard
reset is safe.

```bash
ssh oracle '
  cd /home/ubuntu/clarion \
    && git fetch origin master \
    && git reset --hard origin/master \
    && ~/.local/bin/uv sync --frozen \
    && systemctl --user restart clarion.service clarion-web.service'
```

`uv sync` is needed whenever dependencies or entry points change; for a
pure code edit a restart alone suffices (the install is editable).
Hot-reload picks up `stream` table changes within 30s without a restart.

### Verifying after a deploy

```bash
ssh oracle '
  systemctl --user show clarion.service -p ActiveState,MainPID
  journalctl --user -u clarion.service --since "30 seconds ago" --no-pager \
    | grep -E "ERROR|Traceback|Supervising"
  curl -sS -o /dev/null -w "/ HTTP %{http_code}\n" http://127.0.0.1:8766/'
```

## Database schema

The runtime schema is in **`src/clarion/local/schema.sql`** (applied
idempotently at every supervisor startup via
`LocalDatabase._create_tables`). The catalog schema lives in
**`tools/sources/schema.sql`** (applied by the catalog tools).

All tables use **singular names** as of the May-2026 migration.

### `public` — runtime

| Table | Purpose |
|---|---|
| `event` | One row per observed item. `UNIQUE (source_type, item_id)` is also the dedup ledger. `body` is nullable when redundant with `title`. Carries `received_at` (publisher) and `observed_at` (clarion). |
| `classification`, `classification_failure` | **Legacy** — retained for the historical data classified before classification was removed. No longer written to. |
| `stream` | Streams the supervisor polls. `config_json` is JSONB. |
| `app_setting`, `local_setting` | Key-value config. |
| `monitoring_state` | Collector heartbeats (`monitoring_start_time`, `last_check_time`). |
| `telegram_link_token` | **Legacy** — unused since Telegram notifications were removed. |
| `schema_meta` | Schema-version pointer. |

### `sources` — Media Cloud catalog

| Table | Purpose |
|---|---|
| `source` | ~1M publishers (id from MC, canonical_domain, stories_per_week, language, country). |
| `collection`, `source_collection` | MC topic groupings (membership empty in v1). |
| `source_sitemap` | Discovered Google News sitemaps (`kind` ∈ news/index/urlset/...). |
| `source_feed` | Validated RSS/Atom feeds per source. |
| `sync_run`, `discovery_run`, `feed_discovery_run` | Audit trail rows for the catalog/discovery tools. |

### Running a migration

DDL lives in checked-in SQL. For destructive or one-shot migrations,
add a file under `tools/` and run it as the postgres superuser:

```bash
ssh oracle 'sudo -nu postgres psql -d clarion -v ON_ERROR_STOP=1 -f tools/your_migration.sql'
```

**Footgun:** if you run the migration as `postgres` and it creates new
tables, those tables are owned by `postgres` and the `clarion_user`
role can't run `CREATE INDEX IF NOT EXISTS` against them at supervisor
startup. After any migration that creates tables, fix ownership:

```sql
ALTER TABLE <newtable> OWNER TO clarion_user;
```

This bit us during the singular-names migration; the
`tools/migrate_to_singular_schema.sql` file is still in the tree as
reference but isn't meant to re-run.

## Adding scraping coverage

```bash
# 1. (Once / occasionally) refresh the Media Cloud catalog
MEDIACLOUD_API_KEY=... uv run python -m tools.sources.mediacloud_sync

# 2. Walk publisher sitemaps to populate sources.source_sitemap
uv run python -m tools.sources.discover_sitemaps --limit 10000 --min-spw 100 --concurrency 100

# 3. Walk homepages for RSS feeds — populates sources.source_feed
uv run python -m tools.sources.discover_feeds --limit 10000 --min-spw 100 --concurrency 100

# 4. Turn catalog rows into runtime streams (idempotent)
uv run clarion sources materialize --limit 500 --min-fresh 50
uv run clarion sources materialize --feeds-only --limit 200

# Optional: drop materialized streams no longer matching a filter
uv run clarion sources materialize --limit 100 --prune
```

The supervisor's hot-reload picks up new `stream` rows within 30s — no
restart needed. `src:*` stream names come from sitemap materialization;
`src-feed:*` come from feed materialization. The `--prune` flag only
touches those prefixes.

## Things that need watching

| | |
|---|---|
| Memory drift | Slow growth under sustained ingest — `MemoryMax=4G` + `Restart=always` is the current backstop. Restarts cost 5min of re-priming (sitemap streams skip first-poll emission). |
| `event` size | **Append-only and kept indefinitely — there is no prune.** Grows ~150–200 MB/day (~236k rows/day) at current load. Watch disk on oracle and manage capacity at the infra level (bigger volume, table partitioning, archiving). Do **not** add a time-based prune to trim it. |
| Long tail of streams | The single-process asyncio supervisor handles ~750-1500 streams comfortably. Beyond that, CPU pegs and memory grows. Going wider needs a worker-pool refactor. |
| Postgres backups | Not yet wired up — and now load-bearing: `event` is append-only and kept indefinitely, so its full history is **irreplaceable** if the DB is lost. The `sources.*` catalog is re-derivable from Media Cloud (hours to re-walk); `stream` and `app_setting` are also irreplaceable. Wiring up backups is a real TODO. |

## Catalog re-walk cost

For reference if you ever blow away the catalog:

| Step | Wall time | API cost |
|---|---|---|
| `mediacloud_sync` (1M sources + 1.7k collections) | ~2 hours | ~213 MC API hits |
| `discover_sitemaps --limit 10000` | ~15 min | none (publisher HTTP) |
| `discover_feeds --limit 10000` | ~10 min | none unless `--mediacloud-fallback` |
| `sources materialize` (whatever filter) | ~30 sec | none |

## Quick `psql` recipes

```bash
ssh oracle 'sudo -nu postgres psql -d clarion'

-- Live system snapshot
SELECT
  (SELECT COUNT(*) FROM event)              AS events,
  (SELECT COUNT(*) FROM stream)             AS streams,
  (SELECT MAX(observed_at) FROM event)      AS most_recent;

-- Recent throughput
SELECT source_type, COUNT(*) AS n,
       MIN(observed_at) AS first, MAX(observed_at) AS last
FROM event
WHERE observed_at > NOW() - INTERVAL '5 minutes'
GROUP BY 1 ORDER BY 2 DESC;

-- Active streams (something arrived in last 10 min)
SELECT stream_name, COUNT(*) AS items
FROM event
WHERE observed_at > NOW() - INTERVAL '10 minutes'
GROUP BY 1 ORDER BY 2 DESC LIMIT 20;

-- Most recent items
SELECT source_type, stream_name, title, url, observed_at
FROM event
ORDER BY observed_at DESC LIMIT 20;
```
