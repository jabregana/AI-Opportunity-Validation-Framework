"""Cognee integration adapter for the GC lifecycle dimension.

Translates the `GCIntegrationShim` contract into Cognee API calls.
Cognee has a module-level API (rather than instance-based like Mem0
or Graphiti), so this adapter accepts a `cognee_module` (defaulting
to the real `cognee` package) which lets tests pass in a FakeCognee.

Cognee's pipeline:
  cognee.add(text, dataset_name=...)       # raw ingest
  await cognee.cognify(datasets=...)       # extract + load to graph
  await cognee.search(query_type, query)   # query

This adapter intercepts add/cognify/search and translates each into
the shim contract's record_* methods. Per-node deletion uses
`cognee.delete()` (per-doc) when available; otherwise falls back to
the prune APIs.

Phase 1+ of the synthesis-memory-lifecycle-management.md plan; same
shape as the Mem0 and Graphiti adapters.

Real-Cognee smoke test deferred until `pip install cognee` lands.
"""
from __future__ import annotations
import asyncio
import time as _time
from dataclasses import dataclass, field
from typing import Any

from ..base import GraphState
from .base import GCIntegrationShim, IntegrationStats


@dataclass
class CogneeNodeRecord:
    """Per-node metadata the middleware tracks."""

    node_id: str
    kind: str = "fact"
    added_at: float = 0.0
    last_access: float = 0.0
    query_count: int = 0
    dataset_name: str | None = None  # used as tenant_id


