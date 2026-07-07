"""Online story clustering — the streaming core of the digest daemon.

The same greedy-centroid scheme as cluster.py's batch path, run
continuously: each incoming title vector joins the most similar live
story or singleton if it clears the threshold, otherwise it waits in
the singleton pool. Two matched singletons open a story. A periodic
merge pass re-joins fragments, exactly like the batch merge.

Pure in-memory and side-effect free: every mutation is returned as an
op (OpenStory / GrowStory / MergeStories) for the caller to persist.
Newly opened stories carry negative local keys until the caller binds
them to database ids via bind(). State is fully reconstructible from
the story and event_embedding tables (see restore_*), which is what
makes daemon restarts safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import numpy as np


def vec_to_bytes(vec: np.ndarray) -> bytes:
    """Serialize an L2-normalized vector as little-endian float16."""
    return vec.astype("<f2").tobytes()


def vec_from_bytes(raw: bytes) -> np.ndarray:
    """Deserialize and re-normalize (float16 storage denormalizes slightly)."""
    vec = np.frombuffer(raw, dtype="<f2").astype(np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


@dataclass(frozen=True)
class ClusterItem:
    """One clusterable event, embedded."""

    event_id: int
    vec: np.ndarray            # L2-normalized float32
    title: str
    domain: str
    observed_at: datetime


@dataclass
class OpenStory:
    key: int                   # negative local key; caller binds a db id
    day: date
    title: str
    rep_event_id: int
    members: List[Tuple[int, float]]
    event_count: int
    source_count: int
    centroid: np.ndarray
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass
class GrowStory:
    key: int                   # db id, or local key if opened this batch
    member: Tuple[int, float]
    title: str
    rep_event_id: int
    event_count: int
    source_count: int
    centroid: np.ndarray
    last_seen_at: datetime


@dataclass
class MergeStories:
    winner_key: int
    loser_keys: List[int]
    title: str
    rep_event_id: int
    event_count: int
    source_count: int
    centroid: np.ndarray
    last_seen_at: datetime


@dataclass
class _Story:
    key: int
    centroid: np.ndarray
    count: int
    domains: Set[str]
    rep_event_id: int
    rep_sim: float
    title: str
    day: date
    first_seen: datetime
    last_seen: datetime


@dataclass
class _Single:
    event_id: int
    vec: np.ndarray
    title: str
    domain: str
    observed_at: datetime


class _VecPool:
    """Growable row matrix with tombstoned removal, so scoring every
    incoming vector is one matvec instead of a python loop."""

    def __init__(self, dim: int, capacity: int = 4096):
        self._mat = np.zeros((capacity, dim), dtype=np.float32)
        self._keys: List[Optional[int]] = []
        self._index: Dict[int, int] = {}
        self._dead = 0

    def __len__(self) -> int:
        return len(self._index)

    def add(self, key: int, vec: np.ndarray) -> None:
        n = len(self._keys)
        if n == len(self._mat):
            self._mat = np.vstack([self._mat, np.zeros_like(self._mat)])
        self._mat[n] = vec
        self._keys.append(key)
        self._index[key] = n

    def update(self, key: int, vec: np.ndarray) -> None:
        self._mat[self._index[key]] = vec

    def rekey(self, old: int, new: int) -> None:
        row = self._index.pop(old)
        self._index[new] = row
        self._keys[row] = new

    def remove(self, key: int) -> None:
        # Zeroed rows can never clear a positive cosine threshold.
        row = self._index.pop(key)
        self._mat[row] = 0.0
        self._keys[row] = None
        self._dead += 1
        if self._dead > 1024 and self._dead > len(self._keys) // 4:
            self._compact()

    def best(self, vec: np.ndarray) -> Tuple[Optional[int], float]:
        n = len(self._keys)
        if not n:
            return None, -1.0
        sims = self._mat[:n] @ vec
        row = int(sims.argmax())
        key = self._keys[row]
        return key, float(sims[row])

    def matrix_and_keys(self) -> Tuple[np.ndarray, List[int]]:
        """Live rows only, for the merge pass."""
        rows = [r for r, k in enumerate(self._keys) if k is not None]
        keys = [k for k in self._keys if k is not None]
        return self._mat[rows], keys  # type: ignore[return-value]

    def _compact(self) -> None:
        live = [(k, r) for r, k in enumerate(self._keys) if k is not None]
        mat = np.zeros_like(self._mat[: max(len(live), 1024)])
        self._keys = []
        self._index = {}
        for n, (key, row) in enumerate(live):
            if n == len(mat):
                mat = np.vstack([mat, np.zeros_like(mat)])
            mat[n] = self._mat[row]
            self._keys.append(key)
            self._index[key] = n
        self._mat = mat
        self._dead = 0


def _utc_day(dt: datetime) -> date:
    return dt.astimezone(timezone.utc).date()


class StreamClusterer:
    def __init__(
        self,
        *,
        threshold: float = 0.92,
        merge_threshold: Optional[float] = None,
        dim: int = 768,
    ):
        self.threshold = threshold
        # Same rationale as the batch path: merging at the assignment
        # threshold chains through dense template-headline regions.
        self.merge_threshold = (
            threshold + 0.03 if merge_threshold is None else merge_threshold
        )
        self._stories: Dict[int, _Story] = {}
        self._singles: Dict[int, _Single] = {}
        self._story_pool = _VecPool(dim)
        self._single_pool = _VecPool(dim)
        self._next_local = 0

    # ----- restore (daemon restart) -----------------------------------------

    def restore_story(
        self,
        *,
        story_id: int,
        centroid: np.ndarray,
        day: date,
        title: str,
        rep_event_id: int,
        rep_sim: float,
        event_count: int,
        domains: Set[str],
        first_seen: datetime,
        last_seen: datetime,
    ) -> None:
        self._stories[story_id] = _Story(
            key=story_id, centroid=centroid, count=event_count,
            domains=set(domains), rep_event_id=rep_event_id, rep_sim=rep_sim,
            title=title, day=day, first_seen=first_seen, last_seen=last_seen,
        )
        self._story_pool.add(story_id, centroid)

    def restore_singleton(
        self, *, event_id: int, vec: np.ndarray, title: str,
        domain: str, observed_at: datetime,
    ) -> None:
        self._singles[event_id] = _Single(event_id, vec, title, domain, observed_at)
        self._single_pool.add(event_id, vec)

    # ----- streaming ---------------------------------------------------------

    def add(self, item: ClusterItem) -> Optional[OpenStory | GrowStory]:
        """Assign one item; returns the persistence op it caused, if any."""
        story_key, story_sim = self._story_pool.best(item.vec)
        single_id, single_sim = self._single_pool.best(item.vec)

        # Prefer the story on ties so near-duplicates don't fork.
        if story_key is not None and story_sim >= self.threshold and story_sim >= single_sim:
            return self._grow(self._stories[story_key], item, story_sim)
        if single_id is not None and single_sim >= self.threshold:
            return self._open(self._singles[single_id], item)

        self._singles[item.event_id] = _Single(
            item.event_id, item.vec, item.title, item.domain, item.observed_at
        )
        self._single_pool.add(item.event_id, item.vec)
        return None

    def _grow(self, story: _Story, item: ClusterItem, sim: float) -> GrowStory:
        blended = story.centroid * story.count + item.vec
        norm = float(np.linalg.norm(blended))
        if norm > 0:
            blended /= norm
        story.centroid = blended.astype(np.float32)
        story.count += 1
        story.domains.add(item.domain)
        story.last_seen = max(story.last_seen, item.observed_at)
        if sim > story.rep_sim:
            story.rep_sim = sim
            story.rep_event_id = item.event_id
            story.title = item.title
        self._story_pool.update(story.key, story.centroid)
        return GrowStory(
            key=story.key, member=(item.event_id, sim),
            title=story.title, rep_event_id=story.rep_event_id,
            event_count=story.count, source_count=len(story.domains),
            centroid=story.centroid, last_seen_at=story.last_seen,
        )

    def _open(self, single: _Single, item: ClusterItem) -> OpenStory:
        del self._singles[single.event_id]
        self._single_pool.remove(single.event_id)

        centroid = single.vec + item.vec
        norm = float(np.linalg.norm(centroid))
        if norm > 0:
            centroid /= norm
        centroid = centroid.astype(np.float32)
        sims = {
            single.event_id: float(centroid @ single.vec),
            item.event_id: float(centroid @ item.vec),
        }
        # The earlier event anchors the story: its day, and (on the tie
        # that two members always are) the representative title.
        first, second = sorted(
            (single, item),
            key=lambda m: (m.observed_at, m.event_id),
        )
        rep_id = max(sims, key=lambda eid: (sims[eid], eid == first.event_id))
        rep = first if rep_id == first.event_id else second

        self._next_local -= 1
        key = self._next_local
        story = _Story(
            key=key, centroid=centroid, count=2,
            domains={single.domain, item.domain},
            rep_event_id=rep.event_id, rep_sim=sims[rep.event_id],
            title=rep.title, day=_utc_day(first.observed_at),
            first_seen=first.observed_at, last_seen=second.observed_at,
        )
        self._stories[key] = story
        self._story_pool.add(key, centroid)
        return OpenStory(
            key=key, day=story.day, title=story.title,
            rep_event_id=story.rep_event_id,
            members=[(m.event_id, sims[m.event_id]) for m in (first, second)],
            event_count=2, source_count=len(story.domains),
            centroid=centroid, first_seen_at=story.first_seen,
            last_seen_at=story.last_seen,
        )

    def bind(self, mapping: Dict[int, int]) -> None:
        """Replace local story keys with their database ids."""
        for local, db_id in mapping.items():
            story = self._stories.pop(local)
            story.key = db_id
            self._stories[db_id] = story
            self._story_pool.rekey(local, db_id)

    # ----- maintenance --------------------------------------------------------

    def merge_pass(self) -> List[MergeStories]:
        """Union stories whose centroids clear the merge threshold.
        Call only when all stories are bound (positive keys)."""
        mat, keys = self._story_pool.matrix_and_keys()
        if len(keys) < 2:
            return []
        parent = list(range(len(keys)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        sims = mat @ mat.T
        for i, j in np.argwhere(np.triu(sims, k=1) >= self.merge_threshold):
            ri, rj = find(int(i)), find(int(j))
            if ri != rj:
                parent[ri] = rj

        groups: Dict[int, List[int]] = {}
        for pos in range(len(keys)):
            groups.setdefault(find(pos), []).append(pos)

        ops: List[MergeStories] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            stories = [self._stories[keys[pos]] for pos in members]
            winner = min(stories, key=lambda s: (s.first_seen, s.key))
            losers = [s for s in stories if s.key != winner.key]

            blended = sum((s.centroid * s.count for s in stories), start=np.zeros_like(winner.centroid))
            norm = float(np.linalg.norm(blended))
            if norm > 0:
                blended /= norm
            winner.centroid = blended.astype(np.float32)
            winner.count = sum(s.count for s in stories)
            winner.domains = set().union(*(s.domains for s in stories))
            best_rep = max(stories, key=lambda s: s.rep_sim)
            winner.rep_event_id = best_rep.rep_event_id
            winner.rep_sim = best_rep.rep_sim
            winner.title = best_rep.title
            winner.last_seen = max(s.last_seen for s in stories)

            self._story_pool.update(winner.key, winner.centroid)
            for loser in losers:
                del self._stories[loser.key]
                self._story_pool.remove(loser.key)
            ops.append(MergeStories(
                winner_key=winner.key,
                loser_keys=[s.key for s in losers],
                title=winner.title, rep_event_id=winner.rep_event_id,
                event_count=winner.count, source_count=len(winner.domains),
                centroid=winner.centroid, last_seen_at=winner.last_seen,
            ))
        return ops

    def expire(self, *, story_cutoff: datetime, single_cutoff: datetime) -> Tuple[int, int]:
        """Drop from memory what aged out of the window. Story rows stay
        in the database as archive; expiry only stops new assignment."""
        dead_stories = [k for k, s in self._stories.items() if s.last_seen < story_cutoff]
        for key in dead_stories:
            del self._stories[key]
            self._story_pool.remove(key)
        dead_singles = [e for e, s in self._singles.items() if s.observed_at < single_cutoff]
        for eid in dead_singles:
            del self._singles[eid]
            self._single_pool.remove(eid)
        return len(dead_stories), len(dead_singles)

    def stats(self) -> Dict[str, int]:
        return {"stories": len(self._stories), "singletons": len(self._singles)}
