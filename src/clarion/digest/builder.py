"""Digest builder: fetch a day's events, embed titles, cluster, persist.

Day bucketing uses observed_at (UTC): received_at comes from publishers
and contains garbage (epoch zeros, future dates), while observed_at is
ours and monotonic. The digest therefore answers "what was collected
that day", which for a daily news digest is the honest framing.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np  # ty: ignore[unresolved-import] — digest extra

from clarion.db.pool import DictConnectionPool
from clarion.db.stores import stories as stories_store
from clarion.digest.cluster import cluster_greedy
from clarion.digest.embedder import DEFAULT_MODEL, TitleEmbedder
from clarion.digest.text import normalize_title, source_domain
from clarion.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DigestConfig:
    model_name: str = DEFAULT_MODEL
    threshold: float = 0.92
    batch_size: int = 128          # encoder batch
    cluster_batch: int = 1024      # GEMM batch for greedy clustering
    min_events: int = 2          # don't persist singleton clusters
    device: Optional[str] = None
    cache_dir: Optional[Path] = Path("artifacts")
    limit: Optional[int] = None    # dev: cap the number of events
    lang: Optional[str] = None     # dev: restrict to a metadata language prefix


@dataclass
class DigestStats:
    day: date
    n_events: int = 0
    n_embedded: int = 0
    n_clusters: int = 0
    n_stories: int = 0
    seconds_fetch: float = 0.0
    seconds_embed: float = 0.0
    seconds_cluster: float = 0.0
    seconds_write: float = 0.0


@dataclass
class _Story:
    title: str
    rep_event_id: int
    event_count: int
    source_count: int
    domains: List[str] = field(default_factory=list)
    members: List[Tuple[int, float]] = field(default_factory=list)  # (event_id, similarity)
    sample_titles: List[str] = field(default_factory=list)


def build_digest(
    pool: DictConnectionPool, day: date, config: DigestConfig, dry_run: bool = False
) -> DigestStats:
    """Build (or rebuild) the story digest for one UTC day.

    Takes the pool rather than a connection: embedding can run for hours,
    and separate checkouts for the fetch and the final write mean a
    connection dropped mid-embed heals instead of failing the run.
    """
    stats = DigestStats(day=day)

    t0 = time.monotonic()
    with pool.connection() as conn:
        rows = _fetch_day(conn, day, config)
    stats.seconds_fetch = time.monotonic() - t0
    stats.n_events = len(rows)
    if not rows:
        logger.info("digest: no events for %s, nothing to do", day)
        return stats

    titles = [normalize_title(r["title"]) for r in rows]
    t0 = time.monotonic()
    emb = _embed_with_cache(rows, titles, day, config)
    stats.seconds_embed = time.monotonic() - t0
    stats.n_embedded = len(titles)

    t0 = time.monotonic()
    result = cluster_greedy(emb, threshold=config.threshold, batch_size=config.cluster_batch)
    stats.seconds_cluster = time.monotonic() - t0
    stats.n_clusters = int(result.assignment.max()) + 1 if len(rows) else 0

    stories = _aggregate(rows, result.assignment, result.similarity, config)
    stats.n_stories = len(stories)

    if dry_run:
        _print_preview(stories, stats)
        return stats

    t0 = time.monotonic()
    payload = [
        {
            "title": s.title,
            "rep_event_id": s.rep_event_id,
            "event_count": s.event_count,
            "source_count": s.source_count,
            "members": s.members,
        }
        for s in stories
    ]
    with pool.connection() as conn:
        stories_store.replace_day(conn, day, payload)
    stats.seconds_write = time.monotonic() - t0
    logger.info(
        "digest %s: %d events -> %d clusters -> %d stories "
        "(fetch %.1fs embed %.1fs cluster %.1fs write %.1fs)",
        day, stats.n_events, stats.n_clusters, stats.n_stories,
        stats.seconds_fetch, stats.seconds_embed, stats.seconds_cluster, stats.seconds_write,
    )
    return stats


# ----- fetch --------------------------------------------------------------


def _fetch_day(conn, day: date, config: DigestConfig) -> List[Dict[str, Any]]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    # LENGTH filter: ultra-short titles ("AO VIVO", "(no title)", section
    # names) carry no story signal and congeal into junk-attractor
    # clusters; leave them out of the digest entirely. 12 chars keeps
    # legitimate CJK headlines, which are short in characters.
    sql = """
        SELECT id, title, url, stream_name
        FROM event
        WHERE observed_at >= %s AND observed_at < %s
          AND LENGTH(title) >= 12
    """
    params: List[Any] = [start, end]
    if config.lang:
        sql += " AND metadata->>'language' ILIKE %s"
        params.append(config.lang + "%")
    sql += " ORDER BY observed_at ASC"
    if config.limit:
        sql += " LIMIT %s"
        params.append(config.limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# ----- embeddings (with per-day cache) ------------------------------------


def _cache_path(day: date, config: DigestConfig) -> Optional[Path]:
    if config.cache_dir is None:
        return None
    slug = config.model_name.replace("/", "__")
    return Path(config.cache_dir) / f"digest_emb__{slug}__{day.isoformat()}.npz"


def _embed_with_cache(
    rows: List[Dict[str, Any]],
    titles: List[str],
    day: date,
    config: DigestConfig,
) -> np.ndarray:
    """Return one normalized float32 vector per row, reusing any cached
    vectors for event ids already embedded in a previous run of this day."""
    ids = np.array([r["id"] for r in rows], dtype=np.int64)
    path = _cache_path(day, config)

    cached_ids = np.zeros(0, dtype=np.int64)
    cached_emb: Optional[np.ndarray] = None
    if path is not None and path.exists():
        data = np.load(path)
        cached_ids, cached_emb = data["ids"], data["emb"]

    id_to_row = {int(i): k for k, i in enumerate(cached_ids)}
    missing = [k for k, i in enumerate(ids) if int(i) not in id_to_row]

    dim = cached_emb.shape[1] if cached_emb is not None else 0
    if missing:
        embedder = TitleEmbedder(
            model_name=config.model_name,
            batch_size=config.batch_size,
            device=config.device,
        )
        logger.info("digest: embedding %d/%d titles (%d cached)",
                    len(missing), len(ids), len(ids) - len(missing))
        new_emb = embedder.encode([titles[k] for k in missing], progress=True)
        dim = new_emb.shape[1]
    else:
        new_emb = np.zeros((0, dim), dtype=np.float32)

    emb = np.zeros((len(ids), dim), dtype=np.float32)
    for pos, k in enumerate(missing):
        emb[k] = new_emb[pos]
    hit = [k for k in range(len(ids)) if int(ids[k]) in id_to_row]
    if hit:
        assert cached_emb is not None  # a cache hit implies the cache loaded
        hit_emb = cached_emb[[id_to_row[int(ids[k])] for k in hit]].astype(np.float32)
        # float16 storage denormalizes slightly; restore unit length.
        norms = np.linalg.norm(hit_emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        emb[hit] = hit_emb / norms

    if path is not None and missing:
        path.parent.mkdir(parents=True, exist_ok=True)
        all_ids = np.concatenate([cached_ids, ids[missing]])
        all_emb = (
            np.concatenate([cached_emb, new_emb.astype(np.float16)])
            if cached_emb is not None else new_emb.astype(np.float16)
        )
        np.savez(path, ids=all_ids, emb=all_emb)
    return emb


# ----- aggregation --------------------------------------------------------


def _aggregate(
    rows: List[Dict[str, Any]],
    assignment: np.ndarray,
    similarity: np.ndarray,
    config: DigestConfig,
) -> List[_Story]:
    n_clusters = int(assignment.max()) + 1
    members: List[List[int]] = [[] for _ in range(n_clusters)]
    for k, cid in enumerate(assignment):
        members[cid].append(k)

    stories: List[_Story] = []
    for cid, idxs in enumerate(members):
        if len(idxs) < config.min_events:
            continue
        domains = Counter(source_domain(rows[k]["url"], rows[k]["stream_name"]) for k in idxs)
        medoid = max(idxs, key=lambda k: similarity[k])
        stories.append(_Story(
            title=normalize_title(rows[medoid]["title"]),
            rep_event_id=int(rows[medoid]["id"]),
            event_count=len(idxs),
            source_count=len(domains),
            domains=[d for d, _ in domains.most_common(6)],
            members=[(int(rows[k]["id"]), float(similarity[k])) for k in idxs],
            sample_titles=[normalize_title(rows[k]["title"]) for k in idxs[:5]],
        ))
    return stories


# ----- dry-run preview -----------------------------------------------------


def _print_preview(stories: List[_Story], stats: DigestStats, top: int = 30) -> None:
    ranked = sorted(stories, key=lambda s: (-s.source_count, -s.event_count))
    print(
        f"\n{stats.day}: {stats.n_events} events -> {stats.n_clusters} clusters "
        f"-> {len(stories)} stories with >=2 articles "
        f"(embed {stats.seconds_embed:.1f}s, cluster {stats.seconds_cluster:.1f}s)\n"
    )
    for rank, s in enumerate(ranked[:top], 1):
        print(f"{rank:3d}. [{s.source_count:3d} sources / {s.event_count:4d} articles]"
              f" {s.title[:110]}")
        for t in s.sample_titles[1:4]:
            if t != s.title:
                print(f"       - {t[:100]}")
        print(f"       @ {', '.join(s.domains)}")
