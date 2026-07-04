"""`clarion run` — start the collector supervisor."""

from __future__ import annotations

import argparse
import asyncio

from clarion.cli.common import open_pool
from clarion.config import settings
from clarion.db.migrate import ensure_schema
from clarion.ingest.supervisor import Supervisor


def cmd_run(_args: argparse.Namespace) -> None:
    pool = open_pool()
    with pool.connection() as conn:
        ensure_schema(conn)
        settings.load(conn)
    asyncio.run(Supervisor(pool).run())


def register(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("run", help="Start the collector supervisor").set_defaults(func=cmd_run)
