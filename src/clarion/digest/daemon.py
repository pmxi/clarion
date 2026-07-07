"""The digest daemon: continuous story clustering over the event stream.

The fourth process. Holds the title encoder resident and folds new
events into stories as they arrive — the work that costs hours as a
whole-day batch is negligible as a trickle. All clustering state lives
in StreamClusterer and is exactly reconstructible from the story and
event_embedding tables, so restarts (and crashes mid-batch: every batch
commits atomically with its cursor) lose nothing.
"""

from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Dict, List, Optional

from clarion.db.pool import DictConnectionPool
from clarion.db.stores import embeddings as embeddings_store
from clarion.db.stores import events as events_store
from clarion.db.stores import monitoring as monitoring_store
from clarion.db.stores import stories as stories_store
from clarion.digest.embedder import DEFAULT_MODEL, TitleEmbedder
from clarion.digest.stream import (
    ClusterItem,
    GrowStory,
    OpenStory,
    StreamClusterer,
    vec_from_bytes,
    vec_to_bytes,
)
from clarion.digest.text import normalize_title, source_domain
from clarion.logging import get_logger
from clarion.timeutils import utc_now

logger = get_logger(__name__)


@dataclass
class DaemonConfig:
    model_name: str = DEFAULT_MODEL
    device: Optional[str] = None
    # float32, not the embedder's bf16 default: CPUs without native bf16
    # (oracle's ARM) hit a fallback path that is ~6x slower per title.
    dtype: str = "float32"
    threshold: float = 0.92
    poll_seconds: float = 30.0
    batch_size: int = 512            # events fetched + embedded per cycle
    story_window_hours: int = 48     # how long a story keeps accepting members
    single_window_hours: int = 24    # how long a lone title waits for a pair
    merge_every_seconds: float = 1800.0
    prune_every_seconds: float = 3600.0


