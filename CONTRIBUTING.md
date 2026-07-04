# Contributing to Clarion

## Setup

Follow the installation instructions in README.md to set up your development environment.

Track TODOs, bugs, and priorities in `DEVELOPMENT.md`.

## Code map

The codebase is organized by domain (July 2026 restructure):

```
src/clarion/
    config.py  logging.py  timeutils.py   # cross-cutting, flat at the root
    db/          # pool, schema.sql, migrate, stores/ (one query module per aggregate)
    ingest/      # collector: supervisor, batched event writer, sources/ (stream framework)
    digest/      # daily story clustering: builder, cluster, embedder
    catalog/     # Media Cloud catalog: sync, discovery, materialize
    cli/         # composition root; each domain registers its own subcommands
    devtools.py  # synthetic firehose
src/clarion_web/ # Flask app: views/ blueprints per surface + sse.py
tests/           # pytest; needs DATABASE_URL for the web-route tests
```

Import rules (enforced by `tests/test_import_boundaries.py`):

- `db` imports nothing from the domain packages.
- Domains (`ingest`, `digest`, `catalog`) import only `db` and the flat
  utilities — never each other, with one sanctioned exception:
  `clarion.ingest.streams` (stream config schemas + registry) is the
  shared stream-type contract, importable by catalog and the web.
- `clarion` never imports `clarion_web`; the web app reaches the rest
  of the system only through `db`, the stream registry, the flat
  utilities, and `digest.text` (dependency-free display helpers).
- DDL for the runtime schema runs only via `clarion.db.migrate`
  (process startup or `clarion db migrate`) — never at connect time.
  The offline catalog tools own the separate `sources` schema and
  apply `catalog/schema.sql` themselves in `catalog.db.open_db()`.

Run the tests with `uv run pytest`.
