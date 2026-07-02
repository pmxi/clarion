"""Greedy online centroid clustering over L2-normalized embeddings.

Single pass in row order: each item joins the most similar existing
cluster if its cosine similarity to that cluster's centroid clears the
threshold, otherwise it starts a new cluster. Centroids are running
means, renormalized after every update.

For throughput, items are scored against pre-existing centroids one
batch at a time (a single GEMM instead of per-item matvecs). Two
approximations follow from that, both negligible at news-title scale:
- within a batch, scores against pre-existing clusters use the centroid
  snapshot from the start of the batch;
- clusters born inside the current batch are checked per item, exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

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
) -> ClusterResult:
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

    # Exact final centroids from full membership, then per-row similarity.
    final = np.zeros((n_clusters, dim), dtype=np.float32)
    np.add.at(final, assignment, emb)
    norms = np.linalg.norm(final, axis=1, keepdims=True)
    np.divide(final, norms, out=final, where=norms > 0)
    similarity = np.einsum("ij,ij->i", emb, final[assignment]).astype(np.float32)

    return ClusterResult(assignment=assignment, centroids=final, similarity=similarity)