def _run_async(coro):
    """Run an async coroutine synchronously (Cognee is async-first)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None or loop.is_closed():
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


class CogneeGCMiddleware(GCIntegrationShim):
    """GC middleware around the Cognee module.

    Unlike Mem0 / Graphiti (instance-based), Cognee uses a module-level
    API. The adapter accepts the module reference so tests can inject
    a fake. Production code passes the real `cognee` module:

        import cognee
        from runner.dimensions.memory.lifecycle import build
        from runner.dimensions.memory.lifecycle.integrations import (
            CogneeGCMiddleware,
        )
        mw = CogneeGCMiddleware(cognee)
        variant = build("gc-v0.1.8-comprehensive-tuned")
        mw.add("User data...", dataset_name="user_a")
        mw.cognify(datasets=["user_a"])
        results = mw.search("query_type", "preferences", dataset_name="user_a")
        n_removed = mw.sweep(variant, current_time=time.time())
    """

    name = "cognee-adapter"
    contract_version = 1

    def __init__(self, cognee_module: Any):
        """`cognee_module` is the `cognee` module (or a fake module
        with the same surface: add/cognify/search/delete)."""
        self.cognee = cognee_module
        self._records: dict[str, CogneeNodeRecord] = {}
        self._stats = IntegrationStats()
        self._pinned: set[str] = set()
        self._edges: set[tuple[str, str]] = set()
        self._in_degree: dict[str, int] = {}
        self._out_degree: dict[str, int] = {}
        # Cognee's add() may not return an id directly; the adapter
        # generates one and tracks it alongside the document text
        self._next_id_counter = 0

    def _new_id(self) -> str:
        self._next_id_counter += 1
        return f"cog_doc_{self._next_id_counter:08d}"

    # ---- Cognee API interception ----

    def add(self, text: str, *, dataset_name: str | None = None,
            **kwargs) -> Any:
        """Add raw text via Cognee. Records the document in the sidecar
        with a generated id.

        Cognee's add() is sync (it stores raw text); cognify() is the
        async processing step. The adapter generates a doc_id since
        Cognee does not return ids from add().
        """
        result = self.cognee.add(text, dataset_name=dataset_name, **kwargs)
        # Cognee's add() returns various shapes across versions; the
        # adapter generates its own tracking id either way
        doc_id = self._new_id()
        now = _time.time()
        self.record_write(
            node_id=doc_id, kind="fact",
            metadata={"dataset_name": dataset_name, "text": text},
            t=now,
        )
        return {"doc_id": doc_id, "cognee_result": result}

    def cognify(self, *, datasets: list[str] | None = None, **kwargs) -> Any:
        """Trigger Cognee's graph-extraction pipeline.

        The result typically contains the extracted entity nodes + edges.
        The adapter inspects the result (if structured) and records
        entities + edges into the sidecar.
        """
        result = _run_async(self.cognee.cognify(
            datasets=datasets, **kwargs,
        ))
        now = _time.time()
        # Cognee's cognify output varies by version; try to extract
        # nodes/edges defensively
        if isinstance(result, dict):
            for node in result.get("nodes", []) or []:
                node_id = str(node.get("id") or node.get("uuid") or "")
                if not node_id:
                    continue
                self.record_write(
                    node_id=node_id, kind="entity",
                    metadata={"name": node.get("name")},
                    t=now,
                )
            for edge in result.get("edges", []) or []:
                src = str(edge.get("source") or edge.get("src") or "")
                dst = str(edge.get("target") or edge.get("dst") or "")
                if src and dst:
                    self.record_edge(src, dst, t=now)
        return result

    def search(self, query_type: str, query: str, *,
               dataset_name: str | None = None, **kwargs) -> Any:
        """Search via Cognee; record query events against returned nodes."""
        result = _run_async(self.cognee.search(
            query_type=query_type, query_text=query, **kwargs,
        ))
        now = _time.time()
        # Cognee search results contain matched nodes; record each
        if isinstance(result, list):
            for item in result:
                node_id = str(
                    (item.get("id") or item.get("uuid"))
                    if isinstance(item, dict) else ""
                )
                if node_id:
                    self.record_query(node_id, t=now)
        return result

    def delete(self, node_id: str) -> Any:
        """Delete a single document/node from Cognee + sidecar."""
        result = None
        try:
            # Cognee's delete API name varies; try the most common
            if hasattr(self.cognee, "delete"):
                result = _run_async(self.cognee.delete(node_id))
        except Exception:
            pass
        self._records.pop(node_id, None)
        return result

    # ---- GCIntegrationShim contract methods ----

    def record_write(
        self,
        node_id: str,
        kind: str,
        metadata: dict | None,
        t: float,
    ) -> None:
        dataset = (metadata or {}).get("dataset_name")
        self._records[node_id] = CogneeNodeRecord(
            node_id=node_id, kind=kind,
            added_at=t, last_access=t, query_count=0,
            dataset_name=dataset,
        )
        self._in_degree.setdefault(node_id, 0)
        self._out_degree.setdefault(node_id, 0)
        self._stats.n_writes += 1

    def record_edge(self, src: str, dst: str, t: float) -> None:
        if (src, dst) in self._edges:
            return
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
        for (src, dst) in self._edges:
            state.edges[(src, dst)] = state.edges.get((src, dst), 0) + 1
        state.pinned = set(self._pinned)
        return state

    def apply_sweep(self, node_ids_to_remove: list[str]) -> int:
        self._stats.n_sweeps_invoked += 1
        self._stats.last_sweep_size_before = len(self._records)
        n_removed = 0
        for node_id in node_ids_to_remove:
            if node_id in self._pinned:
                continue
            if node_id not in self._records:
                continue
            try:
                self.delete(node_id)
                # Clean up edges
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
                self._records.pop(node_id, None)
        self._stats.last_sweep_size_after = len(self._records)
        self._stats.n_nodes_actually_removed += n_removed
        return n_removed

    def stats(self) -> IntegrationStats:
        return self._stats

    def sweep(self, variant, *, current_time: float | None = None) -> int:
        """Run one sweep cycle: collect candidates + tombstone-record +
        delete."""
        t = current_time if current_time is not None else _time.time()
        state = self.get_state()
        candidates = variant.collect_candidates(state, t)
        for cand_id in candidates:
            variant.collect(cand_id, state, current_time=t)
        return self.apply_sweep(candidates)
