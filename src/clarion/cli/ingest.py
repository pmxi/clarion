"""`clarion run` and `clarion stream ...` — the collection domain."""

from __future__ import annotations

import argparse
import asyncio

from clarion.cli.common import open_pool, prompt
from clarion.config import settings
from clarion.db.migrate import ensure_schema
from clarion.db.stores import streams as streams_store
from clarion.ingest.streams import describe_stream_rows, get as get_stream_spec
from clarion.ingest.supervisor import Supervisor


def cmd_run(_args: argparse.Namespace) -> None:
    pool = open_pool()
    with pool.connection() as conn:
        ensure_schema(conn)
        settings.load(conn)
    asyncio.run(Supervisor(pool).run())


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
    source_type = args.type
    if not source_type:
        print("Stream types: (1) rss  (2) sitemap_news")
        choice = prompt("Choose stream type", default="1")
        source_type = {
            "1": "rss",
            "2": "sitemap_news",
            "rss": "rss",
            "sitemap_news": "sitemap_news",
        }.get(choice.lower(), "rss")

    name = prompt("Stream name (e.g. 'personal', 'hn-frontpage')")
    if not name:
        raise SystemExit("Stream name is required.")

    if source_type == "rss":
        config_json = _prompt_rss_stream()
    elif source_type == "sitemap_news":
        sitemap_url = prompt("Sitemap URL (e.g. https://www.bloomberg.com/sitemaps/news/latest.xml)")
        publication = prompt("Publication display name", default=name)
        config_json = get_stream_spec("sitemap_news").config_cls(
            sitemap_url=sitemap_url,
            publication_name=publication,
        ).model_dump_json()
    else:
        raise SystemExit(f"Unknown stream type: {source_type!r}")

    with open_pool().connection() as conn:
        streams_store.add(conn, name, source_type, config_json)
    print(f"\nAdded stream {name!r} (type={source_type}).")


def _prompt_rss_stream() -> str:
    feed_url = prompt("Feed URL (RSS or Atom)")
    if not feed_url:
        raise SystemExit("feed_url is required.")
    poll_seconds = int(prompt("Poll interval (seconds)", default="300"))
    config = get_stream_spec("rss").config_cls(feed_url=feed_url, poll_seconds=poll_seconds)
    return config.model_dump_json()


def register(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("run", help="Start the collector supervisor").set_defaults(func=cmd_run)

    stream = sub.add_parser("stream", help="Manage data streams")
    stream_sub = stream.add_subparsers(dest="stream_cmd", required=True)

    stream_sub.add_parser("list").set_defaults(func=cmd_stream_list)

    add = stream_sub.add_parser("add")
    add.add_argument("--type", choices=["rss", "sitemap_news"], help="Stream type")
    add.set_defaults(func=cmd_stream_add)

    rm = stream_sub.add_parser("remove")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_stream_remove)
