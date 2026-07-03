"""Database access: connection pool, schema application, per-domain stores.

Rules:
- `db` imports nothing from the domain packages (ingest, digest, catalog).
- DDL runs only through `migrate.ensure_schema()` — once per process
  startup or via `clarion db migrate` — never at connect time.
- Stores are plain functions taking a psycopg Connection; callers manage
  checkout via `pool.connection()`.
"""
