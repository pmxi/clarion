"""Local Clarion CLI."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Optional

from clarion.core.streams.rss.config import RSSStreamConfig
from clarion.core.streams.sitemap_news.config import SitemapNewsStreamConfig
from clarion.config import settings
from clarion.local.database import LocalDatabase
from clarion.local.dev_firehose import FirehoseConfig, run_firehose
from clarion.local.monitor import LocalMonitor
from clarion.local.services.settings import LocalSetupService
from clarion.local.services.sources_materialize import (
    MaterializeFilter,
    format_plan,
    materialize,
)
from clarion.local.services.streams import LocalStreamService


def _open_db() -> LocalDatabase:
    return LocalDatabase(settings.require_database_url())


def _prompt(label: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or (default or "")


def cmd_init(_args: argparse.Namespace) -> None:
    db = _open_db()
    settings.load(db)
    LocalSetupService(db).initialize()
    print("\nLocal setup complete.")
    print("  - Add an RSS feed: clarion stream add --type rss")
    print("  - Start monitor:   clarion run")
    print("  - Open web UI:     clarion-web")
    print("  - Drive test load: clarion dev firehose --rate 20 --count 200")


def cmd_stream_list(_args: argparse.Namespace) -> None:
    db = _open_db()
    rows = LocalStreamService(db).list_stream_rows()
    if not rows:
        print("No streams configured. Run 'clarion stream add --type rss'.")
        return
    for row in rows:
        status = "enabled" if row["enabled"] else "disabled"
        detail = row["error"] or row["detail"]
        print(f"  {row['name']:20s} {row['stream_type']:8s} ({status})  {detail}")


def cmd_stream_remove(args: argparse.Namespace) -> None:
    db = _open_db()
    LocalStreamService(db).delete_stream(args.name)
    print(f"Removed stream {args.name!r}")


def cmd_stream_add(args: argparse.Namespace) -> None:
    db = _open_db()
    service = LocalStreamService(db)
    stream_type = args.type
    if not stream_type:
        print("Stream types: (1) rss  (2) sitemap_news")
        choice = _prompt("Choose stream type", default="1")
        stream_type = {
            "1": "rss",
            "2": "sitemap_news",
            "rss": "rss",
            "sitemap_news": "sitemap_news",
        }.get(choice.lower(), "rss")

    name = _prompt("Stream name (e.g. 'personal', 'hn-frontpage')")
    if not name:
        raise SystemExit("Stream name is required.")

    if stream_type == "rss":
        config_json = _prompt_rss_stream()
    elif stream_type == "sitemap_news":
        sitemap_url = _prompt("Sitemap URL (e.g. https://www.bloomberg.com/sitemaps/news/latest.xml)")
        publication = _prompt("Publication display name", default=name)
        config_json = SitemapNewsStreamConfig(
            sitemap_url=sitemap_url,
            publication_name=publication,
        ).model_dump_json()
    else:
        raise SystemExit(f"Unknown stream type: {stream_type!r}")

    service.add_stream(name, stream_type, config_json)
    print(f"\nAdded stream {name!r} (type={stream_type}).")


def _prompt_rss_stream() -> str:
    feed_url = _prompt("Feed URL (RSS or Atom)")
    if not feed_url:
        raise SystemExit("feed_url is required.")
    poll_seconds = int(_prompt("Poll interval (seconds)", default="300"))
    config = RSSStreamConfig(feed_url=feed_url, poll_seconds=poll_seconds)
    return config.model_dump_json()


def cmd_sources_materialize(args: argparse.Namespace) -> None:
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


def cmd_digest_build(args: argparse.Namespace) -> None:
    # Heavy imports (numpy; torch lazily inside the embedder) stay out of
    # the base CLI path.
    from datetime import date, timedelta, timezone
    from datetime import datetime as dt
    from pathlib import Path

    from clarion.digest.builder import DigestConfig, build_digest

    today = dt.now(timezone.utc).date()
    if args.day == "today":
        day = today
    elif args.day == "yesterday":
        day = today - timedelta(days=1)
    else:
        day = date.fromisoformat(args.day)

    config = DigestConfig(
        model_name=args.model,
        threshold=args.threshold,
        batch_size=args.batch_size,
        min_articles=args.min_articles,
        device=args.device,
        cache_dir=None if args.no_cache else Path(args.cache_dir),
        limit=args.limit,
        lang=args.lang,
    )
    db = _open_db()
    try:
        stats = build_digest(db, day, config, dry_run=args.dry_run)
    finally:
        db.close()
    if not args.dry_run:
        print(
            f"Digest for {stats.day}: {stats.n_events} events -> "
            f"{stats.n_clusters} clusters -> {stats.n_stories} stories stored. "
            f"(fetch {stats.seconds_fetch:.1f}s, embed {stats.seconds_embed:.1f}s, "
            f"cluster {stats.seconds_cluster:.1f}s, write {stats.seconds_write:.1f}s)"
        )


def cmd_run(_args: argparse.Namespace) -> None:
    db = _open_db()
    settings.load(db)
    asyncio.run(LocalMonitor(db).run())


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
        f"Emitting synthetic {config.source_type} traffic into {_database_label()} "
        f"at {config.rate:.2f} items/sec {target}. Press Ctrl-C to stop."
    )
    try:
        emitted = run_firehose(settings.require_database_url(), config)
    except KeyboardInterrupt:
        print("\nStopped.")
        return
    print(f"Emitted {emitted} synthetic item(s).")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clarion")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Configure the local runtime").set_defaults(func=cmd_init)
    sub.add_parser("run", help="Start the local supervisor").set_defaults(func=cmd_run)

    stream = sub.add_parser("stream", help="Manage local data streams")
    stream_sub = stream.add_subparsers(dest="stream_cmd", required=True)

    stream_sub.add_parser("list").set_defaults(func=cmd_stream_list)

    add = stream_sub.add_parser("add")
    add.add_argument("--type", choices=["rss", "sitemap_news"], help="Stream type")
    add.set_defaults(func=cmd_stream_add)

    rm = stream_sub.add_parser("remove")
    rm.add_argument("name")
    rm.set_defaults(func=cmd_stream_remove)

    sources = sub.add_parser(
        "sources",
        help="Manage the Media Cloud sitemap catalog",
    )
    sources_sub = sources.add_subparsers(dest="sources_cmd", required=True)

    mat = sources_sub.add_parser(
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
    mat.set_defaults(func=cmd_sources_materialize, kind=None)

    digest = sub.add_parser("digest", help="Build the daily story digest")
    digest_sub = digest.add_subparsers(dest="digest_cmd", required=True)

    dbuild = digest_sub.add_parser(
        "build",
        help="Cluster one UTC day's articles into ranked stories",
    )
    dbuild.add_argument(
        "--day", default="today",
        help="UTC day to build: YYYY-MM-DD, 'today' or 'yesterday' (default: today)",
    )
    dbuild.add_argument(
        "--threshold", type=float, default=0.92,
        help="Cosine similarity for two titles to share a story (default: 0.92; "
             "0.80 produced topic blobs, 0.90-0.925 produced clean stories)",
    )
    dbuild.add_argument(
        "--model", default="google/embeddinggemma-300m",
        help="sentence-transformers model for title embeddings",
    )
    dbuild.add_argument("--batch-size", type=int, default=128, help="Encoder batch size")
    dbuild.add_argument(
        "--min-articles", type=int, default=2,
        help="Only persist stories with at least this many articles (default: 2)",
    )
    dbuild.add_argument("--device", default=None, help="Torch device override (e.g. cpu, mps)")
    dbuild.add_argument(
        "--cache-dir", default="artifacts",
        help="Directory for per-day embedding caches (default: artifacts)",
    )
    dbuild.add_argument("--no-cache", action="store_true", help="Disable the embedding cache")
    dbuild.add_argument("--limit", type=int, default=None, help="Dev: cap number of events")
    dbuild.add_argument(
        "--lang", default=None,
        help="Dev: restrict to a metadata language prefix (e.g. 'en')",
    )
    dbuild.add_argument(
        "--dry-run", action="store_true",
        help="Print the top clusters instead of writing to the database",
    )
    dbuild.set_defaults(func=cmd_digest_build)

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

    return parser


def _database_label() -> str:
    url = settings.require_database_url()
    if "@" not in url:
        return url
    scheme_and_user, host_and_db = url.rsplit("@", maxsplit=1)
    if ":" not in scheme_and_user:
        return url
    return f"{scheme_and_user.rsplit(':', maxsplit=1)[0]}:***@{host_and_db}"


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
