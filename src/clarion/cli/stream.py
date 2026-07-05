"""`clarion stream ...` — manage configured data streams."""

from __future__ import annotations

import argparse

from clarion.cli.common import open_pool, prompt
from clarion.db.stores import streams as streams_store
from clarion.ingest.streams import all_specs, build_config_json, describe_stream_rows


def cmd_stream_list(_args: argparse.Namespace) -> None:
    with open_pool().connection() as conn:
        rows = describe_stream_rows(streams_store.list_all(conn))
    if not rows:
        print("No streams configured. Run 'clarion stream add --type rss'.")
        return
    for row in rows:
        status = "enabled" if row["enabled"] else "disabled"
        detail = row["error"] or row["detail"]
        print(f"  {row['name']:20s} {row['source_type']:8s} ({status})  {detail}")


def cmd_stream_remove(args: argparse.Namespace) -> None:
    with open_pool().connection() as conn:
        streams_store.delete(conn, args.name)
    print(f"Removed stream {args.name!r}")


def cmd_stream_add(args: argparse.Namespace) -> None:
    types = sorted(all_specs())
    source_type = args.type
    if not source_type:
        print("Stream types: " + "  ".join(f"({i}) {t}" for i, t in enumerate(types, 1)))
        choice = prompt("Choose stream type", default="1").lower()
        source_type = dict(enumerate(types, 1)).get(int(choice) if choice.isdigit() else 0, choice)
    if source_type not in types:
        raise SystemExit(f"Unknown stream type: {source_type!r}")

    name = prompt("Stream name (e.g. 'personal', 'hn-frontpage')")
    if not name:
        raise SystemExit("Stream name is required.")

    raw = {
        field.name: prompt(field.label, default=field.default)
        for field in all_specs()[source_type].form_fields
    }
    try:
        config_json = build_config_json(source_type, raw)
    except ValueError as exc:
        raise SystemExit(f"Invalid config: {exc}") from exc

    with open_pool().connection() as conn:
        streams_store.add(conn, name, source_type, config_json)
    print(f"\nAdded stream {name!r} (type={source_type}).")


def register(sub: argparse._SubParsersAction) -> None:
    stream = sub.add_parser("stream", help="Manage data streams")
    stream_sub = stream.add_subparsers(dest="stream_cmd", required=True)

    stream_sub.add_parser("list").set_defaults(func=cmd_stream_list)

    add = stream_sub.add_parser("add")
    add.add_argument("--type", choices=sorted(all_specs()), help="Stream type")
    add.set_defaults(func=cmd_stream_add)

    rm = stream_sub.add_parser("remove")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_stream_remove)
