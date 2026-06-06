"""Multi-tenant proxy variants.

Three variants in this module, escalating in cross-source intelligence:

  v0.4.0 PerSourceNamespaceProxy
    Per-source isolation. Never merges across sources. Source-prefixed
    canonicals. Simple, fast write path, over-isolates globally-shared
    entities.

  v0.4.1 CrossSourceConsensusProxy
    EAGER cross-source merge by alias-set Jaccard on every write.
    Catches obvious cross-source consensus immediately but pays an
    O(K) Jaccard scan per write. Default merge threshold 0.5.

  v0.4.2 LazyCrossSourceConsensusProxy
    LAZY cross-source merge: write path is pure per-source isolation
    (same cost as v0.4.0), with a separate `consolidate()` method that
    runs the merge offline using both alias-set Jaccard AND embedding-
    similarity. The harness calls consolidate() between pass 1 and
    pass 2 so reads see the final canonical. In production this maps
    to a periodic background job that runs on a configurable cadence.

The v0.4.2 design is the deliberate write-latency-vs-merge-accuracy
split documented in the project README. Per-write cost stays at v0.3.1
levels; cross-source intelligence accumulates with eventual consistency.
"""
from __future__ import annotations
import math
from typing import Callable, Protocol

from .base import Variant


class Consolidatable(Protocol):
    """Variants implementing this protocol expose an explicit consolidate()
    step that the runner can invoke between pass 1 and pass 2.

    Lazy-merge variants implement this; eager variants do not (their
    merges happen during align_with_context). The runner uses
    isinstance(variant, Consolidatable)-equivalent duck typing to decide.
    """

    def consolidate(self) -> dict: ...


