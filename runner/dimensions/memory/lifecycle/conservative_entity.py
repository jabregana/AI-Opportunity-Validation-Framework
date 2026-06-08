"""Conservative entity-collection GC (v0.1.4).

Re-introduces entity collection (which v0.1.0 had but caused 90 percent
false-collection in the Stage 2 baseline finding) with a much tighter
rule: collect an entity only when ALL THREE conditions hold:

  1. in_degree == 0 (no current edges)
  2. last_access age > min_unaccessed_seconds (no recent queries)
  3. node age > min_observation_seconds (had time to be queried)

Plus: never collects pinned, never collects facts (v0.1.2's rule).

The motivation (from the v0.1.2 finding's deferred section): the original
'collect orphan entities after 7 days' rule was too aggressive because
entities with active queries also got collected. This variant requires
BOTH zero edges AND zero recent queries, which catches the genuine
'dormant entity' case without removing entities the system is still using.

Default thresholds:
  min_unaccessed_seconds = 60 * 86400 (60 days no queries)
  min_observation_seconds = 30 * 86400 (entity must exist 30 days before
                                        collection is even considered)
  min_age_seconds (inherited from FactOnlyGC) controls fact collection

This variant should ship as gc-v0.1.4-conservative-entity-plus-fact.
"""
from __future__ import annotations

from .base import GraphState
from .ref_count import FactOnlyGC


class ConservativeEntityPlusFactGC(FactOnlyGC):
    """v0.1.4: extends FactOnlyGC with tight entity-collection rule."""

    name = "gc-v0.1.4-conservative-entity-plus-fact"

    def __init__(
        self,
        min_age_seconds: float = 86400.0,
        min_unaccessed_seconds: float = 60.0 * 86400,
        min_observation_seconds: float = 30.0 * 86400,
    ):
        super().__init__(min_age_seconds=min_age_seconds)
        self.min_unaccessed_seconds = min_unaccessed_seconds
        self.min_observation_seconds = min_observation_seconds

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        # First check the inherited fact-collection rule
        if super().should_collect(node_id, state, current_time):
            return True

        # Then apply the conservative entity rule
        if node_id in state.pinned:
            return False
        node = state.nodes.get(node_id)
        if node is None or node.get("kind") != "entity":
            return False

        in_deg = state.in_degree.get(node_id, 0)
        if in_deg > 0:
            return False  # entity still has edges

        added_at = node.get("added_at", current_time)
        age = current_time - added_at
        if age < self.min_observation_seconds:
            return False  # entity too new

        last_access = state.last_access.get(node_id, added_at)
        unaccessed_age = current_time - last_access
        if unaccessed_age < self.min_unaccessed_seconds:
            return False  # entity queried recently

        return True
