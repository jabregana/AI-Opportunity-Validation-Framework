"""gc-v0.2.4-supersession-tombstone: graph-native analog of v0.1.3.

When a fact is explicitly superseded (the downstream framework or the
synthetic workload records a `superseded_by` link to the newer fact),
this variant collects the old fact AND records a tombstone with its
id, kind, and the superseder's id. The tombstone is queryable via
`was_recently_collected(node_id, current_time)` so production code
can distinguish "this fact was never in the store" from "this fact
was superseded N seconds ago, here is what replaced it."

Pairs with v0.2.1-temporal-validity: v0.2.1 uses the downstream's own
`invalid_at` field; v0.2.4 uses explicit supersession events. The
v0.2.5 bundle composes both signals.

Tombstones expire after `tombstone_ttl_seconds` (default 7 days,
matching v0.1.3). Expired tombstones get pruned by
`prune_expired_tombstones`.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .base import GCVariant, GraphState


@dataclass
class Tombstone:
    """Record of a collected node's metadata for recovery queries."""

    node_id: str
    kind: str
    collected_at: float
    superseded_by: str | None = None  # if known


class SupersessionTombstoneGC(GCVariant):
    """v0.2.4: collect explicitly-superseded nodes; retain tombstones
    for recovery."""

    name = "gc-v0.2.4-supersession-tombstone"

    def __init__(
        self,
        tombstone_ttl_seconds: float = 7 * 86400.0,
        min_age_before_collect_seconds: float = 86400.0,
    ) -> None:
        self.tombstone_ttl_seconds = tombstone_ttl_seconds
        self.min_age_before_collect_seconds = min_age_before_collect_seconds
        self._tombstones: dict[str, Tombstone] = {}

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        if node_id in state.pinned:
            return False
        node = state.nodes.get(node_id)
        if not node:
            return False
        # Only collect nodes that have been explicitly superseded
        if node.get("superseded_by") is None:
            return False
        added_at = node.get("added_at", current_time)
        return (current_time - added_at) >= self.min_age_before_collect_seconds

    def collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float = 0.0,
    ) -> int:
        """Record tombstone before delegating to the base collect()."""
        node = state.nodes.get(node_id)
        if node and node_id not in state.pinned:
            self._tombstones[node_id] = Tombstone(
                node_id=node_id,
                kind=node.get("kind", "unknown"),
                collected_at=current_time,
                superseded_by=node.get("superseded_by"),
            )
        return super().collect(node_id, state, current_time)

    def was_recently_collected(
        self,
        node_id: str,
        current_time: float,
    ) -> Tombstone | None:
        """Return the tombstone if the node was collected within the
        TTL window, else None. Production code uses this to surface
        'this memory was recently superseded by X' to the agent."""
        tomb = self._tombstones.get(node_id)
        if tomb is None:
            return None
        if (current_time - tomb.collected_at) > self.tombstone_ttl_seconds:
            return None
        return tomb

    def prune_expired_tombstones(self, current_time: float) -> int:
        """Drop tombstones older than the TTL. Returns count pruned."""
        expired = [
            nid for nid, t in self._tombstones.items()
            if (current_time - t.collected_at) > self.tombstone_ttl_seconds
        ]
        for nid in expired:
            del self._tombstones[nid]
        return len(expired)
