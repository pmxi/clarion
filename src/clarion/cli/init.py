"""`clarion init` — first-run setup."""

from __future__ import annotations

import argparse

from clarion.cli.common import open_pool
from clarion.config import settings
from clarion.db.migrate import ensure_schema


def cmd_init(_args: argparse.Namespace) -> None:
    with open_pool().connection() as conn:
        ensure_schema(conn)
        settings.load(conn)
    print("\nSetup complete.")
    print("  - Add an RSS feed:  clarion stream add --type rss")
    print("  - Start collector:  clarion run")
    print("  - Read the digest:  clarion-web")
    print("  - Drive test load:  clarion dev firehose --rate 20 --count 200")


def register(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("init", help="Configure the runtime").set_defaults(func=cmd_init)
