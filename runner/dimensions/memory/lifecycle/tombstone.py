"""Fact-only GC with tombstone log (v0.1.3).

Extends FactOnlyGC (v0.1.2) with an internal tombstone log of recently-
collected fact ids. The collect() method records the (node_id,
collection_time) tuple before deletion; production code can query
`was_recently_collected(node_id, current_time)` to distinguish
"this fact was never in the store" from "this fact was collected
T seconds ago."

The motivation (from the Stage 3 finding's "what's not earned" list):
v0.1.2 has no over-collection recovery path. If a fact is collected
and a query for it arrives a minute later, the query fails. Tombstones
let the production layer say "this fact existed, was collected at T,
was about entity X; query the entity for related context."

Tombstones expire after `tombstone_ttl_seconds` (default 7 days). The
internal log is the variant's own state, not a field on GraphState, so
this variant slots cleanly into the existing factory + benchmark
infrastructure with no contract changes.

Adds two new fields to the runner's tracking (via collect side effects):
  - tombstones: dict[node_id, dict] with keys "collected_at" and any
    metadata snapshot the variant captured before delete
  - tombstone_eviction_count: how many tombstones have aged out

This variant ships as gc-v0.1.3-fact-only-tombstone.
"""
from __future__ import annotations

from .base import GraphState
from .ref_count import FactOnlyGC


class FactOnlyTombstoneGC(FactOnlyGC):
    """v0.1.3: FactOnlyGC + tombstone log for over-collection recovery.

    Same collection rule as v0.1.2 (collect facts with out_degree == 0
    AND age > min_age_seconds). Difference: records each collected
    node's metadata in an internal tombstone dict for production
    query-time consultation.
    """

    name = "gc-v0.1.3-fact-only-tombstone"

    def __init__(
        self,
        min_age_seconds: float = 86400.0,
        tombstone_ttl_seconds: float = 7 * 86400.0,
    ):
        super().__init__(min_age_seconds=min_age_seconds)
        self.tombstone_ttl = tombstone_ttl_seconds
        self.tombstones: dict[str, dict] = {}
        self.tombstone_eviction_count = 0

    def collect(self, node_id: str, state: GraphState) -> int:
        """Record tombstone before delegating to parent's collect."""
        # Capture metadata BEFORE deletion
        if node_id in state.nodes and node_id not in state.pinned:
            node_metadata = dict(state.nodes.get(node_id, {}))
            # Get the timestamp from the node's added_at or use last_access
            collected_at = state.last_access.get(node_id,
                                                 node_metadata.get("added_at", 0.0))
            self.tombstones[node_id] = {
                "collected_at": collected_at,
                "kind": node_metadata.get("kind"),
                "added_at": node_metadata.get("added_at"),
            }
        return super().collect(node_id, state)

    def was_recently_collected(
        self,
        node_id: str,
        current_time: float,
    ) -> bool:
        """Public query-time API for production use.

        Returns True if the node was collected within the tombstone TTL
        window. Production query code can call this to distinguish
        'never existed' from 'recently superseded.'
        """
        if node_id not in self.tombstones:
            return False
        collected_at = self.tombstones[node_id]["collected_at"]
        return (current_time - collected_at) <= self.tombstone_ttl

    def prune_expired_tombstones(self, current_time: float) -> int:
        """Remove tombstones older than tombstone_ttl_seconds.

        Returns the number of tombstones evicted. Production deployments
        should call this on the same cadence as the collection sweep.
        """
        expired = [
            nid for nid, t in self.tombstones.items()
            if (current_time - t["collected_at"]) > self.tombstone_ttl
        ]
        for nid in expired:
            del self.tombstones[nid]
        self.tombstone_eviction_count += len(expired)
        return len(expired)
