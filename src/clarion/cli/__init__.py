"""Clarion CLI — the composition root that wires every domain together.

One module per top-level command; each contributes its commands via a
register(subparsers) function and this module only assembles the parser
and dispatches.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

from clarion.cli import catalog, db, dev, digest, run, stream
from clarion.db import pool as db_pool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clarion")
    sub = parser.add_subparsers(dest="cmd", required=True)
    db.register(sub)
    run.register(sub)
    stream.register(sub)
    digest.register(sub)
    catalog.register(sub)
    dev.register(sub)
    return parser


def parse_cli(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse argv, forwarding unrecognized flags to passthrough commands
    (the catalog tools own their argparse surfaces)."""
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    if getattr(args, "passthrough", False):
        args.args = list(extra) + list(getattr(args, "args", None) or [])
    elif extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    return args


def main() -> None:
    args = parse_cli()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)
    finally:
        db_pool.close_pool()


if __name__ == "__main__":
    main()
