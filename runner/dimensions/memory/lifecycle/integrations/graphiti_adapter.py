"""Graphiti integration adapter for the GC lifecycle dimension.

Translates the `GCIntegrationShim` contract into Graphiti API calls.
Graphiti is graph-native (nodes + edges + episodes) and async-first,
so this adapter wraps async Graphiti calls in `asyncio.run()` to
keep the sync `GCIntegrationShim` contract.

Use:

    from graphiti_core import Graphiti
    from runner.dimensions.memory.lifecycle import build
    from runner.dimensions.memory.lifecycle.integrations import GraphitiGCMiddleware

    graphiti = Graphiti(uri="bolt://localhost:7687", user="neo4j", password="...")
    await graphiti.build_indices_and_constraints()

    variant = build("gc-v0.1.8-comprehensive-tuned")
    mw = GraphitiGCMiddleware(graphiti)

    # Drop-in for graphiti.add_episode / search
    mw.add_episode(name="ep-1", episode_body="User likes coffee...",
                   group_id="user_a")
    results = mw.search("preferences", group_ids=["user_a"])

    # Periodic sweep deletes stale nodes per the variant's policy
    n_removed = mw.sweep(variant, current_time=time.time())

Graphiti differences from Mem0 (worth knowing for adapter behavior):

  - Graphiti has explicit entity_nodes + entity_edges. Variants that
    differentiate facts vs entities (v0.1.4 / v0.1.7 / v0.1.8) get
    REAL signal here, unlike Mem0 v2's flat memory model.
  - Graphiti uses group_id for multi-tenant separation, which the
    adapter maps onto our tenant_id concept (v0.1.5 / v0.1.6 / v0.1.8
    tenant_pin API).
  - Graphiti exposes timestamps (reference_time, created_at) on
    nodes / edges so the adapter does NOT need a separate sidecar
    for added_at; it reads from Graphiti directly.
  - Graphiti's search returns nodes + edges; the adapter records
    queries against both.

Phase 2 of the synthesis-memory-lifecycle-management.md plan.
Real-Graphiti smoke test deferred until graphiti-core is installed.
"""
from __future__ import annotations
import asyncio
import time as _time
from dataclasses import dataclass, field
from typing import Any

from ..base import GraphState
from .base import GCIntegrationShim, IntegrationStats


@dataclass
class GraphitiNodeRecord:
    """Per-node metadata the middleware tracks.

    Most of this comes from Graphiti directly (created_at, kind).
    The adapter adds `last_access` and `query_count` which Graphiti
    does not track natively.
    """

    node_id: str
    kind: str = "entity"  # entity or episode (treat episode as fact)
    added_at: float = 0.0
    last_access: float = 0.0
    query_count: int = 0
    group_id: str | None = None  # used as tenant_id


_PERSISTENT_LOOP = None


def _get_persistent_loop():
    """Lazily create a single event loop that lives for the process.

    Graphiti caches httpx + Neo4j driver clients tied to the loop
    they were first instantiated under. asyncio.run() creates AND
    closes a fresh loop per call, which leaves those cached clients
    pointing at a dead loop and produces:
      'got Future attached to a different loop'
    on the second call. A persistent loop avoids that.
    """
    global _PERSISTENT_LOOP
    if _PERSISTENT_LOOP is None or _PERSISTENT_LOOP.is_closed():
        _PERSISTENT_LOOP = asyncio.new_event_loop()
    return _PERSISTENT_LOOP


def _run_async(coro):
    """Run an async coroutine synchronously.

    Uses a process-wide persistent event loop (see _get_persistent_loop)
    so cached async clients survive across calls. Falls back to a
    threaded asyncio.run if called from inside a running loop.
    """
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is not None and not running.is_closed():
        # Nested-loop case (called from inside async): thread-pool fallback
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(asyncio.run, coro)
            return future.result()
    return _get_persistent_loop().run_until_complete(coro)


