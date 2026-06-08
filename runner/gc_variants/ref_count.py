"""Reference-counted GC variants.

Three variants in this file:

  v0.1.0 RefCountGC: pure reference counting. Collect an entity node
    when its in_degree is 0 AND the node is older than min_age_seconds.
    Never collects fact nodes (those are the write-stream record).

  v0.1.1 RefCountUtilityGC: extends v0.1.0 with a utility-score rule.
    In addition to the orphan rule, also collect a node when its
    utility score drops below min_utility AND the node has been
    observed for at least min_observation_seconds. Utility combines
    recency, query frequency, and (implicitly) reference count.

  v0.1.2 FactOnlyGC: conservative-survival variant. Entities are
    NEVER collected (they are the long-lived semantically meaningful
    nodes). Only facts get collected, and only after all their
    outgoing edges have been removed AND the node is older than
    min_age_seconds. Introduced after Stage 2 baseline finding showed
    v0.1.0 and v0.1.1 collected 90% of entities (UC-GC-2 fail) while
    leaving facts untouched (only 2.2% store reduction).
    See docs/finding-gc-stage2-baseline.md for the analysis.
"""
from __future__ import annotations
import math

from .base import GCVariant, GraphState


class RefCountGC(GCVariant):
    """v0.1.0: in_degree==0 AND age > min_age_seconds means collect.

    The age guard prevents collecting an entity in the brief window
    before its first fact is written.
    """

    name = "gc-v0.1.0-ref-count"

    def __init__(self, min_age_seconds: float = 7 * 86400):
        self.min_age_seconds = min_age_seconds

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        if node_id in state.pinned:
            return False
        node = state.nodes.get(node_id)
        if node is None:
            return False
        # Reference counting applies only to entity nodes. Facts are
        # the write-stream record; they stay even after their edges
        # to entities have been removed.
        if node.get("kind") != "entity":
            return False
        age = current_time - node.get("added_at", current_time)
        if age < self.min_age_seconds:
            return False
        in_deg = state.in_degree.get(node_id, 0)
        return in_deg == 0


class RefCountUtilityGC(RefCountGC):
    """v0.1.1: RefCountGC plus a utility-score rule.

    Utility(node) = exp(-decay_rate * days_since_last_access)
                    * (1 + log(1 + query_count))

    If utility < min_utility AND age > min_observation_seconds, collect.

    The observation window prevents premature collection of newly-added
    nodes that have not yet had a chance to be queried.
    """

    name = "gc-v0.1.1-ref-count-utility"

    def __init__(
        self,
        min_age_seconds: float = 7 * 86400,
        min_utility: float = 0.05,
        utility_decay_per_day: float = 0.05,
        min_observation_seconds: float = 14 * 86400,
    ):
        super().__init__(min_age_seconds=min_age_seconds)
        self.min_utility = min_utility
        self.decay_per_day = utility_decay_per_day
        self.min_observation_seconds = min_observation_seconds

    def utility(self, node_id: str, state: GraphState, current_time: float) -> float:
        last = state.last_access.get(node_id, state.nodes.get(node_id, {}).get(
            "added_at", current_time))
        days_since = max(0.0, (current_time - last) / 86400.0)
        recency = math.exp(-self.decay_per_day * days_since)
        q = state.query_count.get(node_id, 0)
        return recency * (1.0 + math.log1p(q))

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        # Inherit the orphan rule first; if it fires, collect.
        if super().should_collect(node_id, state, current_time):
            return True
        # Utility rule: applies to entity nodes only, after observation
        # window.
        if node_id in state.pinned:
            return False
        node = state.nodes.get(node_id)
        if node is None or node.get("kind") != "entity":
            return False
        age = current_time - node.get("added_at", current_time)
        if age < self.min_observation_seconds:
            return False
        u = self.utility(node_id, state, current_time)
        return u < self.min_utility


class FactOnlyGC(GCVariant):
    """v0.1.2: conservative-survival GC that collects facts only.

    Rule: collect a fact node when all of its outgoing edges have been
    removed (state.out_degree[fact_id] == 0) AND the node is older
    than min_age_seconds (default 1 day, giving the fact a grace
    window to be queried before collection).

    Entity nodes are NEVER collected by this variant. The workload's
    conservative-survival philosophy says entities are the long-lived
    semantically meaningful nodes that should persist beyond the
    lifetime of any individual fact about them. A future variant
    (v0.1.3) can re-introduce entity collection with a tighter rule;
    v0.1.2 establishes the safe lower bound first.

    Stage 2 baseline finding (docs/finding-gc-stage2-baseline.md)
    showed that the largest store-reduction lever is fact collection:
    facts are ~98% of the store on the synthetic workload, and the
    earlier ref-count variants never collected them.
    """

    name = "gc-v0.1.2-fact-only"

    def __init__(self, min_age_seconds: float = 86400.0):
        # Default 1 day: gives the fact a chance to be queried after
        # its edges age out, before getting swept.
        self.min_age_seconds = min_age_seconds

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        if node_id in state.pinned:
            return False
        node = state.nodes.get(node_id)
        if node is None:
            return False
        if node.get("kind") != "fact":
            return False
        age = current_time - node.get("added_at", current_time)
        if age < self.min_age_seconds:
            return False
        out_deg = state.out_degree.get(node_id, 0)
        return out_deg == 0
