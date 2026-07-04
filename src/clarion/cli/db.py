"""`clarion db ...` — schema administration."""

from __future__ import annotations

import argparse

from clarion.cli.common import open_pool
from clarion.db.migrate import ensure_schema


def cmd_db_migrate(_args: argparse.Namespace) -> None:
    with open_pool().connection() as conn:
        ensure_schema(conn)
    print("Schema is up to date.")


def register(sub: argparse._SubParsersAction) -> None:
    db = sub.add_parser("db", help="Database administration")
    db_sub = db.add_subparsers(dest="db_cmd", required=True)
    db_sub.add_parser(
        "migrate", help="Apply schema.sql idempotently"
    ).set_defaults(func=cmd_db_migrate)
