"""Multi-tenant proxy variants.

Four variants in this module, escalating in cross-source intelligence:

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
    runs the merge offline using alias-set Jaccard OR embedding
    cosine. The harness calls consolidate() between pass 1 and pass 2
    so reads see the final canonical. In production this maps to a
    periodic background job that runs on a configurable cadence.

  v0.4.3 LazyConsensusANDRuleProxy
    Same lazy design as v0.4.2 but with two added safety checks:
      1. AND rule: both Jaccard AND embedding cosine must clear
         their thresholds (vs v0.4.2's OR).
      2. min_overlap: alias sets must share at least N elements
         (default 2), not just one. v0.4.2 over-merges WIKIDATA
         clusters that share only the common surface form "Apple"
         (Jaccard = 1.0 over the single shared element). Requiring
         two shared aliases ensures the evidence is more than a
         single naming collision.

The v0.4.2+ designs are the deliberate write-latency-vs-merge-accuracy
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


class LazyConsensusANDRuleProxy(LazyCrossSourceConsensusProxy):
    """v0.4.3: lazy cross-source merge with AND rule + min_overlap.

    Inherits v0.4.2's lazy execution model (per-source write path,
    explicit consolidate() between pass 1 and pass 2). Adds two safety
    checks to address v0.4.2's WIKIDATA over-merging:

    1. AND rule: both Jaccard AND embedding cosine must clear their
       thresholds (vs v0.4.2's OR). Requires evidence from both
       signal types before merging.

    2. min_overlap_for_merge (default 2): the alias intersection must
       have at least this many shared elements. v0.4.2 happily merges
       two single-alias clusters that share their one alias (Jaccard
       = 1.0). On WIKIDATA, several (source, local) clusters end up
       single-alias for distinct entities that happen to share a
       common surface like "Apple"; requiring two shared aliases
       blocks these spurious one-word merges.

    Trade-off: more conservative than v0.4.2. Will miss merges where
    two sources legitimately share only one alias for the same entity.
    For realistic enterprise data where teams use multiple aliases
    per entity, this is safe. For sparse data, may under-merge.
    """

    name = "embed-proxy-v0.4.3-and-rule"

    def __init__(
        self,
        inner_factory=None,
        alias_jaccard_threshold: float = 0.5,
        embedding_cosine_threshold: float = 0.85,
        min_aliases_for_merge: int = 2,
        min_overlap_for_merge: int = 2,
    ):
        if min_overlap_for_merge < 1:
            raise ValueError("min_overlap_for_merge must be >= 1")
        super().__init__(
            inner_factory=inner_factory,
            alias_jaccard_threshold=alias_jaccard_threshold,
            embedding_cosine_threshold=embedding_cosine_threshold,
            min_aliases_for_merge=min_aliases_for_merge,
        )
        self._min_overlap = min_overlap_for_merge

    def consolidate(self) -> dict:
        """Union-find merge with AND rule and min_overlap constraint."""
        keys = list(self._aliases.keys())
        centroids: dict[tuple[str, str], list[float] | None] = {
            k: self._centroid(k) for k in keys
        }
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
        reasons = {
            "and_passed": 0,
            "blocked_overlap_below_min": 0,
            "blocked_jaccard_below": 0,
            "blocked_cosine_below": 0,
            "blocked_both": 0,
        }
        for i in range(len(keys)):
            ki = keys[i]
            ai = self._aliases[ki]
            if len(ai) < self._min_aliases:
                continue
            ci = centroids.get(ki)
            for j in range(i + 1, len(keys)):
                kj = keys[j]
                if ki[0] == kj[0]:
                    continue
                aj = self._aliases[kj]
                if len(aj) < self._min_aliases:
                    continue
                overlap = len(ai & aj)
                if overlap < self._min_overlap:
                    reasons["blocked_overlap_below_min"] += 1
                    continue
                union_size = len(ai | aj)
                jaccard = overlap / union_size if union_size > 0 else 0.0
                cosine_score = (
                    _cosine(ci, centroids[kj])
                    if ci is not None and centroids.get(kj) is not None
                    else 0.0
                )
                jac_ok = jaccard >= self._jaccard_threshold
                cos_ok = cosine_score >= self._cosine_threshold
                if jac_ok and cos_ok:
                    union(ki, kj)
                    n_edges += 1
                    reasons["and_passed"] += 1
                elif jac_ok and not cos_ok:
                    reasons["blocked_cosine_below"] += 1
                elif cos_ok and not jac_ok:
                    reasons["blocked_jaccard_below"] += 1
                else:
                    reasons["blocked_both"] += 1

        # Same membership-size filter as v0.4.2: only equivalence
        # classes with >= 2 members get a merged canonical.
        self._merged.clear()
        members_by_root: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for k in keys:
            members_by_root.setdefault(find(k), []).append(k)
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


class IntrospectiveLazyConsensusProxy(LazyConsensusANDRuleProxy):
    """v0.4.4: lazy consensus with workload-adaptive thresholds.

    Inspects the distribution of cross-source pair scores during
    consolidate() and picks aggressive or conservative thresholds
    based on the observed structure. The goal: match the best
    manually-tuned v0.4.x on each workload without user input.

    Heuristic:
    1. Compute alias-overlap counts across all cross-source pairs
       that pass the min_aliases gate.
    2. Count "strong" pairs (overlap >= 2 AND embedding cosine >= 0.85
       AND Jaccard >= 0.5). These are confident multi-evidence
       global-stratum matches.
    3. If the strong-pair density (strong / total considered) exceeds
       `strong_density_aggressive_threshold` (default 0.02), the
       workload looks global-stratum-heavy; relax min_aliases to 1
       so single-alias singletons can also participate in merging.
       Otherwise stay at the conservative min_aliases.

    The classification is a one-shot decision per consolidate() call,
    not adaptive within a single consolidation. For workloads that
    shift character over time, re-running consolidate after every
    epoch lets the variant re-pick.

    Reports the classification + chosen thresholds in the consolidate
    summary so the runner can log it.
    """

    name = "embed-proxy-v0.4.4-adaptive"

    def __init__(
        self,
        inner_factory=None,
        alias_jaccard_threshold: float = 0.5,
        embedding_cosine_threshold: float = 0.85,
        conservative_min_aliases: int = 2,
        conservative_min_overlap: int = 2,
        aggressive_min_aliases: int = 1,
        # Bug-fix 2026-06-06: aggressive_min_overlap raised from 1 to 2.
        # min_overlap=1 produced 100% false merges on SYNTH multi-tenant
        # Tier B because any two cross-source clusters sharing their
        # single common surface form (e.g. sales "Account" and finance
        # "Account") would trigger a merge despite having different
        # oracle canonicals. See docs/finding-multitenant-tier-b.md Bug 2.
        aggressive_min_overlap: int = 2,
        strong_density_aggressive_threshold: float = 0.02,
    ):
        super().__init__(
            inner_factory=inner_factory,
            alias_jaccard_threshold=alias_jaccard_threshold,
            embedding_cosine_threshold=embedding_cosine_threshold,
            min_aliases_for_merge=conservative_min_aliases,
            min_overlap_for_merge=conservative_min_overlap,
        )
        self._conservative_min_aliases = conservative_min_aliases
        self._conservative_min_overlap = conservative_min_overlap
        self._aggressive_min_aliases = aggressive_min_aliases
        self._aggressive_min_overlap = aggressive_min_overlap
        self._strong_density_threshold = strong_density_aggressive_threshold

    def consolidate(self) -> dict:
        """Two-phase consolidate: classify workload first, then merge."""
        keys = list(self._aliases.keys())
        centroids = {k: self._centroid(k) for k in keys}

        # Phase 1: classify workload using overlap>=2 + jaccard>=0.5 +
        # cosine>=0.85 as the "strong evidence" signal. Considers pairs
        # at the conservative min_aliases gate.
        n_total = 0
        n_strong = 0
        for i in range(len(keys)):
            ki = keys[i]
            ai = self._aliases[ki]
            if len(ai) < self._conservative_min_aliases:
                continue
            ci = centroids.get(ki)
            for j in range(i + 1, len(keys)):
                kj = keys[j]
                if ki[0] == kj[0]:
                    continue
                aj = self._aliases[kj]
                if len(aj) < self._conservative_min_aliases:
                    continue
                n_total += 1
                overlap = len(ai & aj)
                if overlap < 2:
                    continue
                union_size = len(ai | aj)
                jaccard = overlap / union_size if union_size > 0 else 0.0
                if jaccard < self._jaccard_threshold:
                    continue
                if ci is None or centroids.get(kj) is None:
                    continue
                if _cosine(ci, centroids[kj]) < self._cosine_threshold:
                    continue
                n_strong += 1

        density = n_strong / n_total if n_total > 0 else 0.0

        if density >= self._strong_density_threshold:
            classification = "global_stratum_heavy"
            self._min_aliases = self._aggressive_min_aliases
            self._min_overlap = self._aggressive_min_overlap
        else:
            classification = "ambiguity_heavy"
            self._min_aliases = self._conservative_min_aliases
            self._min_overlap = self._conservative_min_overlap

        # Phase 2: run the inherited AND-rule consolidate with the
        # picked settings.
        result = super().consolidate()
        result["adaptive_classification"] = classification
        result["adaptive_strong_density"] = density
        result["adaptive_min_aliases_chosen"] = self._min_aliases
        result["adaptive_min_overlap_chosen"] = self._min_overlap
        return result


class SingletonAwareLazyProxy(IntrospectiveLazyConsensusProxy):
    """v0.5.x singleton-aware lazy consensus.

    Addresses the Stack Overflow regression: on workloads where each
    source's (source, local) clusters are mostly singletons (one alias
    each), v0.4.4's strong-density check never fires and the variant
    over-isolates cross-source identical surface forms.

    Algorithm:
      1. Phase 1 (this class adds): Detect singleton-dominant clusters.
         If more than `singleton_density_threshold` (default 0.7) of
         (source, local) keys have exactly one alias, treat the workload
         as singleton-heavy.
      2. For singleton-heavy workloads: do an EXACT IDENTITY merge pass.
         Group all (source, local) keys whose single alias is the same
         exact string into one merged canonical. This recovers b-raw's
         identity-clustering wins while staying within the variant
         framework (the merge map records which sources contributed).
      3. Phase 2 (inherited): run the introspective adaptive consolidate
         on the remaining multi-alias clusters using the parent's logic.

    Tradeoffs:
      - Identity merging is by-definition safe: same exact string is
        the strongest possible signal of same entity.
      - It does not help when sources use different surface forms for
        the same entity (the multi-alias case). For those, the parent
        class's introspective adaptive logic still runs.

    Validation: should fix W-STACKOVERFLOW-MT regression while
    preserving all v0.4.4 wins on workloads where it currently performs
    well.
    """

    name = "embed-proxy-v0.5.3-singleton-aware"

    def __init__(
        self,
        inner_factory=None,
        alias_jaccard_threshold: float = 0.5,
        embedding_cosine_threshold: float = 0.85,
        conservative_min_aliases: int = 2,
        conservative_min_overlap: int = 2,
        aggressive_min_aliases: int = 1,
        aggressive_min_overlap: int = 2,
        strong_density_aggressive_threshold: float = 0.02,
        singleton_density_threshold: float = 0.7,
    ):
        super().__init__(
            inner_factory=inner_factory,
            alias_jaccard_threshold=alias_jaccard_threshold,
            embedding_cosine_threshold=embedding_cosine_threshold,
            conservative_min_aliases=conservative_min_aliases,
            conservative_min_overlap=conservative_min_overlap,
            aggressive_min_aliases=aggressive_min_aliases,
            aggressive_min_overlap=aggressive_min_overlap,
            strong_density_aggressive_threshold=strong_density_aggressive_threshold,
        )
        if not 0 < singleton_density_threshold <= 1:
            raise ValueError("singleton_density_threshold must be in (0, 1]")
        self._singleton_density_threshold = singleton_density_threshold

    def consolidate(self) -> dict:
        keys = list(self._aliases.keys())
        if not keys:
            return super().consolidate()

        # Detect singleton density UP FRONT (parent's consolidate doesn't
        # touch _aliases, only _merged).
        singleton_count = sum(1 for k in keys if len(self._aliases[k]) == 1)
        singleton_density = singleton_count / len(keys)
        is_singleton_heavy = singleton_density >= self._singleton_density_threshold

        # Phase A: run the inherited adaptive consolidate first. It
        # clears _merged and populates it for keys that win an AND-rule
        # merge. Multi-alias clusters get their merge decisions made here.
        parent_result = super().consolidate()

        # Phase B: now add singleton-aware identity merges and
        # promotions for keys the parent's consolidate did NOT already
        # assign to a merge group.
        identity_merges = 0
        identity_promotions = 0
        identity_blocked_by_disambig = 0
        if is_singleton_heavy:
            # Per-source map: which local canonicals exist? Used to detect
            # whether a source has multiple related cluster keys for the
            # same surface form (signal that the source disambiguates and
            # we should NOT identity-merge).
            per_source_locals: dict[str, list[str]] = {}
            for src, local in keys:
                per_source_locals.setdefault(src, []).append(local)

            def _has_disambig_signal(source: str, alias: str) -> bool:
                """Source has other cluster keys whose local canonical
                shares a substring with the alias. Implies the source
                distinguishes among variants of this surface."""
                lower_alias = alias.lower()
                for local in per_source_locals.get(source, []):
                    if local == alias:
                        continue
                    lower_local = local.lower()
                    if lower_alias in lower_local or lower_local in lower_alias:
                        return True
                return False

            alias_to_keys: dict[str, list[tuple[str, str]]] = {}
            for k in keys:
                if k in self._merged:
                    continue  # parent already decided this key's canonical
                aliases = self._aliases[k]
                if len(aliases) != 1:
                    continue
                only_alias = next(iter(aliases))
                alias_to_keys.setdefault(only_alias, []).append(k)
            for alias, member_keys in alias_to_keys.items():
                # Disambig check: if ANY member's source has other
                # cluster keys related to this alias, the singleton-
                # identity merge is unsafe (the sources care about
                # variants of this surface form).
                if any(_has_disambig_signal(k[0], alias) for k in member_keys):
                    identity_blocked_by_disambig += 1
                    continue
                if len(member_keys) >= 2:
                    merged_name = f"merged-identity::{alias}"
                    for k in member_keys:
                        self._merged[k] = merged_name
                    identity_merges += 1
                else:
                    k = member_keys[0]
                    self._merged[k] = alias
                    identity_promotions += 1

        parent_result["singleton_density"] = singleton_density
        parent_result["singleton_aware_active"] = is_singleton_heavy
        parent_result["identity_merges"] = identity_merges
        parent_result["identity_promotions"] = identity_promotions
        parent_result["identity_blocked_by_disambig"] = identity_blocked_by_disambig
        return parent_result


class MultiTenantANNSingletonAwareLazyProxy(SingletonAwareLazyProxy):
    """v0.5.7: SingletonAwareLazyProxy (v0.5.3) but every per-source
    inner is an ANN-backed proxy (v0.5.5) instead of the linear-scan
    v0.3.1.

    This extends the v0.5.5 scaling fix to the multi-tenant generation.
    Each source maintains its own inner variant; without ANN the
    per-source inner does an O(K_source) linear cosine scan on every
    write. At production K (per-source K > a few thousand) that
    collapses throughput the same way the single-tenant v0.3.1 did
    pre-v0.5.5.

    The v0.5.7 inner is HNSW-backed (when hnswlib is installed); falls
    back to numpy linear scan otherwise. All cross-source consensus,
    singleton-aware identity merging, and disambig safety checks from
    v0.5.3 are inherited unchanged.
    """

    name = "embed-proxy-v0.5.7-mt-ann"

    def __init__(self, inner_factory=None, **kwargs):
        if inner_factory is None:
            from .embed_proxy import ANNSchemaProxy

            inner_factory = ANNSchemaProxy
        super().__init__(inner_factory=inner_factory, **kwargs)


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