class CrossSourceConsensusProxy(Variant):
    """v0.4.1 multi-tenant proxy: per-source isolation + cross-source
    merge by alias-set Jaccard.

    Builds on v0.4.0's per-source-namespace architecture. Each source
    gets its own inner variant (default: v0.3.1 hybrid + structural
    filter) that locally clusters that source's writes. The new layer
    on top:

    For each (source_id, local_canonical) key, track the SET of input
    surface forms that have been aliased to it. Across sources, if two
    keys have alias sets with Jaccard overlap >= threshold, merge them
    into a single shared canonical name. Otherwise, keep source-prefixed
    isolation as v0.4.0 does.

    Intuition: when sales' "Microsoft" cluster accumulates aliases
    {"Microsoft", "MSFT", "Microsoft Corporation"} and ops' "Microsoft"
    cluster accumulates the same set, both sources are clearly talking
    about the same entity and should share the canonical. But if sales'
    "Apple" cluster has {"Apple", "AAPL", "Apple Inc", "Apple Computer"}
    while ops' "Apple" cluster has {"Apple", "Apple Foods",
    "Apple Supplier Inc"}, the only overlap is "Apple" itself and the
    Jaccard is low — keep them isolated.

    Cross-source merge is necessarily ORDER-DEPENDENT during a single
    pass: early writes return source-prefixed canonicals; once enough
    writes accumulate to trigger a merge, later writes return the
    merged canonical. The harness wraps this variant in a two-pass
    execution model (pass 1 builds state, pass 2 re-queries) so all
    entries get their FINAL canonical, regardless of write order.

    Known limitation: greedy first-pair merge, not transitive. If A and
    B have Jaccard above threshold and B and C have Jaccard above
    threshold but A and C don't directly overlap, the algorithm finds
    A-B and B-C merges separately and the result is correct because
    once B is merged it carries the merged name forward. But for cases
    where three sources need to be transitively unified through weaker
    pairwise links, the greedy heuristic can miss merges.
    """

    name = "embed-proxy-v0.4.1-consensus"

    def __init__(
        self,
        inner_factory: Callable[[], Variant] | None = None,
        alias_jaccard_threshold: float = 0.5,
        min_aliases_for_merge: int = 2,
    ):
        if not 0 < alias_jaccard_threshold <= 1:
            raise ValueError("alias_jaccard_threshold must be in (0, 1]")
        if min_aliases_for_merge < 1:
            raise ValueError("min_aliases_for_merge must be >= 1")
        if inner_factory is None:
            from .embed_proxy import StructurallyFilteredHybridSchemaProxy

            inner_factory = StructurallyFilteredHybridSchemaProxy
        self._inner_factory = inner_factory
        self._per_source: dict[str, Variant] = {}
        # (source_id, local_canonical) -> set of input surface forms
        self._aliases: dict[tuple[str, str], set[str]] = {}
        # (source_id, local_canonical) -> merged shared canonical name
        self._merged: dict[tuple[str, str], str] = {}
        self._jaccard_threshold = alias_jaccard_threshold
        self._min_aliases = min_aliases_for_merge

    @property
    def known_sources(self) -> list[str]:
        return list(self._per_source.keys())

    @property
    def merged_clusters(self) -> dict[tuple[str, str], str]:
        return dict(self._merged)

    def _get_inner(self, source_id: str) -> Variant:
        inner = self._per_source.get(source_id)
        if inner is None:
            inner = self._inner_factory()
            self._per_source[source_id] = inner
        return inner

    def align(self, input_relation: str) -> str:
        """Single-tenant fallback: route to a global namespace."""
        return self.align_with_context(input_relation, context=None)

    def align_with_context(
        self,
        input_relation: str,
        context: dict | None = None,
    ) -> str:
        source_id = (context or {}).get("source_id", "default")
        inner = self._get_inner(source_id)
        local = inner.align(input_relation)
        key = (source_id, local)
        self._aliases.setdefault(key, set()).add(input_relation)
        return self._current_canonical_for(key)

    def _current_canonical_for(self, key: tuple[str, str]) -> str:
        # Already merged? Return cached merge target.
        if key in self._merged:
            return self._merged[key]

        my_aliases = self._aliases[key]
        # Not enough signal yet for a confident merge decision.
        if len(my_aliases) < self._min_aliases:
            return f"{key[0]}::{key[1]}"

        best_match_key = None
        best_jaccard = 0.0
        for other_key, other_aliases in self._aliases.items():
            if other_key[0] == key[0]:
                continue
            if len(other_aliases) < self._min_aliases:
                continue
            overlap = len(my_aliases & other_aliases)
            if overlap == 0:
                continue
            jaccard = overlap / len(my_aliases | other_aliases)
            if jaccard > best_jaccard:
                best_jaccard = jaccard
                best_match_key = other_key

        if best_jaccard >= self._jaccard_threshold and best_match_key is not None:
            # If the best match is already merged, inherit its merged name;
            # otherwise mint a new merged name based on the match's canonical.
            merged_name = self._merged.get(
                best_match_key,
                f"merged::{best_match_key[1]}",
            )
            self._merged[key] = merged_name
            self._merged[best_match_key] = merged_name
            return merged_name

        return f"{key[0]}::{key[1]}"


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class LazyCrossSourceConsensusProxy(Variant):
    """v0.4.2 multi-tenant proxy with deferred cross-source merge.

    Write path (align_with_context): per-source isolation only. Each
    write goes through the source's inner variant; the cross-source
    merge is NOT computed online. Per-write cost is exactly the inner
    variant's cost. No O(K) scan, no embedding comparisons across
    source canonicals.

    Consolidation (consolidate): runs the cross-source merge offline.
    Two signals combine:
      1. Alias-set Jaccard, as in v0.4.1.
      2. Embedding-similarity over per-cluster centroids. Centroid
         for (source, local) = mean of inner-embedder embeddings of
         that cluster's input surface forms.
    A merge fires when (Jaccard >= jaccard_threshold) OR
    (cosine >= cosine_threshold).

    The OR rule means embedding similarity can catch cross-source
    consensus that alias overlap misses (e.g., "Microsoft" in one
    source and "Microsoft Corporation" in another with no shared
    surface form but identical semantics).

    Production model: write path serves online traffic; consolidate()
    runs as a periodic background job on a configurable cadence
    (every N writes, every shift, nightly).

    Harness model: pass 1 calls align_with_context for every entry
    (state accumulates per-source). The runner then calls consolidate()
    once. Pass 2 re-queries every entry; reads now reflect the merged
    state.
    """

    name = "embed-proxy-v0.4.2-lazy-consensus"

    def __init__(
        self,
        inner_factory: Callable[[], Variant] | None = None,
        alias_jaccard_threshold: float = 0.5,
        embedding_cosine_threshold: float = 0.85,
        min_aliases_for_merge: int = 2,
    ):
        if not 0 < alias_jaccard_threshold <= 1:
            raise ValueError("alias_jaccard_threshold must be in (0, 1]")
        if not -1 <= embedding_cosine_threshold <= 1:
            raise ValueError("embedding_cosine_threshold must be in [-1, 1]")
        if min_aliases_for_merge < 1:
            raise ValueError("min_aliases_for_merge must be >= 1")
        if inner_factory is None:
            from .embed_proxy import StructurallyFilteredHybridSchemaProxy

            inner_factory = StructurallyFilteredHybridSchemaProxy
        self._inner_factory = inner_factory
        self._per_source: dict[str, Variant] = {}
        # (source, local) -> set of input surface forms
        self._aliases: dict[tuple[str, str], set[str]] = {}
        # (source, local) -> list of embedding vectors (one per write)
        self._embeddings: dict[tuple[str, str], list[list[float]]] = {}
        # (source, local) -> merged canonical (populated by consolidate())
        self._merged: dict[tuple[str, str], str] = {}
        self._jaccard_threshold = alias_jaccard_threshold
        self._cosine_threshold = embedding_cosine_threshold
        self._min_aliases = min_aliases_for_merge

    @property
    def known_sources(self) -> list[str]:
        return list(self._per_source.keys())

    @property
    def merged_clusters(self) -> dict[tuple[str, str], str]:
        return dict(self._merged)

    def _get_inner(self, source_id: str) -> Variant:
        inner = self._per_source.get(source_id)
        if inner is None:
            inner = self._inner_factory()
            self._per_source[source_id] = inner
        return inner

    def align(self, input_relation: str) -> str:
        return self.align_with_context(input_relation, context=None)

    def align_with_context(
        self,
        input_relation: str,
        context: dict | None = None,
    ) -> str:
        source_id = (context or {}).get("source_id", "default")
        inner = self._get_inner(source_id)
        local = inner.align(input_relation)
        key = (source_id, local)
        self._aliases.setdefault(key, set()).add(input_relation)
        # Track the embedding for centroid computation in consolidate().
        # The inner variant exposes .embedder; if not, skip.
        embedder = getattr(inner, "embedder", None)
        if embedder is not None:
            self._embeddings.setdefault(key, []).append(
                embedder.embed(input_relation)
            )
        # Lazy: return the merged canonical if consolidation already ran,
        # else source-prefixed.
        return self._merged.get(key, f"{source_id}::{local}")

    def _centroid(self, key: tuple[str, str]) -> list[float] | None:
        vecs = self._embeddings.get(key, [])
        if not vecs:
            return None
        dim = len(vecs[0])
        c = [0.0] * dim
        for v in vecs:
            for i, x in enumerate(v):
                c[i] += x
        n = len(vecs)
        c = [x / n for x in c]
        norm = math.sqrt(sum(x * x for x in c))
        if norm == 0:
            return None
        return [x / norm for x in c]

    def consolidate(self) -> dict:
        """Compute cross-source merges offline. Mutates self._merged.

        Returns a small summary dict for the runner to log:
          {
            "n_keys": <total per-source cluster count>,
            "n_merge_edges": <pairs that triggered a merge>,
            "n_merged_clusters": <distinct merged canonical names>,
            "merge_reasons": {"jaccard_only": N, "cosine_only": N, "both": N},
          }
        """
        keys = list(self._aliases.keys())
        # Centroids cache
        centroids: dict[tuple[str, str], list[float] | None] = {
            k: self._centroid(k) for k in keys
        }
        # Find merge pairs using union-find
        parent: dict[tuple[str, str], tuple[str, str]] = {k: k for k in keys}

        def find(k: tuple[str, str]) -> tuple[str, str]:
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        def union(a: tuple[str, str], b: tuple[str, str]) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        n_edges = 0
        reasons = {"jaccard_only": 0, "cosine_only": 0, "both": 0}
        for i in range(len(keys)):
            ki = keys[i]
            ai = self._aliases[ki]
            if len(ai) < self._min_aliases:
                continue
            ci = centroids.get(ki)
            for j in range(i + 1, len(keys)):
                kj = keys[j]
                if ki[0] == kj[0]:
                    continue  # same source
                aj = self._aliases[kj]
                if len(aj) < self._min_aliases:
                    continue
                overlap = len(ai & aj)
                union_size = len(ai | aj)
                jaccard = overlap / union_size if union_size > 0 else 0.0
                cosine_score = (
                    _cosine(ci, centroids[kj])
                    if ci is not None and centroids.get(kj) is not None
                    else 0.0
                )
                jac_ok = jaccard >= self._jaccard_threshold
                cos_ok = cosine_score >= self._cosine_threshold
                if jac_ok or cos_ok:
                    union(ki, kj)
                    n_edges += 1
                    if jac_ok and cos_ok:
                        reasons["both"] += 1
                    elif jac_ok:
                        reasons["jaccard_only"] += 1
                    else:
                        reasons["cosine_only"] += 1

        # Build canonical merge map. CRITICAL: only assign a merged
        # canonical to keys that ACTUALLY participated in a merge.
        # Singleton keys (no cross-source edges) must stay source-prefixed
        # in align_with_context; otherwise two sources whose inners
        # happened to mint the same local canonical name (e.g. both
        # tech_company and biology end up with local "Apple") would
        # spuriously collapse to "merged::Apple" without any evidence
        # they should share.
        self._merged.clear()
        # First, find the equivalence classes' members
        members_by_root: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for k in keys:
            members_by_root.setdefault(find(k), []).append(k)
        # Only merge classes with >=2 members get a merged canonical.
        for root, members in members_by_root.items():
            if len(members) < 2:
                continue
            merged_name = f"merged::{root[1]}"
            for m in members:
                self._merged[m] = merged_name

        return {
            "n_keys": len(keys),
            "n_merge_edges": n_edges,
            "n_merged_clusters": sum(
                1 for members in members_by_root.values() if len(members) >= 2
            ),
            "n_singleton_keys": sum(
                1 for members in members_by_root.values() if len(members) == 1
            ),
            "merge_reasons": reasons,
        }