class DigestDaemon:
    def __init__(self, pool: DictConnectionPool, config: DaemonConfig):
        self.pool = pool
        self.config = config
        self._embedder = TitleEmbedder(
            model_name=config.model_name, device=config.device, dtype=config.dtype
        )
        self._clusterer: Optional[StreamClusterer] = None
        self._cursor = 0
        self._stop = threading.Event()
        self._last_merge = time.monotonic()
        self._last_prune = time.monotonic()

    def run(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self._stop.set())

        logger.info("Loading %s", self.config.model_name)
        dim = self._embedder.encode(["warmup"]).shape[1]
        self._clusterer = StreamClusterer(threshold=self.config.threshold, dim=dim)
        self._rebuild_state()

        logger.info("Digest daemon running (cursor=%d)", self._cursor)
        while not self._stop.is_set():
            try:
                n = self._process_one_batch()
                if time.monotonic() - self._last_merge >= self.config.merge_every_seconds:
                    self._merge()
                if time.monotonic() - self._last_prune >= self.config.prune_every_seconds:
                    self._prune_and_expire()
            except Exception:
                logger.exception("digest cycle failed; retrying next poll")
                n = 0
            if n < self.config.batch_size:  # caught up — wait for arrivals
                self._stop.wait(self.config.poll_seconds)
        logger.info("Digest daemon stopped (cursor=%d)", self._cursor)

    # ----- state ---------------------------------------------------------

    def _rebuild_state(self) -> None:
        assert self._clusterer is not None
        now = utc_now()
        story_since = now - timedelta(hours=self.config.story_window_hours)
        single_since = now - timedelta(hours=self.config.single_window_hours)

        with self.pool.connection() as conn:
            active = stories_store.active_stories(conn, story_since)
            members = stories_store.all_members(conn, [s["id"] for s in active])
            singles = embeddings_store.unassigned_since(conn, single_since)
            cursor = monitoring_store.get_digest_cursor(conn)
            if cursor is None:
                # First run: start at the top of the current UTC day so
                # today's digest backfills; older days stay `digest build`'s.
                midnight = datetime.combine(now.date(), dtime(0), tzinfo=timezone.utc)
                first_today = events_store.min_id_since(conn, midnight)
                cursor = (first_today - 1) if first_today else events_store.latest_id(conn)

        for s in active:
            mems = members.get(int(s["id"]), [])
            if not mems:
                continue
            self._clusterer.restore_story(
                story_id=int(s["id"]),
                centroid=vec_from_bytes(s["centroid"]),
                day=s["day"],
                title=s["title"],
                rep_event_id=int(s["rep_event_id"]),
                rep_sim=max(float(m["similarity"] or 0.0) for m in mems),
                event_count=int(s["event_count"]),
                domains={source_domain(m["url"], m["stream_name"]) for m in mems},
                first_seen=s["first_seen_at"],
                last_seen=s["last_seen_at"],
            )
        for g in singles:
            self._clusterer.restore_singleton(
                event_id=int(g["event_id"]),
                vec=vec_from_bytes(g["vec"]),
                title=normalize_title(g["title"]),
                domain=source_domain(g["url"], g["stream_name"]),
                observed_at=g["observed_at"],
            )
        self._cursor = cursor
        logger.info(
            "State rebuilt: %d active stories, %d singletons, cursor=%d",
            len(active), len(singles), cursor,
        )

    # ----- the pipeline --------------------------------------------------

    def _process_one_batch(self) -> int:
        assert self._clusterer is not None
        with self.pool.connection() as conn:
            rows = events_store.fetch_clusterable_since(
                conn, self._cursor, limit=self.config.batch_size
            )
        if not rows:
            return 0

        titles = [normalize_title(r["title"]) for r in rows]
        vecs = self._embedder.encode(titles)

        ops: List[OpenStory | GrowStory] = []
        for row, title, vec in zip(rows, titles, vecs):
            op = self._clusterer.add(ClusterItem(
                event_id=int(row["id"]),
                vec=vec,
                title=title,
                domain=source_domain(row["url"], row["stream_name"]),
                observed_at=row["observed_at"],
            ))
            if op is not None:
                ops.append(op)

        # One transaction per batch: story writes, the embedding cache,
        # and the cursor land together or not at all.
        local_ids: Dict[int, int] = {}
        with self.pool.connection() as conn, conn.transaction():
            for op in ops:
                if isinstance(op, OpenStory):
                    story_id = stories_store.insert_story(
                        conn, day=op.day, title=op.title,
                        rep_event_id=op.rep_event_id,
                        event_count=op.event_count, source_count=op.source_count,
                        centroid=vec_to_bytes(op.centroid),
                        first_seen_at=op.first_seen_at, last_seen_at=op.last_seen_at,
                    )
                    local_ids[op.key] = story_id
                    stories_store.add_members(
                        conn, [(story_id, eid, sim) for eid, sim in op.members]
                    )
                else:
                    story_id = local_ids.get(op.key, op.key)
                    stories_store.update_story(
                        conn, story_id, title=op.title,
                        rep_event_id=op.rep_event_id,
                        event_count=op.event_count, source_count=op.source_count,
                        centroid=vec_to_bytes(op.centroid),
                        last_seen_at=op.last_seen_at,
                    )
                    eid, sim = op.member
                    stories_store.add_members(conn, [(story_id, eid, sim)])
            embeddings_store.put_many(
                conn,
                [(int(r["id"]), vec_to_bytes(v), r["observed_at"])
                 for r, v in zip(rows, vecs)],
            )
            monitoring_store.set_digest_cursor(conn, int(rows[-1]["id"]))

        self._clusterer.bind(local_ids)
        self._cursor = int(rows[-1]["id"])

        opens = sum(1 for op in ops if isinstance(op, OpenStory))
        grows = len(ops) - opens
        if ops:
            stats = self._clusterer.stats()
            logger.info(
                "clustered %d events: +%d stories, %d grown (live=%d, waiting=%d)",
                len(rows), opens, grows, stats["stories"], stats["singletons"],
            )
        return len(rows)

    def _merge(self) -> None:
        assert self._clusterer is not None
        self._last_merge = time.monotonic()
        merges = self._clusterer.merge_pass()
        if not merges:
            return
        with self.pool.connection() as conn, conn.transaction():
            for op in merges:
                for loser in op.loser_keys:
                    stories_store.absorb_story(conn, op.winner_key, loser)
                stories_store.update_story(
                    conn, op.winner_key, title=op.title,
                    rep_event_id=op.rep_event_id,
                    event_count=op.event_count, source_count=op.source_count,
                    centroid=vec_to_bytes(op.centroid),
                    last_seen_at=op.last_seen_at,
                )
        logger.info(
            "merged %d fragment group(s) (%d stories absorbed)",
            len(merges), sum(len(op.loser_keys) for op in merges),
        )

    def _prune_and_expire(self) -> None:
        assert self._clusterer is not None
        self._last_prune = time.monotonic()
        now = utc_now()
        stories, singles = self._clusterer.expire(
            story_cutoff=now - timedelta(hours=self.config.story_window_hours),
            single_cutoff=now - timedelta(hours=self.config.single_window_hours),
        )
        # Keep embeddings a little past the singleton window so a restart
        # right at the boundary rebuilds the same pool.
        with self.pool.connection() as conn:
            pruned = embeddings_store.prune_before(
                conn, now - timedelta(hours=self.config.single_window_hours + 2)
            )
        if stories or singles or pruned:
            logger.info(
                "expired %d stories, %d singletons from memory; pruned %d embeddings",
                stories, singles, pruned,
            )
