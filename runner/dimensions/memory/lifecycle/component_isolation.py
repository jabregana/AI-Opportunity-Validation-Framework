"""gc-v0.2.0-component-isolation: graph-topology-aware GC for edge-rich graphs.

The v0.1.x family rules (in_degree == 0 orphan check) never trigger on
Graphiti's edge-rich graphs because entities are always connected by
edges. See docs/finding-graphiti-f1-stage5.md for the architectural
finding. v0.2.0 is the first of the v0.2.x family designed to operate
on graph topology rather than orphan-node assumption.

Rule: detect connected components in the undirected projection of the
graph; for each component, find the most-recent query timestamp across
all nodes in it; collect every node in components whose most-recent
query is older than `min_component_idle_seconds`. Pinned nodes anchor
their entire component (never collected).

This is the equivalent of v0.1.2's fact-only rule (single-axis sweep)
but operating at component granularity rather than per-node orphan
detection.

Algorithm complexity per sweep:
  - Connected-component detection via BFS: O(V + E)
  - Per-component idle-time computation: O(V)
  - Collection: O(V_stale + E_incident)
Total: O(V + E). For million-node graphs this needs incremental
component tracking; for now the simple per-sweep traversal is fine.
"""
from __future__ import annotations
from collections import deque

from .base import GCVariant, GraphState


class ComponentIsolationGC(GCVariant):
    """v0.2.0: collect whole components that haven't been queried recently.

    Default: collect components whose most-recent query is more than
    30 days old. Configurable per domain profile (see docs/opportunity-
    v0.2.x-graph-topology-gc.md for the 5 starter profiles).
    """

    name = "gc-v0.2.0-component-isolation"

    def __init__(
        self,
        min_component_idle_seconds: float = 30 * 86400.0,
        min_component_age_seconds: float = 7 * 86400.0,
    ) -> None:
        """
        Args:
          min_component_idle_seconds: a component is collectable when its
            most-recent query is older than now - this threshold. Default
            30 days (matches v0.1.7's entity rule conservatism but at
            component granularity).
          min_component_age_seconds: a component must be at least this old
            (oldest added_at within the component vs now) before becoming
            collectable. Default 7 days. Prevents collecting brand-new
            isolated subgraphs that haven't had time to be queried yet.
        """
        self.min_component_idle_seconds = min_component_idle_seconds
        self.min_component_age_seconds = min_component_age_seconds

    def _connected_components(self, state: GraphState) -> list[set[str]]:
        """Find connected components in the undirected projection of state.

        Treats edges as undirected (Graphiti edges are directed but for
        component detection the direction doesn't matter). Returns a list
        of node-id sets, one per component.
        """
        # Build adjacency (undirected)
        adj: dict[str, set[str]] = {n: set() for n in state.nodes}
        for (src, dst) in state.edges:
            if src in adj and dst in adj:
                adj[src].add(dst)
                adj[dst].add(src)
        visited: set[str] = set()
        components: list[set[str]] = []
        for start in state.nodes:
            if start in visited:
                continue
            # BFS
            component: set[str] = set()
            queue = deque([start])
            while queue:
                node = queue.popleft()
                if node in visited:
                    continue
                visited.add(node)
                component.add(node)
                queue.extend(neighbor for neighbor in adj[node] if neighbor not in visited)
            components.append(component)
        return components

    def collect_candidates(
        self,
        state: GraphState,
        current_time: float,
    ) -> list[str]:
        """Override the default per-node walk with component-level sweep.

        For each connected component:
          - If any node is pinned, the whole component is preserved.
          - If the most-recent query across the component is older than
            min_component_idle_seconds AND the component is older than
            min_component_age_seconds, every node in the component
            becomes a collection candidate.
        """
        candidates: list[str] = []
        for component in self._connected_components(state):
            if any(n in state.pinned for n in component):
                continue
            # Most-recent query across the component
            recent_query = max(
                (state.last_access.get(n, 0.0) for n in component),
                default=0.0,
            )
            if (current_time - recent_query) <= self.min_component_idle_seconds:
                continue
            # Oldest added_at across the component
            oldest_added = min(
                (state.nodes[n].get("added_at", current_time) for n in component
                 if n in state.nodes),
                default=current_time,
            )
            if (current_time - oldest_added) < self.min_component_age_seconds:
                continue
            candidates.extend(component)
        return candidates

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        """Per-node check (used when callers don't go through the
        component-level sweep). Less efficient than collect_candidates;
        provided for compatibility with the GCVariant ABC."""
        for component in self._connected_components(state):
            if node_id not in component:
                continue
            if any(n in state.pinned for n in component):
                return False
            recent_query = max(
                (state.last_access.get(n, 0.0) for n in component),
                default=0.0,
            )
            if (current_time - recent_query) <= self.min_component_idle_seconds:
                return False
            oldest_added = min(
                (state.nodes[n].get("added_at", current_time) for n in component
                 if n in state.nodes),
                default=current_time,
            )
            if (current_time - oldest_added) < self.min_component_age_seconds:
                return False
            return True
        return False
