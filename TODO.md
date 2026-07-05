# Clarion — vision & roadmap

## Vision

News arrives faster than a person can follow it. Publisher sites, RSS feeds,
news sitemaps, and social platforms all carry fragments of the same evolving
story.

Clarion monitors those sources, surfaces consequential developments quickly,
and suppresses routine noise. The goal: keep up with a large information flow
without watching every feed.

The product is the daily digest. The collector and dashboard exist to feed it.

## Now — protect the data, get the digest into production

The event log is irreplaceable and lives on one VM disk; the digest only
exists on a laptop. Nothing else matters until these are done.

- [ ] Postgres backups on oracle (pg_dump timer + off-VM copy). Highest-risk
  open item.
- [ ] Failure alerting: healthchecks.io-style ping or systemd OnFailure →
  push, so a dead collector isn't silent data loss.
- [ ] Deploy the digest job on oracle: `uv sync --frozen --extra digest` +
  `clarion-digest.timer` (recipe in DEPLOYMENT.md). Benchmark embedding
  throughput on the ARM CPU first — a 200k-article day may take hours
  (~25 min on an M-series laptop).
- [ ] Serve clarion-web with a real WSGI server (gunicorn/waitress); size the
  thread pool for SSE clients.
- [ ] Prune embedding caches in `artifacts/` after a day closes
  (~300 MB/day, float16).

## Next — make the digest trustworthy

Cluster-quality problems that make the ranking lie. All are title-only
embedding artifacts at full-day scale.

- [ ] Cross-language story merging: at threshold 0.92 the same story lands in
  one cluster per language. Second-pass merge of cluster centroids at a lower
  threshold, or rank by combined coverage.
- [ ] Collapse known wire-syndication mirrors (aol.com/yahoo.com
  republications count as distinct sources today).
- [ ] Cluster coherence: store mean member-to-centroid similarity per story;
  downrank or split low-coherence giants. Targets the known failure modes:
  topical blobs (~700-article "NBA offseason" clusters), template events
  ("fire extinguished in <town>"), small-language blobs (sr, te, ta).
- [ ] Make `/` the digest page once it's proven; the dashboard is ops.

## Then — consequential vs. routine (the actual vision)

Breadth of coverage is the only ranking signal today. It's neutral but crude.

- [ ] A "significance" signal that isn't engagement-shaped: front-page
  placement, cross-language spread, coverage velocity.
- [ ] Faster than daily: rebuild the current day on a schedule
  (`--day today` is already idempotent) so big stories surface intraday.
- [ ] Story continuity across days — the vision says "evolving story", but
  every day clusters from scratch. Link a day's stories to yesterday's
  (centroid similarity) so a running story reads as one thread.

## Later — widen intake, open the data

- [ ] X (Twitter) scraping — the most valuable source we haven't unlocked.
- [ ] Instagram scraping.
- [ ] Read API (cursor feed over `event.id` + filtered query + search) so
  aggregator apps stop reading Postgres directly. `clarion.web` reading
  Postgres was the deliberate "shared Postgres now, API later" call.
- [ ] Replace first-poll suppression with persisted per-stream cursors + HTTP
  conditional GET. Today it silently drops anything published while the
  collector was down; the event table's dedup constraint makes re-emission
  harmless.
- [ ] If newsworthiness ranking is wanted again, reintroduce ML scoring as a
  separate service (was: logistic regression → local LLM → API LLM; removed
  when Clarion narrowed to pure collection).
