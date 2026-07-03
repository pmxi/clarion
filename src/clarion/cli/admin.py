"""`clarion init` and `clarion db ...` — setup and schema administration."""

from __future__ import annotations

import argparse

from clarion.cli.common import open_pool
from clarion.config import settings
from clarion.db.migrate import ensure_schema
from clarion.db.stores import settings as settings_store


def cmd_init(_args: argparse.Namespace) -> None:
    import secrets

    with open_pool().connection() as conn:
        ensure_schema(conn)
        settings.load(conn)
        if not settings_store.get(conn, "SESSION_SECRET"):
            settings_store.set(conn, "SESSION_SECRET", secrets.token_hex(32))
    print("\nSetup complete.")
    print("  - Add an RSS feed: clarion stream add --type rss")
    print("  - Start collector: clarion run")
    print("  - Open web UI:     clarion-web")
    print("  - Drive test load: clarion dev firehose --rate 20 --count 200")


def cmd_db_migrate(_args: argparse.Namespace) -> None:
    with open_pool().connection() as conn:
        ensure_schema(conn)
    print("Schema is up to date.")


def register(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("init", help="Configure the runtime").set_defaults(func=cmd_init)

    db = sub.add_parser("db", help="Database administration")
    db_sub = db.add_subparsers(dest="db_cmd", required=True)
    db_sub.add_parser(
        "migrate", help="Apply schema.sql idempotently"
    ).set_defaults(func=cmd_db_migrate)
