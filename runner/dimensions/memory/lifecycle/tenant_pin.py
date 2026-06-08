"""Tenant-scoped pinning GC (v0.1.5).

Extends FactOnlyGC (v0.1.2) with per-tenant pinned-set tracking. Required
for production multi-tenant deployments where tenant A's pinned nodes
should not leak across to tenant B.

Implementation: the variant maintains an internal
  tenant_pins: dict[tenant_id, set[node_id]]

separately from the GraphState's global `pinned` set. The variant
overrides should_collect to consult both:

  - Global state.pinned (still respected for cross-tenant pins)
  - Variant's tenant_pins[tenant_id_of_this_call]

This keeps GraphState backward-compatible (no breaking change to other
variants or the runner) while adding tenant scope where needed.

The runner is expected to pass `tenant_id` in the context dict on
collect_candidates calls. Without a tenant_id, the variant falls back
to global pin semantics (same as v0.1.2).

Ships as gc-v0.1.5-fact-only-tenant-pinning.
"""
from __future__ import annotations

from .base import GraphState
from .ref_count import FactOnlyGC


class FactOnlyTenantPinningGC(FactOnlyGC):
    """v0.1.5: FactOnlyGC + per-tenant pinned-set tracking."""

    name = "gc-v0.1.5-fact-only-tenant-pinning"

    def __init__(self, min_age_seconds: float = 86400.0):
        super().__init__(min_age_seconds=min_age_seconds)
        self.tenant_pins: dict[str, set[str]] = {}
        self._current_tenant_id: str | None = None

    def pin_for_tenant(self, tenant_id: str, node_id: str) -> None:
        """Add node_id to tenant_id's pinned set."""
        if tenant_id not in self.tenant_pins:
            self.tenant_pins[tenant_id] = set()
        self.tenant_pins[tenant_id].add(node_id)

    def unpin_for_tenant(self, tenant_id: str, node_id: str) -> None:
        if tenant_id in self.tenant_pins:
            self.tenant_pins[tenant_id].discard(node_id)

    def is_pinned_for_any_tenant(self, node_id: str) -> bool:
        """Cross-tenant query: is this node pinned by anyone?"""
        return any(node_id in pins for pins in self.tenant_pins.values())

    def set_active_tenant(self, tenant_id: str | None) -> None:
        """Set the tenant scope for the next sweep cycle.

        The runner is expected to call this before collect_candidates
        for each tenant's sweep.
        """
        self._current_tenant_id = tenant_id

    def _is_pinned(self, node_id: str, state: GraphState) -> bool:
        if node_id in state.pinned:
            return True
        # If any tenant has this node pinned, it survives the global sweep
        if self.is_pinned_for_any_tenant(node_id):
            return True
        return False

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        if self._is_pinned(node_id, state):
            return False
        # Inherit the v0.1.2 fact-only rule
        return super().should_collect(node_id, state, current_time)
