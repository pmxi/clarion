"""Database access: connection pool, schema application, per-domain stores.

Rules:
- `db` imports nothing from the domain packages (ingest, digest, catalog).
- DDL runs only through `migrate.ensure_schema()` — once per process
  startup or via `clarion db migrate` — never at connect time.
- Stores are plain functions taking a psycopg Connection; callers manage
  checkout via `pool.connection()`.
"""

from clarion.db import migrate as _migrate
from clarion.db import pool as _pool


def open_pool_with_schema(database_url: str) -> _pool.DictConnectionPool:
    """The standard process-startup preamble: open the process-wide pool
    and apply the schema. Every long-running entry point (collector, web,
    `clarion db migrate`) goes through here."""
    pool = _pool.open_pool(database_url)
    with pool.connection() as conn:
        _migrate.ensure_schema(conn)
    return pool
