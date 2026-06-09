"""gc-v0.2.3-evidence-count: never collect entity nodes; collect
fact / episode / mention nodes (evidence) when newer evidence about
the same entity already exists.

The intuition: in a knowledge graph, ENTITIES are the long-lived
canonical things (a company, a person, a product). EVIDENCE NODES
(episodes, mentions, source documents) are the data that supports
what is known about an entity. Old evidence becomes redundant when
newer evidence supersedes it for the same entity.

This variant preserves all entity nodes and collects evidence nodes
where:
  - kind in {"fact", "episode", "mention"}, AND
  - age >= min_age_seconds, AND
  - some newer evidence exists referencing AT LEAST ONE of the same
    entities (i.e., the entity has more recent supporting evidence)

`min_age_seconds` defaults to 30 days to avoid collecting evidence
before steady-state queries can hit it.
"""
from __future__ import annotations

from .base import GCVariant, GraphState


EVIDENCE_KINDS = frozenset({"fact", "episode", "mention"})


class EvidenceCountGC(GCVariant):
    """v0.2.3: keep entities; collect superseded evidence nodes."""

    name = "gc-v0.2.3-evidence-count"

    def __init__(self, min_age_seconds: float = 30 * 86400.0) -> None:
        self.min_age_seconds = min_age_seconds

    def _entities_supported_by(self, node_id: str, state: GraphState) -> set[str]:
        """Return the set of entity nodes connected to this evidence node."""
        entities: set[str] = set()
        for (src, dst) in state.edges:
            if src == node_id:
                other = dst
            elif dst == node_id:
                other = src
            else:
                continue
            node = state.nodes.get(other)
            if node and node.get("kind") == "entity":
                entities.add(other)
        return entities

    def _has_newer_evidence_for(
        self,
        node_id: str,
        node_added_at: float,
        target_entities: set[str],
        state: GraphState,
    ) -> bool:
        """True if some other evidence node younger than node_added_at
        also references at least one of the target_entities."""
        if not target_entities:
            return False
        for other_id, other in state.nodes.items():
            if other_id == node_id:
                continue
            if other.get("kind") not in EVIDENCE_KINDS:
                continue
            if other.get("added_at", 0.0) <= node_added_at:
                continue
            other_entities = self._entities_supported_by(other_id, state)
            if other_entities & target_entities:
                return True
        return False

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
        # Never collect entities
        if node.get("kind") == "entity":
            return False
        # Only handle known evidence kinds
        if node.get("kind") not in EVIDENCE_KINDS:
            return False
        added_at = node.get("added_at", current_time)
        if (current_time - added_at) < self.min_age_seconds:
            return False
        target_entities = self._entities_supported_by(node_id, state)
        return self._has_newer_evidence_for(node_id, added_at, target_entities, state)
