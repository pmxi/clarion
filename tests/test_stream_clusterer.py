"""StreamClusterer: the online core of the digest daemon.

Vectors are built on a unit circle so cosine similarity is exactly
cos(angle difference): threshold 0.92 ≈ 23°, merge 0.95 ≈ 18°.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

np = pytest.importorskip("numpy")

from clarion.digest.stream import (  # noqa: E402
    ClusterItem,
    GrowStory,
    OpenStory,
    StreamClusterer,
    vec_from_bytes,
    vec_to_bytes,
)

T0 = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def v(angle_deg: float, dim: int = 8) -> np.ndarray:
    rad = math.radians(angle_deg)
    vec = np.zeros(dim, dtype=np.float32)
    vec[0], vec[1] = math.cos(rad), math.sin(rad)
    return vec


def item(eid: int, angle: float, *, domain: str = "", title: str = "",
         minutes: int = 0) -> ClusterItem:
    return ClusterItem(
        event_id=eid,
        vec=v(angle),
        title=title or f"title {eid}",
        domain=domain or f"domain{eid}.com",
        observed_at=T0 + timedelta(minutes=minutes),
    )


def test_first_item_waits_as_singleton():
    c = StreamClusterer(dim=8)
    assert c.add(item(1, 0)) is None
    assert c.stats() == {"stories": 0, "singletons": 1}


def test_two_similar_items_open_a_story():
    c = StreamClusterer(dim=8)
    c.add(item(1, 0, minutes=0))
    op = c.add(item(2, 10, minutes=5))
    assert isinstance(op, OpenStory)
    assert op.key < 0
    assert sorted(eid for eid, _ in op.members) == [1, 2]
    assert op.event_count == 2
    assert op.source_count == 2  # distinct domains
    assert op.day == date(2026, 7, 6)
    assert op.first_seen_at == T0
    assert op.last_seen_at == T0 + timedelta(minutes=5)
    # The earlier event anchors the representative title.
    assert op.rep_event_id == 1
    assert c.stats() == {"stories": 1, "singletons": 0}


def test_same_domain_counts_one_source():
    c = StreamClusterer(dim=8)
    c.add(item(1, 0, domain="wire.com"))
    op = c.add(item(2, 10, domain="wire.com"))
    assert isinstance(op, OpenStory)
    assert op.source_count == 1


def test_third_item_grows_the_story():
    c = StreamClusterer(dim=8)
    c.add(item(1, 0))
    opened = c.add(item(2, 10))
    assert isinstance(opened, OpenStory)
    op = c.add(item(3, 5, minutes=9))
    assert isinstance(op, GrowStory)
    assert op.key == opened.key
    assert op.member[0] == 3
    assert op.event_count == 3
    assert op.source_count == 3
    assert op.last_seen_at == T0 + timedelta(minutes=9)


def test_bind_rewrites_keys_for_later_ops():
    c = StreamClusterer(dim=8)
    c.add(item(1, 0))
    opened = c.add(item(2, 10))
    assert isinstance(opened, OpenStory)
    c.bind({opened.key: 42})
    op = c.add(item(3, 5))
    assert isinstance(op, GrowStory)
    assert op.key == 42


def test_dissimilar_items_stay_apart():
    c = StreamClusterer(dim=8)
    c.add(item(1, 0))
    assert c.add(item(2, 45)) is None
    assert c.stats() == {"stories": 0, "singletons": 2}


def test_rep_switches_to_the_more_central_member():
    c = StreamClusterer(dim=8)
    c.add(item(1, 0, title="edge one"))
    c.add(item(2, 20, title="edge two"))          # centroid ≈ 10°
    op = c.add(item(3, 10, title="dead center"))  # sim ≈ 1.0
    assert isinstance(op, GrowStory)
    assert op.rep_event_id == 3
    assert op.title == "dead center"


def _restore_story(c, sid, angle, *, count=2, first_minutes=0, domains=None):
    c.restore_story(
        story_id=sid, centroid=v(angle), day=date(2026, 7, 6),
        title=f"story {sid}", rep_event_id=sid * 100, rep_sim=0.97,
        event_count=count, domains=domains or {f"d{sid}.com"},
        first_seen=T0 + timedelta(minutes=first_minutes),
        last_seen=T0 + timedelta(minutes=first_minutes + 5),
    )


def test_merge_pass_unions_fragments():
    c = StreamClusterer(dim=8)  # merge threshold 0.95 ≈ 18°
    _restore_story(c, 10, 0, count=3, first_minutes=0)
    _restore_story(c, 20, 12, count=2, first_minutes=30)
    _restore_story(c, 30, 90, count=2, first_minutes=10)  # far away

    ops = c.merge_pass()
    assert len(ops) == 1
    merged = ops[0]
    assert merged.winner_key == 10   # earliest first_seen wins
    assert merged.loser_keys == [20]
    assert merged.event_count == 5
    assert merged.source_count == 2
    assert c.stats()["stories"] == 2

    # The loser's pool slot is gone: nothing can grow story 20 anymore.
    grow = c.add(item(99, 6))
    assert isinstance(grow, GrowStory)
    assert grow.key == 10


def test_merge_pass_with_no_candidates_is_quiet():
    c = StreamClusterer(dim=8)
    _restore_story(c, 10, 0)
    _restore_story(c, 20, 90)
    assert c.merge_pass() == []


def test_expiry_stops_assignment_but_keeps_nothing_in_memory():
    c = StreamClusterer(dim=8)
    _restore_story(c, 10, 0, first_minutes=0)
    c.add(item(1, 50, minutes=0))  # singleton
    cutoff = T0 + timedelta(hours=2)
    stories, singles = c.expire(story_cutoff=cutoff, single_cutoff=cutoff)
    assert (stories, singles) == (1, 1)
    assert c.stats() == {"stories": 0, "singletons": 0}
    # An item that would have matched the expired story now waits alone.
    assert c.add(item(2, 2, minutes=200)) is None


def test_restored_singleton_can_open_a_story():
    c = StreamClusterer(dim=8)
    c.restore_singleton(
        event_id=7, vec=v(0), title="restored", domain="a.com", observed_at=T0
    )
    op = c.add(item(8, 8, minutes=1))
    assert isinstance(op, OpenStory)
    assert sorted(eid for eid, _ in op.members) == [7, 8]
    assert op.rep_event_id == 7


def test_vec_bytes_roundtrip_preserves_direction():
    vec = v(37)
    back = vec_from_bytes(vec_to_bytes(vec))
    assert back.dtype == np.float32
    assert abs(float(vec @ back) - 1.0) < 1e-3
    assert abs(float(np.linalg.norm(back)) - 1.0) < 1e-6
