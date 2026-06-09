"""gc-v0.2.1-temporal-validity: use the downstream framework's own
'this fact is no longer true' signal to collect superseded facts.

Graphiti exposes `valid_at` / `invalid_at` / `expired_at` on every
EntityEdge. When a newer fact contradicts an older one, Graphiti's
extraction layer sets `invalid_at` on the old fact's edges. This
variant reads that field directly: nodes whose `invalid_at` is set
and is older than `ttl_seconds` get collected.

For unit tests + synthetic workloads, the supersede event in
w_graph_lifecycle sets `invalid_at` on the node's dict so this
variant works without a real Graphiti backend.

This is the graph-native analog of v0.1.2's fact-only rule. v0.1.2
detected death-of-fact via `in_degree == 0` (last edge removed);
v0.2.1 detects it via `invalid_at` set on the fact directly. The
latter is the right signal for append-only graphs.
"""
from __future__ import annotations

from .base import GCVariant, GraphState


class TemporalValidityGC(GCVariant):
    """v0.2.1: collect facts whose validity window has expired more than
    `ttl_seconds` ago. Reads the node dict's `invalid_at` field.
    """

    name = "gc-v0.2.1-temporal-validity"

    def __init__(self, ttl_seconds: float = 7 * 86400.0) -> None:
        """
        Args:
          ttl_seconds: a fact becomes collectable when
            `current_time - node.invalid_at >= ttl_seconds`. Default 7 days
            (matches v0.1.3 tombstone TTL).
        """
        self.ttl_seconds = ttl_seconds

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
        invalid_at = node.get("invalid_at")
        if invalid_at is None:
            return False
        return (current_time - invalid_at) >= self.ttl_seconds
