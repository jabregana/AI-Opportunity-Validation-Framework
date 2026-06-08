"""GCVariant ABC and the GraphState the variants operate on.

Mirrors the pattern from runner/variants/base.py for schema-alignment
variants. A GCVariant exposes four hooks:

  on_write_edge(src, dst, state, t)   - called when a new edge is written
  on_remove_edge(src, dst, state, t)  - called when an edge is removed
  should_collect(node_id, state, t)   - decision: collect this node now?
  collect(node_id, state)             - remove the node + its edges

Plus a default collect_candidates(state, t) helper that walks all nodes
and returns the ones should_collect says to collect. Variants can
override this for efficiency (incremental candidate tracking).

State is shared across the harness and the variant. Variants own the
should_collect decision; the runner owns event application and the
overall lifecycle.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class GraphState:
    """The graph state a GC variant sees and may mutate via collect().

    Fields:
      nodes: node_id -> dict with at least "kind" and "added_at"
      edges: (src, dst) -> integer count (multigraph; usually 1)
      in_degree: node_id -> int (number of incoming edges)
      out_degree: node_id -> int (number of outgoing edges)
      last_access: node_id -> float (timestamp of last query)
      query_count: node_id -> int (cumulative queries hitting this node)
      pinned: set of node_ids that must never be collected
    """

    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[tuple[str, str], int] = field(default_factory=dict)
    in_degree: dict[str, int] = field(default_factory=dict)
    out_degree: dict[str, int] = field(default_factory=dict)
    last_access: dict[str, float] = field(default_factory=dict)
    query_count: dict[str, int] = field(default_factory=dict)
    pinned: set[str] = field(default_factory=set)


class GCVariant(ABC):
    """A graph-GC variant.

    Variants decide which nodes to collect from the current GraphState.
    They are called by the runner on each event and at the end of
    processing for a final sweep.

    The name attribute is the variant id used in the FACTORIES registry
    and in artifact outputs.
    """

    name: str = "unnamed-gc-variant"

    @abstractmethod
    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        """Decision: should this node be collected at current_time?"""
        raise NotImplementedError

    def on_write_edge(
        self,
        src: str,
        dst: str,
        state: GraphState,
        current_time: float,
    ) -> None:
        """Hook called after the runner applies an add_edge event.
        Default: no-op (the runner already updated in_degree)."""
        return

    def on_remove_edge(
        self,
        src: str,
        dst: str,
        state: GraphState,
        current_time: float,
    ) -> None:
        """Hook called after the runner applies a remove_edge event.
        Default: no-op."""
        return

    def collect_candidates(
        self,
        state: GraphState,
        current_time: float,
    ) -> list[str]:
        """Default sweep: walk all nodes, return those should_collect
        approves. Override for incremental candidate tracking at scale."""
        return [
            nid for nid in list(state.nodes)
            if self.should_collect(nid, state, current_time)
        ]

    def collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float = 0.0,
    ) -> int:
        """Remove `node_id` and all its incident edges.

        `current_time` is the sweep time at which collection is
        happening. The base implementation does not use it. Tombstone
        variants record it as the collection moment so the TTL window
        is measured from the actual collection time, not from a proxy
        like state.last_access.

        Refuses to collect pinned nodes (returns 0). Returns the
        number of edges removed.
        """
        if node_id in state.pinned:
            return 0
        if node_id not in state.nodes:
            return 0
        n_edges_removed = 0
        # Remove all edges incident to this node and decrement the
        # appropriate degree of the other endpoint.
        for (src, dst) in list(state.edges):
            if src == node_id or dst == node_id:
                state.edges.pop((src, dst))
                n_edges_removed += 1
                if dst != node_id and dst in state.in_degree:
                    state.in_degree[dst] = max(0, state.in_degree[dst] - 1)
                if src != node_id and src in state.out_degree:
                    state.out_degree[src] = max(0, state.out_degree[src] - 1)
        state.nodes.pop(node_id, None)
        state.in_degree.pop(node_id, None)
        state.out_degree.pop(node_id, None)
        state.last_access.pop(node_id, None)
        state.query_count.pop(node_id, None)
        return n_edges_removed
