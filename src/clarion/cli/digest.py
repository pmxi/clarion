"""`clarion digest ...` — daily story aggregation."""

from __future__ import annotations

import argparse

from clarion.cli.common import open_pool


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
    stats = build_digest(open_pool(), day, config, dry_run=args.dry_run)
    if not args.dry_run:
        print(
            f"Digest for {stats.day}: {stats.n_events} events -> "
            f"{stats.n_clusters} clusters -> {stats.n_stories} stories stored. "
            f"(fetch {stats.seconds_fetch:.1f}s, embed {stats.seconds_embed:.1f}s, "
            f"cluster {stats.seconds_cluster:.1f}s, write {stats.seconds_write:.1f}s)"
        )


def register(sub: argparse._SubParsersAction) -> None:
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
