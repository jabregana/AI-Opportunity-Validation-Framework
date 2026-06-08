"""Comprehensive GC variant combining v0.1.3 + v0.1.4 + v0.1.5 (v0.1.6).

`gc-v0.1.6-comprehensive` is the production-ready bundle: fact-only
collection (from v0.1.2), conservative entity collection (from v0.1.4),
tombstone log (from v0.1.3), and tenant-scoped pinning (from v0.1.5).

Inherits from ConservativeEntityPlusFactGC (which inherits from
FactOnlyGC) to keep the should_collect rule single-source-of-truth.
Tombstone and tenant-pin features are layered on top.

Use this when:
  - You want EVERYTHING the framework knows about safe GC
  - You're running multi-tenant (SaaS)
  - You want over-collection recovery via tombstones
  - You want dormant entities cleaned up too (not just orphan facts)
"""
from __future__ import annotations

from .base import GraphState
from .conservative_entity import ConservativeEntityPlusFactGC


class ComprehensiveGC(ConservativeEntityPlusFactGC):
    """v0.1.6: ConservativeEntityPlusFactGC + tombstone + tenant pinning."""

    name = "gc-v0.1.6-comprehensive"

    def __init__(
        self,
        min_age_seconds: float = 86400.0,
        tombstone_ttl_seconds: float = 7 * 86400.0,
        min_unaccessed_seconds: float = 60.0 * 86400,
        min_observation_seconds: float = 30.0 * 86400,
    ):
        super().__init__(
            min_age_seconds=min_age_seconds,
            min_unaccessed_seconds=min_unaccessed_seconds,
            min_observation_seconds=min_observation_seconds,
        )
        # Tombstone state (from v0.1.3)
        self.tombstone_ttl = tombstone_ttl_seconds
        self.tombstones: dict[str, dict] = {}
        self.tombstone_eviction_count = 0
        # Tenant-pinning state (from v0.1.5)
        self.tenant_pins: dict[str, set[str]] = {}
        self._current_tenant_id: str | None = None

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        # Tenant-pinning check first (global or any-tenant)
        if node_id in state.pinned:
            return False
        if self.is_pinned_for_any_tenant(node_id):
            return False
        # Inherited conservative-entity-plus-fact rule
        return super().should_collect(node_id, state, current_time)

    def collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float = 0.0,
    ) -> int:
        # Tenant-pin protection (base GCVariant.collect only checks
        # state.pinned; v0.1.6 must also refuse tenant-pinned)
        if self.is_pinned_for_any_tenant(node_id):
            return 0
        # Record tombstone BEFORE delegating to parent (from v0.1.3)
        if node_id in state.nodes and node_id not in state.pinned:
            node_meta = dict(state.nodes.get(node_id, {}))
            if current_time > 0.0:
                collected_at = current_time
            else:
                collected_at = state.last_access.get(
                    node_id, node_meta.get("added_at", 0.0),
                )
            self.tombstones[node_id] = {
                "collected_at": collected_at,
                "kind": node_meta.get("kind"),
                "added_at": node_meta.get("added_at"),
            }
        return super().collect(node_id, state, current_time)

    # ---- Tombstone API (from v0.1.3) ----

    def was_recently_collected(
        self,
        node_id: str,
        current_time: float,
    ) -> bool:
        if node_id not in self.tombstones:
            return False
        collected_at = self.tombstones[node_id]["collected_at"]
        if current_time < collected_at:
            return False
        return (current_time - collected_at) <= self.tombstone_ttl

    def prune_expired_tombstones(self, current_time: float) -> int:
        expired = [
            nid for nid, t in self.tombstones.items()
            if (current_time - t["collected_at"]) > self.tombstone_ttl
        ]
        for nid in expired:
            del self.tombstones[nid]
        self.tombstone_eviction_count += len(expired)
        return len(expired)

    # ---- Tenant-pin API (from v0.1.5) ----

    def pin_for_tenant(self, tenant_id: str, node_id: str) -> None:
        if tenant_id not in self.tenant_pins:
            self.tenant_pins[tenant_id] = set()
        self.tenant_pins[tenant_id].add(node_id)

    def unpin_for_tenant(self, tenant_id: str, node_id: str) -> None:
        if tenant_id in self.tenant_pins:
            self.tenant_pins[tenant_id].discard(node_id)

    def is_pinned_for_any_tenant(self, node_id: str) -> bool:
        return any(node_id in pins for pins in self.tenant_pins.values())

    def set_active_tenant(self, tenant_id: str | None) -> None:
        self._current_tenant_id = tenant_id
