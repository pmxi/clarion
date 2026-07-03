"""`clarion catalog ...` — the Media Cloud source catalog."""

from __future__ import annotations

import argparse

from clarion.catalog.materialize import MaterializeFilter, format_plan, materialize
from clarion.config import settings


def cmd_catalog_sync(args: argparse.Namespace) -> None:
    # Lazy: pulls the mediacloud client (dev-group dependency).
    from clarion.catalog.mediacloud_sync import main as sync_main
    raise SystemExit(sync_main(args.args))


def cmd_catalog_discover_sitemaps(args: argparse.Namespace) -> None:
    from clarion.catalog.discover_sitemaps import main as discover_main
    raise SystemExit(discover_main(args.args))


def cmd_catalog_discover_feeds(args: argparse.Namespace) -> None:
    from clarion.catalog.discover_feeds import main as discover_main
    raise SystemExit(discover_main(args.args))


def cmd_catalog_materialize(args: argparse.Namespace) -> None:
    kinds = tuple(args.kind) if args.kind else ("news",)
    # --sitemaps-only and --feeds-only are mutually exclusive shortcuts.
    include_sitemaps = not args.feeds_only
    include_feeds = not args.sitemaps_only
    flt = MaterializeFilter(
        language=args.language,
        country=args.country,
        min_fresh=args.min_fresh,
        limit=args.limit,
        kinds=kinds,
    )
    result = materialize(
        database_url=settings.require_database_url(),
        flt=flt,
        include_sitemaps=include_sitemaps,
        include_feeds=include_feeds,
        dry_run=args.dry_run,
        prune=args.prune,
    )
    print(format_plan(result, dry_run=args.dry_run))


def register(sub: argparse._SubParsersAction) -> None:
    catalog = sub.add_parser(
        "catalog",
        help="Manage the Media Cloud source catalog",
    )
    catalog_sub = catalog.add_subparsers(dest="catalog_cmd", required=True)

    for cmd_name, cmd_func, cmd_help in (
        ("sync", cmd_catalog_sync, "Sync the Media Cloud publisher catalog"),
        ("discover-sitemaps", cmd_catalog_discover_sitemaps,
         "Walk publisher sitemaps into sources.source_sitemap"),
        ("discover-feeds", cmd_catalog_discover_feeds,
         "Walk publisher homepages for RSS feeds into sources.source_feed"),
    ):
        passthrough = catalog_sub.add_parser(
            cmd_name,
            help=cmd_help + " (flags are forwarded to the underlying tool)",
        )
        passthrough.add_argument("args", nargs=argparse.REMAINDER)
        passthrough.set_defaults(func=cmd_func, passthrough=True)

    mat = catalog_sub.add_parser(
        "materialize",
        help="Materialize catalog sitemaps into sitemap_news streams",
    )
    mat.add_argument("--language", help="Filter sources by primary_language (e.g. 'en')")
    mat.add_argument("--country", help="Filter sources by pub_country (e.g. 'USA')")
    mat.add_argument(
        "--min-fresh", type=int, default=1,
        help="Minimum fresh_entries_24h for sitemap candidates (default 1)",
    )
    mat.add_argument(
        "--limit", type=int, default=10,
        help="Max candidates *per source kind* to materialize (default 10). "
             "With both sitemaps and feeds enabled, the actual stream count "
             "can be up to 2x this.",
    )
    mat.add_argument(
        "--kind",
        action="append",
        default=None,
        help="source_sitemaps.kind to include (repeatable; default: news)",
    )
    sf = mat.add_mutually_exclusive_group()
    sf.add_argument(
        "--sitemaps-only", action="store_true",
        help="Only materialize sitemap_news streams from source_sitemaps",
    )
    sf.add_argument(
        "--feeds-only", action="store_true",
        help="Only materialize rss streams from source_feeds",
    )
    mat.add_argument("--dry-run", action="store_true", help="Print plan without writing")
    mat.add_argument(
        "--prune",
        action="store_true",
        help="Delete src:* / src-feed:* streams no longer matching the filter",
    )
    mat.set_defaults(func=cmd_catalog_materialize, kind=None)
