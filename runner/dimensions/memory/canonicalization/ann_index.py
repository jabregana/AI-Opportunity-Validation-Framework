"""ANN index abstraction for the schema proxy's nearest-canonical lookup.

The default EmbeddingSchemaProxy does a linear O(K) cosine scan over
every canonical on every write. The scale-stress finding
(`docs/finding-scale-stress.md`) showed this drops throughput from 70
writes/sec at K~300 to ~16 writes/sec at K~16k. Past that, the wedge
thesis vs LLM-in-loop CLOSES.

This module provides two interchangeable index backends:

  - LinearANNIndex: numpy-vectorized linear scan. Exact. No extra deps
    beyond numpy. Recommended below K~5k.
  - HNSWANNIndex: hnswlib HNSW graph. Approximate. Sub-linear lookup.
    Recommended above K~5k. Falls back to LinearANNIndex if hnswlib
    is not installed (the project's optional `ann` extra).

Both implement the same protocol so the calling variant does not have
to care which one is in use. The index is keyed by integer canonical
index (matching the position in `EmbeddingSchemaProxy._canonicals`).
"""
from __future__ import annotations
from typing import Protocol

try:
    import numpy as np
    _HAVE_NUMPY = True
except ImportError:
    _HAVE_NUMPY = False

try:
    import hnswlib
    _HAVE_HNSW = True
except ImportError:
    _HAVE_HNSW = False


class ANNIndex(Protocol):
    """Approximate nearest-neighbor index over L2-normalized vectors.

    Cosine = dot product for normalized vectors, so all backends compute
    cosine via dot product internally.
    """

    @property
    def size(self) -> int:
        """Number of vectors currently indexed."""

    def add(self, idx: int, vector: list[float]) -> None:
        """Add a vector at integer id `idx`. ids must be unique."""

    def nearest(self, vector: list[float]) -> tuple[int, float]:
        """Return (idx, cosine_similarity) of the single nearest neighbor.
        Raises if the index is empty."""


class LinearANNIndex:
    """Exact O(K) cosine scan, numpy-vectorized when available.

    Numpy fallback (pure-python) is the same algorithm as the original
    inline loop in EmbeddingSchemaProxy.align; the numpy path is what
    makes a difference at K > a few hundred.
    """

    def __init__(self, dim: int):
        if dim < 1:
            raise ValueError(f"dim must be >= 1, got {dim}")
        self._dim = dim
        self._ids: list[int] = []
        if _HAVE_NUMPY:
            self._matrix = np.zeros((0, dim), dtype=np.float32)
        else:
            self._matrix = []  # list of list[float]

    @property
    def size(self) -> int:
        return len(self._ids)

    def add(self, idx: int, vector: list[float]) -> None:
        if len(vector) != self._dim:
            raise ValueError(
                f"vector dim {len(vector)} != index dim {self._dim}"
            )
        self._ids.append(idx)
        if _HAVE_NUMPY:
            row = np.asarray(vector, dtype=np.float32).reshape(1, -1)
            self._matrix = np.vstack([self._matrix, row]) if self._matrix.size else row
        else:
            self._matrix.append(list(vector))

    def nearest(self, vector: list[float]) -> tuple[int, float]:
        if not self._ids:
            raise IndexError("index is empty")
        if _HAVE_NUMPY:
            q = np.asarray(vector, dtype=np.float32)
            sims = self._matrix @ q
            best = int(np.argmax(sims))
            return self._ids[best], float(sims[best])
        # pure-python fallback
        best_i = 0
        best_sim = sum(a * b for a, b in zip(vector, self._matrix[0]))
        for i in range(1, len(self._ids)):
            s = sum(a * b for a, b in zip(vector, self._matrix[i]))
            if s > best_sim:
                best_sim = s
                best_i = i
        return self._ids[best_i], best_sim


class HNSWANNIndex:
    """Approximate HNSW index via hnswlib. Sub-linear nearest-neighbor
    lookup at the cost of (small) recall loss.

    Parameters tuned for the project's typical embedding dim (4096 token
    + 256 neural). Recall at top-1 for cosine should be >0.99 on
    workloads where the top-1 margin is > a few percent (which is the
    only regime our threshold-based aliasing relies on; below-threshold
    matches never trigger an alias).

    HNSWANNIndex grows the underlying hnswlib index lazily, doubling
    capacity each time it fills up. This keeps add cost amortized O(1)
    rather than paying a giant up-front allocation. Insertion order
    matches LinearANNIndex so the proxy's first-writer-wins canonical
    naming is unchanged.
    """

    def __init__(
        self,
        dim: int,
        initial_capacity: int = 1024,
        M: int = 16,
        ef_construction: int = 200,
        ef_search: int = 64,
    ):
        if not _HAVE_HNSW:
            raise RuntimeError(
                "hnswlib not installed; install with `pip install hnswlib` "
                "or use the `ann` extra"
            )
        if dim < 1:
            raise ValueError(f"dim must be >= 1, got {dim}")
        self._dim = dim
        self._capacity = max(16, initial_capacity)
        self._M = M
        self._ef_c = ef_construction
        self._ef_s = ef_search
        self._index = hnswlib.Index(space="cosine", dim=dim)
        self._index.init_index(
            max_elements=self._capacity,
            ef_construction=self._ef_c,
            M=self._M,
        )
        self._index.set_ef(self._ef_s)
        self._ids: list[int] = []  # insertion-order mapping to canonical idx

    @property
    def size(self) -> int:
        return len(self._ids)

    def _maybe_grow(self) -> None:
        if len(self._ids) + 1 > self._capacity:
            self._capacity *= 2
            self._index.resize_index(self._capacity)

    def add(self, idx: int, vector: list[float]) -> None:
        if len(vector) != self._dim:
            raise ValueError(
                f"vector dim {len(vector)} != index dim {self._dim}"
            )
        self._maybe_grow()
        pos = len(self._ids)
        self._ids.append(idx)
        # hnswlib uses cosine DISTANCE (1 - cos_sim) internally. The label
        # we attach is the position within the index, which we then map
        # back to the caller's canonical idx via self._ids.
        if _HAVE_NUMPY:
            v = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        else:
            v = [vector]
        self._index.add_items(v, [pos])

    def nearest(self, vector: list[float]) -> tuple[int, float]:
        if not self._ids:
            raise IndexError("index is empty")
        if _HAVE_NUMPY:
            v = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        else:
            v = [vector]
        labels, distances = self._index.knn_query(v, k=1)
        pos = int(labels[0][0])
        # hnswlib reports cosine distance; convert to similarity.
        sim = 1.0 - float(distances[0][0])
        return self._ids[pos], sim


def build_index(dim: int, backend: str = "auto", **kwargs) -> ANNIndex:
    """Build an ANN index. `backend` is one of:
      - "linear": always use LinearANNIndex
      - "hnsw":   require HNSWANNIndex; raises if hnswlib is missing
      - "auto":   HNSWANNIndex if hnswlib is installed, else LinearANNIndex
    """
    if backend == "linear":
        return LinearANNIndex(dim)
    if backend == "hnsw":
        return HNSWANNIndex(dim, **kwargs)
    if backend == "auto":
        if _HAVE_HNSW:
            return HNSWANNIndex(dim, **kwargs)
        return LinearANNIndex(dim)
    raise ValueError(f"unknown backend {backend!r}; expected linear/hnsw/auto")
