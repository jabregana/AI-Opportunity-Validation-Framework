"""v0.4.0 multi-tenant proxy: per-source namespace isolation.

Each source_id (team, user, tenant) gets its own inner variant instance
and its own canonical store. When source_id arrives in the context, the
proxy dispatches to that source's inner variant. Canonicals are
prefixed with the source_id ("sales::Apple_Inc") so the harness can
tell apart writes that happen to share an input string across sources.

This is the simplest correct architectural answer to the user's
scenario:

  "When a team of 8 is querying the same agent, 'Apple the company'
  might be authoritative from the sales team but ambiguous to the ops
  team who interacts with Apple the supplier and Apple the tech company
  in different contexts. The resolution engine now needs to track not
  just node identity but source identity."

Per-source isolation literally tracks source identity. Sales "Apple"
and ops "Apple" become distinct canonicals; they never alias.

Known limitation, surfaced by W-MULTITENANT-DEMO: this is too
aggressive on globally unambiguous entities. Sales "Microsoft" and ops
"Microsoft" both legitimately mean Microsoft_Corp; per-source isolation
keeps them apart. A v0.4.1 cross-source consensus variant would detect
unambiguous-across-sources entities and merge them into a "shared"
namespace.

Tracking the gap is intentional. v0.4.0 ships the architecture; v0.4.1
adds the smarter resolution policy.
"""
from __future__ import annotations
from typing import Callable

from .base import Variant


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
