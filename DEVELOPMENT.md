# TODO

## Digest (daily story aggregation)
- Deploy the digest job on oracle: `uv sync --frozen --extra digest` +
  the `clarion-digest.timer` unit (recipe in DEPLOYMENT.md). Benchmark
  embedding throughput on the ARM CPU first — a 200k-article day may
  take hours there (~25 min on an M-series laptop).
- Cross-language story merging: at threshold 0.92 the same story in
  different languages usually lands in separate clusters, so a global
  story shows up once per language. Options: second-pass merge of
  cluster centroids at a lower threshold, or rank/display by combined
  coverage.
- Wire-syndication inflation: aol.com/yahoo.com republications count as
  distinct sources. Fine as a coverage signal, but consider collapsing
  known mirror domains.
- Known cluster-quality limits at full-day scale (all title-only
  embedding artifacts, acceptable for now):
  - topical blobs: "NBA offseason moves" style clusters (~700 articles)
    where many related-but-distinct stories share one cluster;
  - template events: near-identical headlines about different events
    ("fire extinguished in <town>") cluster together;
  - small-language blobs: for less-represented languages (sr, te, ta)
    the embedding space is less separated and unrelated stories merge.
  A cheap lever if these annoy: store mean member-to-centroid
  similarity per story and downrank/split low-coherence giants.
- The digest ranks by coverage breadth only. Consider a "significance"
  signal that isn't engagement-shaped (e.g. front-page placement,
  cross-language spread).
- Embedding caches in `artifacts/` grow ~300 MB/day (float16); prune
  automatically after a day closes.
- Consider making `/` the digest page once it's proven — the product is
  the digest, the dashboard is ops.

## Data sources
- Figure out X (Twitter) scraping — the most valuable source we haven't unlocked.
- Figure out Instagram scraping.

## Architecture follow-ups
- Stand up a read API (cursor feed over `event.id` + filtered query + search)
  so aggregator apps stop depending on direct Postgres access. Today
  `clarion_web` reads Postgres directly — the deliberate "shared Postgres now,
  API later" call.
- Migrate the live `oracle` deployment off the legacy Sentinel names: checkout
  path, the now-two systemd units (`clarion` + `clarion-web`), environment
  path, Postgres database, and Postgres role.
- Drop the now-unused `event.score` column **after** the next oracle deploy
  (the currently-deployed collector still names it in INSERTs; new code
  doesn't reference it).
- Next deploy needs `uv sync` (new runtime dep: psycopg-pool). Entry
  points and systemd units are unchanged.
- Next deploy also applies the v5 vocabulary renames at startup
  (`stream.stream_type`→`source_type`, `story.article_count`→`event_count`,
  `story_article`→`story_event`, `sources.discovery_run`→
  `sitemap_discovery_run`). The renames happen the moment new code first
  touches the DB, and old code can't read the renamed columns — so update
  and restart the collector and web units together, not one at a time.
  `clarion digest build --min-articles` is now `--min-events`.
- Wire up Postgres backups (see DEPLOYMENT "Things that need watching") —
  the event log is irreplaceable and lives on one VM disk. Highest-risk
  open item.
- Serve clarion-web with a real WSGI server (gunicorn/waitress) instead
  of the Flask dev server; size the thread pool for SSE clients.
- Reconsider first-poll suppression in the streams: it predates the
  classifier's removal, and today it silently drops anything published
  while the collector was down. The event table's dedup constraint makes
  re-emission harmless. Better: persisted per-stream cursors + HTTP
  conditional GET.
- Failure alerting: a healthchecks.io-style ping (or systemd OnFailure →
  push) so a dead collector isn't silent data loss.

## Future
- If newsworthiness ranking is wanted again, reintroduce ML scoring /
  classification as a **separate** concern/service (was: logistic regression
  -> local LLM -> API LLM). It was removed from the collector when Clarion
  narrowed to pure news collection.

## Notes
- Postgres lives on the `oracle` SSH host: `ssh -L 5433:localhost:5432 oracle`.
