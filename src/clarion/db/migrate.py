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


def ensure_schema(conn: psycopg.Connection[DictRow]) -> None:
    conn.execute(SCHEMA_PATH.read_bytes())
