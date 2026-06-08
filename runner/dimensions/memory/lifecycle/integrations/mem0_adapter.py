"""Mem0 integration adapter for the GC lifecycle dimension.

Translates the `GCIntegrationShim` contract into actual Mem0 v2.x
API calls. Treats each Mem0 memory as a "fact" node in our GC graph
(Mem0 v2 does not expose explicit entity/fact distinction; the adapter
works at the memory-id granularity).

Use:

    from mem0 import Memory
    from runner.dimensions.memory.lifecycle import build
    from runner.dimensions.memory.lifecycle.integrations import Mem0GCMiddleware

    memory = Memory()  # or Memory.from_config(...)
    variant = build("gc-v0.1.8-comprehensive-tuned")
    middleware = Mem0GCMiddleware(memory)

    # Drop-in replacement for memory.add / memory.search
    middleware.add("User likes coffee", user_id="user_1")
    results = middleware.search("preferences", user_id="user_1")

    # Periodic sweep deletes stale memories per the variant's policy
    n_removed = middleware.sweep(variant, current_time=time.time())

The middleware exposes the underlying `Memory` instance as
`middleware.memory` for any operation the framework does not need
to intercept (e.g. `chat`, `history`).

Phase 1 of the synthesis-memory-lifecycle-management.md plan.
"""
from __future__ import annotations
import time as _time
from dataclasses import dataclass, field
from typing import Any

from ..base import GraphState
from .base import GCIntegrationShim, IntegrationStats


@dataclass
class Mem0MemoryRecord:
    """Per-memory metadata the middleware tracks."""

    memory_id: str
    kind: str = "fact"  # Mem0 memories are facts by default
    added_at: float = 0.0
    last_access: float = 0.0
    query_count: int = 0
    user_id: str | None = None  # used as tenant_id when present


