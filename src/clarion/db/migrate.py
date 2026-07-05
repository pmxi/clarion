"""Schema application — the only place DDL runs.

Called once per process startup (collector, web, CLI) via
db.open_pool_with_schema. Connection-time DDL (the old LocalDatabase
applied schema.sql on every instantiation, i.e. every web request) is
gone.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
from psycopg.rows import DictRow

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
SCHEMA_VERSION = 5


def ensure_schema(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute(SCHEMA_PATH.read_bytes())
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', %s) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