class PerSourceNamespaceProxy(Variant):
    """Maintain one inner variant per observed source_id.

    Inner variant factory defaults to v0.3.1 (hybrid + structural
    filter). Each source gets its own fresh instance, lazily
    constructed on first contact.
    """

    name = "embed-proxy-v0.4.0-per-source"

    def __init__(self, inner_factory: Callable[[], Variant] | None = None):
        if inner_factory is None:
            # Default inner: v0.3.1 hybrid + structural filter
            from .embed_proxy import StructurallyFilteredHybridSchemaProxy

            inner_factory = StructurallyFilteredHybridSchemaProxy
        self._inner_factory = inner_factory
        self._per_source: dict[str, Variant] = {}

    @property
    def known_sources(self) -> list[str]:
        return list(self._per_source.keys())

    def _inner_for(self, source_id: str) -> Variant:
        inner = self._per_source.get(source_id)
        if inner is None:
            inner = self._inner_factory()
            self._per_source[source_id] = inner
        return inner

    def align(self, input_relation: str) -> str:
        """Single-tenant fallback: route to a global namespace."""
        return self.align_with_context(input_relation, context=None)

    def align_with_context(
        self,
        input_relation: str,
        context: dict | None = None,
    ) -> str:
        source_id = (context or {}).get("source_id", "default")
        inner = self._inner_for(source_id)
        local_canonical = inner.align(input_relation)
        return f"{source_id}::{local_canonical}"
