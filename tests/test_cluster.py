"""Invariants for the digest's greedy clustering (no DB, no network)."""

import pytest

np = pytest.importorskip("numpy")

from clarion.digest.cluster import cluster_greedy  # noqa: E402


def _three_anchor_corpus(scale: float = 0.03, per_anchor: int = 200):
    rng = np.random.default_rng(42)
    anchors = rng.normal(size=(3, 64))
    anchors /= np.linalg.norm(anchors, axis=1, keepdims=True)
    rows, truth = [], []
    for i, anchor in enumerate(anchors):
        pts = anchor + rng.normal(scale=scale, size=(per_anchor, 64))
        pts /= np.linalg.norm(pts, axis=1, keepdims=True)
        rows.append(pts)
        truth += [i] * per_anchor
    emb = np.concatenate(rows)
    truth = np.array(truth)
    perm = rng.permutation(len(emb))
    return emb[perm], truth[perm]


def test_well_separated_groups_cluster_exactly():
    emb, truth = _three_anchor_corpus()
    res = cluster_greedy(emb, threshold=0.9, batch_size=64)
    n = res.assignment.max() + 1
    assert n == 3
    for c in range(n):
        assert len(set(truth[res.assignment == c])) == 1, "mixed cluster"


def test_purity_holds_even_when_noise_straddles_threshold():
    # Borderline geometry over-splits (acceptable) but must never mix anchors.
    emb, truth = _three_anchor_corpus(scale=0.05)
    res = cluster_greedy(emb, threshold=0.9, batch_size=64)
    for c in range(res.assignment.max() + 1):
        assert len(set(truth[res.assignment == c])) == 1


def test_edge_cases():
    emb, _ = _three_anchor_corpus()
    assert cluster_greedy(emb[:1], threshold=0.9).assignment.tolist() == [0]
    dup = np.vstack([emb[0], emb[0]])
    assert cluster_greedy(dup, threshold=0.99).assignment.tolist() == [0, 0]


def test_similarity_is_to_own_centroid():
    emb, _ = _three_anchor_corpus()
    res = cluster_greedy(emb, threshold=0.9, batch_size=64)
    assert res.similarity.min() > 0.9
    assert res.similarity.max() <= 1.0 + 1e-6
