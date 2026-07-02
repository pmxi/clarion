"""Greedy online centroid clustering over L2-normalized embeddings.

Single pass in row order: each item joins the most similar existing
cluster if its cosine similarity to that cluster's centroid clears the
threshold, otherwise it starts a new cluster. Centroids are running
means, renormalized after every update.

Greedy assignment fragments: early items seed a cluster before its
centroid has converged, so one story can split into several clusters
(measured ~13% of multi-article clusters on real data). A final merge
pass unions clusters whose *final* centroids clear the same threshold,
which re-joins those fragments.

For throughput, items are scored against pre-existing centroids one
batch at a time (a single GEMM instead of per-item matvecs). Two
approximations follow from that, both negligible at news-title scale:
- within a batch, scores against pre-existing clusters use the centroid
  snapshot from the start of the batch;
- clusters born inside the current batch are checked per item, exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ClusterResult:
    # Cluster id for each input row, dense in [0, n_clusters).
    assignment: np.ndarray
    # Exact final centroids (mean of members, renormalized), (n_clusters, dim).
    centroids: np.ndarray
    # Cosine similarity of each row to its own final centroid.
    similarity: np.ndarray


def cluster_greedy(
    emb: np.ndarray,
    threshold: float,
    batch_size: int = 1024,
    merge_threshold: Optional[float] = None,
) -> ClusterResult:
    """merge_threshold defaults to threshold + 0.03: merging at the
    assignment threshold lets union-find chain through dense template-
    headline regions into black-hole clusters (measured: an 8k-article
    cluster mixing bonds, NBA trades and student loans), while +0.03
    still re-joins genuine fragments of one story. Pass 1.0 to disable."""
    assignment = _assign_greedy(emb, threshold, batch_size)
    merge_at = threshold + 0.03 if merge_threshold is None else merge_threshold
    if merge_at < 1.0:
        centroids, _ = _finalize(emb, assignment)
        assignment = _merge_fragments(assignment, centroids, merge_at)
    centroids, similarity = _finalize(emb, assignment)
    return ClusterResult(assignment=assignment, centroids=centroids, similarity=similarity)


def _assign_greedy(emb: np.ndarray, threshold: float, batch_size: int) -> np.ndarray:
    n_items, dim = emb.shape
    assignment = np.full(n_items, -1, dtype=np.int64)

    capacity = 4096
    centroids = np.zeros((capacity, dim), dtype=np.float32)
    counts = np.zeros(capacity, dtype=np.int64)
    n_clusters = 0

    for start in range(0, n_items, batch_size):
        batch = emb[start : start + batch_size]
        frozen = n_clusters  # clusters that existed before this batch

        if frozen:
            sims = batch @ centroids[:frozen].T
            best = sims.argmax(axis=1)
            best_sim = sims[np.arange(len(batch)), best]
        else:
            best = np.zeros(len(batch), dtype=np.int64)
            best_sim = np.full(len(batch), -np.inf, dtype=np.float32)

        for i in range(len(batch)):
            e = batch[i]
            cid = int(best[i]) if best_sim[i] >= threshold else -1
            if cid < 0 and n_clusters > frozen:
                fresh_sims = centroids[frozen:n_clusters] @ e
                j = int(fresh_sims.argmax())
                if fresh_sims[j] >= threshold:
                    cid = frozen + j
            if cid < 0:
                if n_clusters == capacity:
                    capacity *= 2
                    centroids = np.vstack([centroids, np.zeros_like(centroids)])
                    counts = np.concatenate([counts, np.zeros_like(counts)])
                cid = n_clusters
                centroids[cid] = e
                counts[cid] = 1
                n_clusters += 1
            else:
                c = centroids[cid] * counts[cid] + e
                norm = np.linalg.norm(c)
                if norm > 0:
                    c /= norm
                centroids[cid] = c
                counts[cid] += 1
            assignment[start + i] = cid

    return assignment


def _merge_fragments(
    assignment: np.ndarray,
    centroids: np.ndarray,
    threshold: float,
    block: int = 2048,
) -> np.ndarray:
    """Union clusters whose final centroids clear the threshold; return a
    re-densified assignment. Works in blocks to bound the sims matrix."""
    n = len(centroids)
    parent = np.arange(n)

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for lo in range(0, n, block):
        blk = centroids[lo : min(lo + block, n)]
        sims = blk @ centroids.T
        for i in range(len(blk)):  # strict upper triangle only
            sims[i, : lo + i + 1] = 0.0
        for i, j in np.argwhere(sims >= threshold):
            ra, rb = find(lo + int(i)), find(int(j))
            if ra != rb:
                parent[ra] = rb

    roots = np.array([find(c) for c in range(n)], dtype=np.int64)
    dense = {r: k for k, r in enumerate(dict.fromkeys(roots[assignment].tolist()))}
    return np.array([dense[r] for r in roots[assignment]], dtype=np.int64)


def _finalize(emb: np.ndarray, assignment: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Exact centroids (mean of members, renormalized) and each row's
    cosine similarity to its own centroid."""
    n_clusters = int(assignment.max()) + 1
    final = np.zeros((n_clusters, emb.shape[1]), dtype=np.float32)
    np.add.at(final, assignment, emb)
    norms = np.linalg.norm(final, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    final /= norms
    similarity = np.einsum("ij,ij->i", emb, final[assignment]).astype(np.float32)
    return final, similarity
