"""Conservative-entity tuned GC (v0.1.7).

Addresses the v0.1.4 over-collection issue surfaced in the differentiated
Stage 2 finding: v0.1.4 collects non-dormant entities whose queries
cluster early in the workload period (the 60-day-unaccessed threshold
fires on entities that were queried at day 30-40 of a 120-day workload).

v0.1.7 adds a secondary condition: entity must have `query_count < N`
(default 3). This protects entities that have been queried multiple
times (probably real, just quiet recently) while still collecting
truly dormant entities (zero or very few queries throughout the
workload).

Inherits ConservativeEntityPlusFactGC; overrides should_collect only
on the entity path.
"""
from __future__ import annotations

from .base import GraphState
from .conservative_entity import ConservativeEntityPlusFactGC


class ConservativeEntityTunedGC(ConservativeEntityPlusFactGC):
    """v0.1.7: ConservativeEntityPlusFactGC + query_count secondary gate."""

    name = "gc-v0.1.7-conservative-entity-tuned"

    def __init__(
        self,
        min_age_seconds: float = 86400.0,
        min_unaccessed_seconds: float = 60.0 * 86400,
        min_observation_seconds: float = 30.0 * 86400,
        min_query_count: int = 3,
    ):
        super().__init__(
            min_age_seconds=min_age_seconds,
            min_unaccessed_seconds=min_unaccessed_seconds,
            min_observation_seconds=min_observation_seconds,
        )
        self.min_query_count = min_query_count

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        # Defer to parent for the orphan + age + unaccessed checks
        if not super().should_collect(node_id, state, current_time):
            return False
        # Parent said yes. For entities, also check query_count.
        node = state.nodes.get(node_id)
        if node and node.get("kind") == "entity":
            qc = state.query_count.get(node_id, 0)
            if qc >= self.min_query_count:
                return False  # entity has been queried; keep it
        return True
