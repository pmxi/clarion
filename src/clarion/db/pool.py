"""Process-wide psycopg connection pool.

Every process (collector, web, CLI) opens one pool at startup and checks
connections out per unit of work. `check=check_connection` revalidates a
connection on checkout, so a dropped SSH tunnel or Postgres restart heals
on the next request instead of poisoning the pool.

Long-lived consumers that would otherwise starve the pool (the dev
firehose holds one for its whole run) use `raw_connection()` — a
dedicated connection outside the pool.
"""

from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

# Every clarion connection uses dict rows; annotations share these aliases.
DictConnection = psycopg.Connection[DictRow]
DictConnectionPool = ConnectionPool[DictConnection]

_pool: Optional[DictConnectionPool] = None
_lock = threading.Lock()


def open_pool(database_url: str, *, min_size: int = 1, max_size: int = 8) -> DictConnectionPool:
    """Open (or return) the process-wide pool. Idempotent."""
    global _pool
    with _lock:
        if _pool is None:
            _pool = DictConnectionPool(
                database_url,
                min_size=min_size,
                max_size=max_size,
                kwargs={"row_factory": dict_row, "autocommit": True},
                check=DictConnectionPool.check_connection,
                name="clarion",
                open=True,
            )
            # Pool worker threads must be joined before interpreter
            # shutdown or Python 3.14 raises PythonFinalizationError.
            atexit.register(close_pool)
    return _pool


def get_pool() -> DictConnectionPool:
    pool = _pool
    if pool is None:
        raise RuntimeError("connection pool not opened; call db.pool.open_pool() at startup")
    return pool


@contextmanager
def connection() -> Iterator[DictConnection]:
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def raw_connection(database_url: str) -> DictConnection:
    """A dedicated autocommit connection outside the pool."""
    conn = psycopg.Connection[DictRow].connect(database_url, row_factory=dict_row)
    conn.autocommit = True
    return conn