class Mem0GCMiddleware(GCIntegrationShim):
    """GC middleware around a Mem0 `Memory` instance.

    The middleware maintains its own metadata sidecar (`_records`)
    keyed by Mem0 memory_id. Calls to add / search update both Mem0
    and the sidecar. The sweep method walks the sidecar, asks the
    variant which memories to collect, and calls memory.delete() for
    each.

    For multi-tenant deployments: Mem0's user_id maps to our
    tenant_id, so variants with `pin_for_tenant()` get tenant-scoped
    pinning when the user_id is passed through.
    """

    name = "mem0-adapter"
    contract_version = 1

    def __init__(self, memory: Any):
        """`memory` is a mem0.Memory instance (or anything with the
        Mem0 v2 API: add/search/get/get_all/update/delete)."""
        self.memory = memory
        self._records: dict[str, Mem0MemoryRecord] = {}
        self._stats = IntegrationStats()
        # The "graph state" derived from Mem0's memory store. Mem0 v2
        # does not expose edges, so out_degree is always 0 for facts
        # (their "edges" to entities are implicit in the memory text,
        # not modeled here). v0.1.2-fact-only's rule (out_degree==0
        # AND age>min_age) therefore makes ALL aged-out facts
        # collectible, which is the correct semantic for Mem0.
        self._pinned: set[str] = set()

    # ---- Mem0 API interception (the operational surface) ----

    def add(self, messages, **kwargs) -> Any:
        """Add memory via Mem0; record the new memory ids in the sidecar."""
        result = self.memory.add(messages, **kwargs)
        # Mem0 v2 returns {"results": [{"id": ..., "memory": ..., "event": ...}, ...]}
        memory_results = result.get("results", []) if isinstance(result, dict) else []
        now = _time.time()
        user_id = kwargs.get("user_id")
        for r in memory_results:
            mem_id = r.get("id")
            if not mem_id:
                continue
            event = r.get("event", "ADD")
            if event == "ADD":
                self.record_write(
                    node_id=str(mem_id),
                    kind="fact",
                    metadata={"user_id": user_id, "memory": r.get("memory")},
                    t=now,
                )
            elif event == "UPDATE":
                # Mem0 may UPDATE an existing memory rather than ADD;
                # treat as a write touch (refresh added_at? or just
                # update last_access?). We update last_access to keep
                # the memory "fresh" in the lifecycle sense.
                self.record_query(str(mem_id), t=now)
            elif event == "DELETE":
                # Mem0 may delete during add (e.g., supersession)
                self._records.pop(str(mem_id), None)
        return result

    def search(self, query: str, **kwargs) -> Any:
        """Search via Mem0; record query events against the returned ids.

        Mem0 v2 requires entity scoping (user_id/agent_id/run_id) via
        filters={...} and rejects top-level entity kwargs. The adapter
        translates top-level entity kwargs into filters for backward
        compatibility with Mem0 v1 call sites.
        """
        entity_keys = ("user_id", "agent_id", "run_id")
        filters = dict(kwargs.pop("filters", {}) or {})
        for k in entity_keys:
            if k in kwargs:
                filters[k] = kwargs.pop(k)
        if filters:
            kwargs["filters"] = filters
        result = self.memory.search(query, **kwargs)
        now = _time.time()
        # Mem0 v2 search returns {"results": [{"id": ...}, ...]}
        for r in (result.get("results", []) if isinstance(result, dict) else []):
            mem_id = r.get("id")
            if mem_id:
                self.record_query(str(mem_id), t=now)
        return result

    def get(self, memory_id) -> Any:
        """Get one memory; record access."""
        result = self.memory.get(memory_id)
        if result:
            self.record_query(str(memory_id), t=_time.time())
        return result

    def get_all(self, **kwargs) -> Any:
        """Pass through; do NOT record query events for get_all (would
        falsely refresh last_access on every memory)."""
        return self.memory.get_all(**kwargs)

    def update(self, memory_id, data, **kwargs) -> Any:
        """Update via Mem0; refresh last_access."""
        result = self.memory.update(memory_id, data, **kwargs)
        self.record_query(str(memory_id), t=_time.time())
        return result

    def delete(self, memory_id) -> Any:
        """Delete via Mem0; remove from sidecar."""
        result = self.memory.delete(memory_id)
        self._records.pop(str(memory_id), None)
        return result

    # ---- GCIntegrationShim contract methods ----

    def record_write(
        self,
        node_id: str,
        kind: str,
        metadata: dict | None,
        t: float,
    ) -> None:
        user_id = (metadata or {}).get("user_id")
        self._records[node_id] = Mem0MemoryRecord(
            memory_id=node_id,
            kind=kind,
            added_at=t,
            last_access=t,
            query_count=0,
            user_id=user_id,
        )
        self._stats.n_writes += 1

    def record_edge(self, src: str, dst: str, t: float) -> None:
        """Mem0 v2 has no explicit edge surface. Adapters for v3+ with
        graph support should override this."""
        self._stats.n_edges_added += 1

    def record_remove_edge(self, src: str, dst: str, t: float) -> None:
        """Same as record_edge: not exposed in Mem0 v2."""
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
        """Build a GraphState from the sidecar records.

        Mem0 v2 facts have no explicit out_degree (they're already
        terminal). Setting out_degree = 0 for every record makes
        v0.1.2-fact-only's collection rule "collect facts whose
        out_degree==0 AND age > min_age" apply to every aged-out
        memory — which is the correct semantic for Mem0 (a memory
        whose age exceeds the lifecycle window IS ready for collection).
        """
        state = GraphState()
        for mem_id, rec in self._records.items():
            state.nodes[mem_id] = {
                "kind": rec.kind,
                "added_at": rec.added_at,
            }
            state.in_degree[mem_id] = 0
            state.out_degree[mem_id] = 0
            state.last_access[mem_id] = rec.last_access
            state.query_count[mem_id] = rec.query_count
        state.pinned = set(self._pinned)
        return state

    def apply_sweep(self, node_ids_to_remove: list[str]) -> int:
        """Delete the chosen memories from Mem0 + sidecar.

        Respects pinning (pinned nodes are NOT deleted). Returns the
        number actually removed.
        """
        self._stats.n_sweeps_invoked += 1
        self._stats.last_sweep_size_before = len(self._records)
        n_removed = 0
        for mem_id in node_ids_to_remove:
            if mem_id in self._pinned:
                continue
            if mem_id not in self._records:
                continue
            try:
                self.memory.delete(mem_id)
                self._records.pop(mem_id, None)
                n_removed += 1
            except Exception:
                # Mem0 may raise if memory_id is gone; swallow + skip.
                # In production, log this; for the smoke test we keep
                # the run going.
                self._records.pop(mem_id, None)
        self._stats.last_sweep_size_after = len(self._records)
        self._stats.n_nodes_actually_removed += n_removed
        return n_removed

    def stats(self) -> IntegrationStats:
        return self._stats

    # ---- Convenience: end-to-end sweep ----

    def sweep(self, variant, *, current_time: float | None = None) -> int:
        """Run one sweep cycle: ask the variant for candidates, apply.

        Calls `variant.collect(mem_id, state, current_time)` for each
        candidate before deleting from the downstream so tombstone
        variants can record their internal sidecar. Then calls
        apply_sweep() to actually remove from Mem0 + sidecar.

        Returns the number of memories removed. Production deployments
        should call this periodically (every N writes, every K minutes,
        or on a fixed schedule).
        """
        t = current_time if current_time is not None else _time.time()
        state = self.get_state()
        candidates = variant.collect_candidates(state, t)
        # First, let the variant record any per-variant side effects
        # (tombstones, eviction counters, etc) via its own collect().
        # The state mutation on the ephemeral GraphState is discarded;
        # what we care about is the variant's internal state changes.
        for cand_id in candidates:
            variant.collect(cand_id, state, current_time=t)
        # Then actually delete from Mem0 + sidecar
        return self.apply_sweep(candidates)
