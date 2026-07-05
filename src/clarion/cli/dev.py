"""`clarion dev ...` — developer helpers."""

from __future__ import annotations

import argparse

from clarion.cli.common import database_label
from clarion.config import require_database_url
from clarion.devtools import FirehoseConfig, run_firehose


def cmd_dev_firehose(args: argparse.Namespace) -> None:
    count = None if args.count == 0 else args.count
    config = FirehoseConfig(
        rate=args.rate,
        count=count,
        source_type=args.source_type,
        stream_name=args.stream_name,
    )
    target = "until interrupted" if count is None else f"for {count} items"
    print(
        f"Emitting synthetic {config.source_type} traffic into {database_label()} "
        f"at {config.rate:.2f} items/sec {target}. Press Ctrl-C to stop."
    )
    try:
        emitted = run_firehose(require_database_url(), config)
    except KeyboardInterrupt:
        print("\nStopped.")
        return
    print(f"Emitted {emitted} synthetic item(s).")


def register(sub: argparse._SubParsersAction) -> None:
    dev = sub.add_parser("dev", help="Developer helpers for local testing")
    dev_sub = dev.add_subparsers(dest="dev_cmd", required=True)

    firehose = dev_sub.add_parser(
        "firehose",
        help="Emit synthetic dashboard traffic into the local database",
    )
    firehose.add_argument(
        "--rate",
        type=float,
        default=20.0,
        help="Synthetic items per second (default: 20)",
    )
    firehose.add_argument(
        "--count",
        type=int,
        default=200,
        help="How many items to emit; use 0 to run until interrupted (default: 200)",
    )
    firehose.add_argument(
        "--source-type",
        default="rss",
        help="Source label shown in the dashboard (default: rss)",
    )
    firehose.add_argument(
        "--stream-name",
        default="dev-firehose",
        help="Stream label shown in the dashboard (default: dev-firehose)",
    )
    firehose.set_defaults(func=cmd_dev_firehose)
