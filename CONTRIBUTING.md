Linter:
uv run ruff check
Type check:
uv run ty check
Tests:
uv run pytest

## Code map

```
src/clarion/
    config.py  logging.py  timeutils.py   # cross-cutting, flat at the root
    db/          # pool, schema.sql, migrate, stores/ (one query module per aggregate)
    ingest/      # collector: supervisor, generic poll loop (poll.py), batched
                 # event writer, streams/ (Item contract + one module per source type)
    digest/      # daily story clustering: builder, cluster, embedder
    catalog/     # Media Cloud catalog: sync, discovery, materialize
    cli/         # composition root; each domain registers its own subcommands
    devtools.py  # synthetic firehose
    web/         # the digest reader (Flask, two routes)
tests/           # pytest; pure — no Postgres, network, or torch required
```

A stream type is a pydantic config model plus an async fetch function,
registered in `ingest/streams/registry.py`'s `SPECS` dict. The generic
poll loop (`ingest/poll.py`) owns everything around the fetch: dedup,
first-poll priming, error handling, cadence.

Import rules (enforced by `tests/test_import_boundaries.py`): `db`
imports no domain; domains never import each other except the shared
`clarion.ingest.streams` contract; the web app touches only `config`,
`db`, and `digest.text`; runtime DDL runs only through
`db.open_pool_with_schema` at process startup.
