"""MockGraphStoreShim: an in-memory shim that satisfies the
GCIntegrationShim contract.

Used for:
  - Verifying the shim contract end-to-end without a real downstream
    framework installed
  - Stage 4 architectural validation (running v0.1.2 through the shim
    against a known-good store and confirming the same UC gates pass
    as in the direct Stage 3 run)
  - Future concrete shim development (the mock is the reference
    implementation; a Graphiti or Mem0 shim must produce the same
    GraphState given the same recorded calls)

The mock's internal store shape mirrors Graphiti's per-graph storage:
  - nodes: id -> dict with at least "kind" and "added_at"
  - edges: (src, dst) -> count (multigraph)
Plus the bookkeeping that GraphState needs (in_degree, out_degree,
last_access, query_count, pinned).
"""
from __future__ import annotations
from dataclasses import dataclass, field

from ..base import GraphState
from .base import GCIntegrationShim, IntegrationStats


@dataclass
class _MockStore:
    """Internal storage matching the GraphState shape."""

    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[tuple[str, str], int] = field(default_factory=dict)
    in_degree: dict[str, int] = field(default_factory=dict)
    out_degree: dict[str, int] = field(default_factory=dict)
    last_access: dict[str, float] = field(default_factory=dict)
    query_count: dict[str, int] = field(default_factory=dict)
    pinned: set[str] = field(default_factory=set)


class MockGraphStoreShim(GCIntegrationShim):
    """Reference implementation of GCIntegrationShim.

    Keeps the GraphState incrementally maintained so get_state() is
    O(1). apply_sweep() refuses to remove pinned nodes and updates
    the other endpoint's degree counters when an incident edge is
    pulled.
    """

    name = "mock-graph-store"
    contract_version = 1

    def __init__(self):
        self._store = _MockStore()
        self._stats = IntegrationStats()

    def record_write(
        self,
        node_id: str,
        kind: str,
        metadata: dict | None,
        t: float,
    ) -> None:
        s = self._store
        meta = dict(metadata or {})
        meta["kind"] = kind
        meta["added_at"] = t
        s.nodes[node_id] = meta
        s.in_degree.setdefault(node_id, 0)
        s.out_degree.setdefault(node_id, 0)
        s.last_access.setdefault(node_id, t)
        s.query_count.setdefault(node_id, 0)
        self._stats.n_writes += 1

    def record_edge(self, src: str, dst: str, t: float) -> None:
        s = self._store
        key = (src, dst)
        s.edges[key] = s.edges.get(key, 0) + 1
        if dst in s.nodes:
            s.in_degree[dst] = s.in_degree.get(dst, 0) + 1
        if src in s.nodes:
            s.out_degree[src] = s.out_degree.get(src, 0) + 1
        self._stats.n_edges_added += 1

    def record_remove_edge(self, src: str, dst: str, t: float) -> None:
        s = self._store
        key = (src, dst)
        if key not in s.edges:
            return
        s.edges[key] -= 1
        if s.edges[key] <= 0:
            s.edges.pop(key)
            if dst in s.in_degree:
                s.in_degree[dst] = max(0, s.in_degree[dst] - 1)
            if src in s.out_degree:
                s.out_degree[src] = max(0, s.out_degree[src] - 1)
        self._stats.n_edges_removed += 1

    def record_query(self, node_id: str, t: float) -> None:
        s = self._store
        if node_id in s.nodes:
            s.last_access[node_id] = t
            s.query_count[node_id] = s.query_count.get(node_id, 0) + 1
        self._stats.n_queries += 1

    def pin(self, node_id: str) -> None:
        self._store.pinned.add(node_id)
        self._stats.n_pins += 1

    def get_state(self) -> GraphState:
        s = self._store
        # Return a fresh GraphState that aliases the underlying dicts.
        # The variant should not mutate this directly; it calls
        # apply_sweep() to commit changes via the shim.
        return GraphState(
            nodes=dict(s.nodes),
            edges=dict(s.edges),
            in_degree=dict(s.in_degree),
            out_degree=dict(s.out_degree),
            last_access=dict(s.last_access),
            query_count=dict(s.query_count),
            pinned=set(s.pinned),
        )

    def apply_sweep(self, node_ids_to_remove: list[str]) -> int:
        s = self._store
        self._stats.n_sweeps_invoked += 1
        self._stats.last_sweep_size_before = len(s.nodes)
        n_removed = 0
        for nid in node_ids_to_remove:
            if nid in s.pinned:
                continue
            if nid not in s.nodes:
                continue
            # Remove incident edges first, updating both endpoints'
            # degree counters
            for (src, dst) in list(s.edges):
                if src == nid or dst == nid:
                    s.edges.pop((src, dst))
                    if dst != nid and dst in s.in_degree:
                        s.in_degree[dst] = max(0, s.in_degree[dst] - 1)
                    if src != nid and src in s.out_degree:
                        s.out_degree[src] = max(0, s.out_degree[src] - 1)
            s.nodes.pop(nid, None)
            s.in_degree.pop(nid, None)
            s.out_degree.pop(nid, None)
            s.last_access.pop(nid, None)
            s.query_count.pop(nid, None)
            n_removed += 1
        self._stats.last_sweep_size_after = len(s.nodes)
        self._stats.n_nodes_actually_removed += n_removed
        return n_removed

    def stats(self) -> IntegrationStats:
        return self._stats
