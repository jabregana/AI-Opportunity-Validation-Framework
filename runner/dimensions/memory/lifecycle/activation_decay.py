"""gc-v0.2.2-activation-decay: collect nodes that haven't been queried
in a while and don't have enough historical query traffic to justify
keeping.

Analog of v0.1.7's tuned-entity rule but designed for graph-native
shapes. Reads `state.last_access` (per-node last-query timestamp) and
`state.query_count` (per-node cumulative queries). Both fields already
exist in GraphState and get updated by the runner / adapter as queries
land.

Default thresholds (per the local-model-conservative profile baseline):
  window_seconds        60 days (last query must be more recent)
  min_query_count       3 (historical query traffic floor)

A node is kept if EITHER:
  - it was queried in the last window_seconds, OR
  - it has at least min_query_count lifetime queries

Both conditions must fail (cold AND low-traffic) for collection.

Skips nodes with `invalid_at` set; those are v0.2.1's territory. The
v0.2.5 bundle composes both rules.
"""
from __future__ import annotations

from .base import GCVariant, GraphState


class ActivationDecayGC(GCVariant):
    """v0.2.2: collect cold + low-traffic nodes."""

    name = "gc-v0.2.2-activation-decay"

    def __init__(
        self,
        window_seconds: float = 60 * 86400.0,
        min_query_count: int = 3,
    ) -> None:
        self.window_seconds = window_seconds
        self.min_query_count = min_query_count

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
        # Skip nodes that have invalid_at set (handled by v0.2.1)
        if node.get("invalid_at") is not None:
            return False
        last_query = state.last_access.get(node_id, 0.0)
        query_count = state.query_count.get(node_id, 0)
        recently_queried = (current_time - last_query) < self.window_seconds
        well_used = query_count >= self.min_query_count
        # Keep if EITHER condition holds; collect only when both fail
        return not (recently_queried or well_used)
