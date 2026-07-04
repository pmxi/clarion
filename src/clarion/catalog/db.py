"""Postgres store for the Media Cloud source catalog (schema `sources`)."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import DictRow, dict_row

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DATABASE_URL_ENV = "DATABASE_URL"


def open_db(database_url: str | None = None) -> psycopg.Connection[DictRow]:
    url = database_url or os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise RuntimeError(
            f"set {DATABASE_URL_ENV} to the clarion postgres connection string"
        )
    conn = psycopg.Connection[DictRow].connect(url, row_factory=dict_row)
    conn.autocommit = True
    conn.execute(SCHEMA_PATH.read_bytes())
    conn.execute("SET search_path TO sources, public")
    return conn
