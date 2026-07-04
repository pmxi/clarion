"""Shared scaffolding for the catalog discovery walkers.

discover_sitemaps and discover_feeds are the same machine pointed at
different targets: select high-volume sources, fan a per-source async
walk out under a semaphore (one connection per host), record an audit
row per run, and upsert what was found. That shape lives here; the
walkers keep only their own parsing/validation and upsert SQL.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, LiteralString, TypeVar

import aiohttp
import psycopg
from psycopg.rows import DictRow

from clarion.logging import get_logger
from clarion.timeutils import utc_now_iso

logger = get_logger(__name__)

R = TypeVar("R")

# (source_id, walk result or None on crash, crash repr or None)
WalkOutcome = tuple[int, R | None, str | None]


@dataclass
class FetchResult:
    status: int
    body: bytes
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


def looks_gzipped(raw: bytes) -> bool:
    return len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B


async def fetch(
    session: aiohttp.ClientSession, url: str, timeout: aiohttp.ClientTimeout
) -> FetchResult:
    try:
        async with session.get(url, timeout=timeout, allow_redirects=True) as resp:
            body = await resp.read()
            return FetchResult(
                status=resp.status,
                body=body,
                etag=resp.headers.get("etag"),
                last_modified=resp.headers.get("last-modified"),
            )
    except Exception as exc:
        return FetchResult(status=0, body=b"", error=str(exc))


def select_sources(
    conn: psycopg.Connection[DictRow],
    args: argparse.Namespace,
    *,
    value_column: LiteralString = "canonical_domain",
) -> list[tuple[int, str]]:
    """(id, value_column) pairs to walk: the explicit --domains list, or
    the top --limit sources by stories_per_week. One source per
    canonical_domain either way (the catalog lists many URL variants of
    the same outlet)."""
    with conn.cursor() as cur:
        if args.domains:
            cur.execute(
                f"""
                SELECT id, canonical_domain, {value_column} AS value FROM source
                WHERE canonical_domain = ANY(%s)
                  AND {value_column} IS NOT NULL
                ORDER BY stories_per_week DESC NULLS LAST
                """,
                (args.domains,),
            )
        else:
            cur.execute(
                f"""
                SELECT id, canonical_domain, {value_column} AS value FROM source
                WHERE canonical_domain IS NOT NULL
                  AND {value_column} IS NOT NULL
                  AND stories_per_week >= %s
                ORDER BY stories_per_week DESC
                LIMIT %s
                """,
                (args.min_spw, args.limit),
            )
        rows = cur.fetchall()
    seen: set[str] = set()
    out: list[tuple[int, str]] = []
    for r in rows:
        if r["canonical_domain"] in seen:
            continue
        seen.add(r["canonical_domain"])
        out.append((r["id"], r["value"]))
    return out


def start_run(conn: psycopg.Connection[DictRow], table: LiteralString) -> int:
    row = conn.execute(
        f"INSERT INTO {table} (started_at) VALUES (%s) RETURNING id",
        (utc_now_iso(),),
    ).fetchone()
    assert row is not None  # INSERT ... RETURNING always yields a row
    return int(row["id"])


def finish_run(
    conn: psycopg.Connection[DictRow],
    table: LiteralString,
    run_id: int,
    counts: dict[LiteralString, Any],
) -> None:
    sets = ", ".join(f"{column}=%s" for column in counts)
    conn.execute(
        f"UPDATE {table} SET finished_at=%s, {sets} WHERE id=%s",
        (utc_now_iso(), *counts.values(), run_id),
    )


async def walk_sources(
    sources: list[tuple[int, str]],
    walk_one: Callable[[aiohttp.ClientSession, int, str], Awaitable[R]],
    *,
    concurrency: int,
    user_agent: str,
    connector_limit: int | None = None,
    progress_every: int = 25,
    on_progress: Callable[[int, int, list[WalkOutcome]], None] | None = None,
) -> list[WalkOutcome]:
    """Fan walk_one over the sources under a semaphore, one connection
    per host. A crashed walk is logged and yields (source_id, None,
    repr(exc)); callers decide how to record it. Outcomes arrive in
    completion order."""
    sem = asyncio.Semaphore(concurrency)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
    connector = aiohttp.TCPConnector(
        limit=connector_limit or concurrency, limit_per_host=1, ttl_dns_cache=300
    )
    outcomes: list[WalkOutcome] = []
    async with aiohttp.ClientSession(headers=headers, connector=connector) as session:

        async def bounded(source_id: int, value: str) -> WalkOutcome:
            async with sem:
                try:
                    return source_id, await walk_one(session, source_id, value), None
                except Exception as exc:
                    logger.exception("walk crashed for source %d (%s)", source_id, value)
                    return source_id, None, repr(exc)

        tasks = [asyncio.create_task(bounded(sid, value)) for sid, value in sources]
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            outcomes.append(await coro)
            if i % progress_every == 0 or i == len(tasks):
                if on_progress is not None:
                    on_progress(i, len(tasks), outcomes)
                else:
                    logger.info("completed %d/%d", i, len(tasks))
    return outcomes


def base_arg_parser(description: str | None, *, default_concurrency: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--limit", type=int, default=20, help="max sources to walk (ignored if --domains)")
    parser.add_argument("--min-spw", type=int, default=50, help="minimum stories_per_week")
    parser.add_argument("--concurrency", type=int, default=default_concurrency)
    parser.add_argument(
        "--domains",
        type=lambda s: [d.strip() for d in s.split(",") if d.strip()],
        default=None,
        help="comma-separated canonical_domain list (overrides --limit/--min-spw)",
    )
    return parser