class GraphitiGCMiddleware(GCIntegrationShim):
    """GC middleware around a Graphiti instance.

    The middleware maintains its own sidecar (`_records`) keyed by
    node_id (uuid string). Calls to add_episode / search update both
    Graphiti and the sidecar. The sweep method walks the sidecar,
    asks the variant which nodes to collect, and calls
    `graphiti.delete_node()` for each (or delete_episode if the
    candidate is an episode).
    """

    name = "graphiti-adapter"
    contract_version = 1

    def __init__(self, graphiti: Any):
        """`graphiti` is a Graphiti instance (or anything with the
        graphiti-core async API: add_episode/search/get_nodes_by_query/
        delete_node/delete_episode)."""
        self.graphiti = graphiti
        self._records: dict[str, GraphitiNodeRecord] = {}
        self._stats = IntegrationStats()
        self._pinned: set[str] = set()
        # Track edges separately so the variants' out_degree / in_degree
        # rules apply correctly. Each edge is (src_uuid, dst_uuid).
        self._edges: set[tuple[str, str]] = set()
        self._in_degree: dict[str, int] = {}
        self._out_degree: dict[str, int] = {}

    # ---- Graphiti API interception ----

    def add_episode(self, name: str, episode_body: str, *,
                    group_id: str = "", reference_time=None,
                    **kwargs) -> Any:
        """Add an episode via Graphiti; record the new nodes + edges.

        Returns Graphiti's add_episode result (an `AddEpisodeResults`
        object with `episode`, `nodes`, `edges` attributes per
        graphiti-core's documented shape).
        """
        result = _run_async(self.graphiti.add_episode(
            name=name, episode_body=episode_body,
            group_id=group_id, reference_time=reference_time,
            **kwargs,
        ))
        now = _time.time()
        # Record any new entity nodes
        for node in getattr(result, "nodes", []) or []:
            node_uuid = str(getattr(node, "uuid", None) or "")
            if not node_uuid:
                continue
            self.record_write(
                node_id=node_uuid, kind="entity",
                metadata={"group_id": group_id,
                          "name": getattr(node, "name", None)},
                t=now,
            )
        # Record the episode itself as a fact node
        episode = getattr(result, "episode", None)
        if episode is not None:
            ep_uuid = str(getattr(episode, "uuid", None) or "")
            if ep_uuid:
                self.record_write(
                    node_id=ep_uuid, kind="fact",
                    metadata={"group_id": group_id, "name": name},
                    t=now,
                )
        # Record edges (fact -> entity, in our model)
        for edge in getattr(result, "edges", []) or []:
            src = str(getattr(edge, "source_node_uuid", None) or "")
            dst = str(getattr(edge, "target_node_uuid", None) or "")
            if src and dst:
                self.record_edge(src, dst, t=now)
        return result

    def search(self, query: str, *, group_ids: list[str] | None = None,
               num_results: int = 10, **kwargs) -> Any:
        """Search via Graphiti; record query events against returned nodes."""
        result = _run_async(self.graphiti.search(
            query=query, group_ids=group_ids,
            num_results=num_results, **kwargs,
        ))
        now = _time.time()
        # Graphiti search returns a list of edges (per documented API)
        # Each edge references source_node_uuid and target_node_uuid
        items = result if isinstance(result, list) else getattr(result, "edges", [])
        for edge in items or []:
            for attr in ("source_node_uuid", "target_node_uuid"):
                node_uuid = str(getattr(edge, attr, None) or "")
                if node_uuid:
                    self.record_query(node_uuid, t=now)
        return result

    def get_nodes_by_query(self, query: str, **kwargs) -> Any:
        """Pass through; record query events against returned nodes."""
        result = _run_async(self.graphiti.get_nodes_by_query(
            query=query, **kwargs,
        ))
        now = _time.time()
        for node in result or []:
            node_uuid = str(getattr(node, "uuid", None) or "")
            if node_uuid:
                self.record_query(node_uuid, t=now)
        return result

    # ---- GCIntegrationShim contract methods ----

    def record_write(
        self,
        node_id: str,
        kind: str,
        metadata: dict | None,
        t: float,
    ) -> None:
        group_id = (metadata or {}).get("group_id")
        self._records[node_id] = GraphitiNodeRecord(
            node_id=node_id, kind=kind,
            added_at=t, last_access=t, query_count=0,
            group_id=group_id,
        )
        self._in_degree.setdefault(node_id, 0)
        self._out_degree.setdefault(node_id, 0)
        self._stats.n_writes += 1

    def record_edge(self, src: str, dst: str, t: float) -> None:
        if (src, dst) in self._edges:
            return  # idempotent
        self._edges.add((src, dst))
        self._in_degree[dst] = self._in_degree.get(dst, 0) + 1
        self._out_degree[src] = self._out_degree.get(src, 0) + 1
        self._stats.n_edges_added += 1

    def record_remove_edge(self, src: str, dst: str, t: float) -> None:
        if (src, dst) not in self._edges:
            return
        self._edges.discard((src, dst))
        if dst in self._in_degree:
            self._in_degree[dst] = max(0, self._in_degree[dst] - 1)
        if src in self._out_degree:
            self._out_degree[src] = max(0, self._out_degree[src] - 1)
        self._stats.n_edges_removed += 1

    def record_query(self, node_id: str, t: float) -> None:
        rec = self._records.get(node_id)
        if rec is not None:
            rec.last_access = t
            rec.query_count += 1
        self._stats.n_queries += 1

    def pin(self, node_id: str) -> None:
        self._pinned.add(node_id)
        self._stats.n_pins += 1

    def get_state(self) -> GraphState:
        """Build a GraphState from the sidecar + edge tracking."""
        state = GraphState()
        for node_id, rec in self._records.items():
            state.nodes[node_id] = {
                "kind": rec.kind,
                "added_at": rec.added_at,
            }
            state.in_degree[node_id] = self._in_degree.get(node_id, 0)
            state.out_degree[node_id] = self._out_degree.get(node_id, 0)
            state.last_access[node_id] = rec.last_access
            state.query_count[node_id] = rec.query_count
        # Edges: copy the tracking set as a count dict
        for (src, dst) in self._edges:
            state.edges[(src, dst)] = state.edges.get((src, dst), 0) + 1
        state.pinned = set(self._pinned)
        return state

    def apply_sweep(self, node_ids_to_remove: list[str]) -> int:
        """Delete the chosen nodes from Graphiti + sidecar.

        Respects pinning. Calls graphiti.delete_node() for entity
        nodes and graphiti.delete_episode() for fact (episode) nodes.
        """
        self._stats.n_sweeps_invoked += 1
        self._stats.last_sweep_size_before = len(self._records)
        n_removed = 0
        for node_id in node_ids_to_remove:
            if node_id in self._pinned:
                continue
            if node_id not in self._records:
                continue
            rec = self._records[node_id]
            try:
                if rec.kind == "fact":
                    # In Graphiti, episodes (facts) deletion
                    _run_async(self.graphiti.delete_episode(uuid=node_id))
                else:
                    # Entity node deletion
                    _run_async(self.graphiti.delete_node(uuid=node_id))
                # Clean up sidecar + edges
                self._records.pop(node_id, None)
                # Drop any edges touching this node + update degrees
                for (src, dst) in list(self._edges):
                    if src == node_id or dst == node_id:
                        self._edges.discard((src, dst))
                        if dst != node_id and dst in self._in_degree:
                            self._in_degree[dst] = max(0, self._in_degree[dst] - 1)
                        if src != node_id and src in self._out_degree:
                            self._out_degree[src] = max(0, self._out_degree[src] - 1)
                self._in_degree.pop(node_id, None)
                self._out_degree.pop(node_id, None)
                n_removed += 1
            except Exception:
                # Graphiti may raise if node already deleted; swallow
                self._records.pop(node_id, None)
        self._stats.last_sweep_size_after = len(self._records)
        self._stats.n_nodes_actually_removed += n_removed
        return n_removed

    def stats(self) -> IntegrationStats:
        return self._stats

    # ---- Convenience: end-to-end sweep ----

    def sweep(self, variant, *, current_time: float | None = None) -> int:
        """Run one sweep cycle: ask the variant for candidates, apply.

        Calls `variant.collect(node_id, state, current_time)` for each
        candidate before deleting from Graphiti so tombstone variants
        record their internal sidecar.
        """
        t = current_time if current_time is not None else _time.time()
        state = self.get_state()
        candidates = variant.collect_candidates(state, t)
        for cand_id in candidates:
            variant.collect(cand_id, state, current_time=t)
        return self.apply_sweep(candidates)
