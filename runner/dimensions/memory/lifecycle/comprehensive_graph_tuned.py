"""gc-v0.2.5-comprehensive-graph-tuned: the v0.2.x bundle.

Composes all five v0.2.x layers + v0.1.5's tenant pinning. Configurable
per deployment profile (see profile_loader.py + profiles/*.yaml).

Composition semantics: a node is collected only if EVERY enabled layer
that has an opinion about the node agrees to collect (or has no
opinion). Pinned nodes are never collected (anchored at the
component-isolation layer + as a final guard).

This is the graph-native analog of v0.1.8-comprehensive-tuned. The
layered design lets a customer disable any layer via profile config
without rebuilding the variant class.
"""
from __future__ import annotations
from dataclasses import dataclass

from .activation_decay import ActivationDecayGC
from .base import GCVariant, GraphState
from .component_isolation import ComponentIsolationGC
from .evidence_count import EvidenceCountGC
from .supersession_tombstone import SupersessionTombstoneGC, Tombstone
from .temporal_validity import TemporalValidityGC


@dataclass
class V02xConfig:
    """Per-deployment configuration for the v0.2.5 bundle.

    Each layer has an `enabled` flag plus its own knobs. Profile YAMLs
    materialize this object via profile_loader.from_yaml().
    """

    # Layer 1: component-isolation
    component_isolation_enabled: bool = True
    min_component_idle_seconds: float = 30 * 86400.0
    min_component_age_seconds: float = 7 * 86400.0

    # Layer 2: temporal-validity
    temporal_validity_enabled: bool = True
    temporal_validity_ttl_seconds: float = 7 * 86400.0

    # Layer 3: activation-decay
    activation_decay_enabled: bool = True
    activation_window_seconds: float = 60 * 86400.0
    min_query_count: int = 3

    # Layer 4: evidence-count
    evidence_count_enabled: bool = True
    evidence_min_age_seconds: float = 30 * 86400.0

    # Layer 5: supersession-tombstone
    supersession_tombstone_enabled: bool = True
    tombstone_ttl_seconds: float = 7 * 86400.0
    supersession_min_age_seconds: float = 86400.0

    # Tenant pinning (inherited from v0.1.5 design; bundle holds the set)
    tenant_pinning_enabled: bool = True


class ComprehensiveGraphTunedGC(GCVariant):
    """v0.2.5: composes all five v0.2.x layers + tenant pinning.

    A node is collected only when every enabled layer that has an
    opinion approves. Pinned nodes are never collected.
    """

    name = "gc-v0.2.5-comprehensive-graph-tuned"

    def __init__(self, config: V02xConfig | None = None) -> None:
        self.config = config or V02xConfig()
        c = self.config
        self.component_isolation = (
            ComponentIsolationGC(
                min_component_idle_seconds=c.min_component_idle_seconds,
                min_component_age_seconds=c.min_component_age_seconds,
            ) if c.component_isolation_enabled else None
        )
        self.temporal_validity = (
            TemporalValidityGC(ttl_seconds=c.temporal_validity_ttl_seconds)
            if c.temporal_validity_enabled else None
        )
        self.activation_decay = (
            ActivationDecayGC(
                window_seconds=c.activation_window_seconds,
                min_query_count=c.min_query_count,
            ) if c.activation_decay_enabled else None
        )
        self.evidence_count = (
            EvidenceCountGC(min_age_seconds=c.evidence_min_age_seconds)
            if c.evidence_count_enabled else None
        )
        self.supersession_tombstone = (
            SupersessionTombstoneGC(
                tombstone_ttl_seconds=c.tombstone_ttl_seconds,
                min_age_before_collect_seconds=c.supersession_min_age_seconds,
            ) if c.supersession_tombstone_enabled else None
        )
        # Tenant pinning state (per-tenant pinned node sets)
        self._tenant_pins: dict[str, set[str]] = {}

    # ---- Tenant pinning API (inherited shape from v0.1.5) ----

    def pin_for_tenant(self, tenant_id: str, node_id: str) -> None:
        if not self.config.tenant_pinning_enabled:
            return
        self._tenant_pins.setdefault(tenant_id, set()).add(node_id)

    def unpin_for_tenant(self, tenant_id: str, node_id: str) -> None:
        if tenant_id in self._tenant_pins:
            self._tenant_pins[tenant_id].discard(node_id)

    def is_pinned_for_any_tenant(self, node_id: str) -> bool:
        return any(node_id in pins for pins in self._tenant_pins.values())

    # ---- Tombstone recovery API (delegated to v0.2.4 layer) ----

    def was_recently_collected(
        self,
        node_id: str,
        current_time: float,
    ) -> Tombstone | None:
        if self.supersession_tombstone is None:
            return None
        return self.supersession_tombstone.was_recently_collected(
            node_id, current_time,
        )

    # ---- The decision ----

    def _layer_opinions(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> list[bool]:
        """Collect each enabled layer's opinion. None means 'no opinion'
        (the layer doesn't apply to this node), True means 'collect',
        False means 'preserve'."""
        opinions: list[bool] = []
        for layer in (
            self.temporal_validity,
            self.activation_decay,
            self.evidence_count,
            self.supersession_tombstone,
        ):
            if layer is None:
                continue
            opinions.append(layer.should_collect(node_id, state, current_time))
        return opinions

    def should_collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float,
    ) -> bool:
        # Pinned (global) takes precedence
        if node_id in state.pinned:
            return False
        # Tenant pin
        if self.is_pinned_for_any_tenant(node_id):
            return False
        # Component-isolation: anchors the whole component
        if self.component_isolation is not None:
            iso_candidates = set(
                self.component_isolation.collect_candidates(state, current_time)
            )
            if node_id not in iso_candidates:
                # Component-level rule already says preserve
                # (recent query in component OR pinned anchor OR brand-new)
                return False
        # At least one of the per-node layers must say 'collect'
        opinions = self._layer_opinions(node_id, state, current_time)
        return any(opinions)

    def collect(
        self,
        node_id: str,
        state: GraphState,
        current_time: float = 0.0,
    ) -> int:
        """Delegate to the supersession-tombstone layer for tombstone
        recording, then to the base collect() for state mutation."""
        if (self.supersession_tombstone is not None
                and node_id not in state.pinned):
            node = state.nodes.get(node_id)
            if node and node.get("superseded_by") is not None:
                # Let v0.2.4 record the tombstone properly
                return self.supersession_tombstone.collect(node_id, state, current_time)
        return super().collect(node_id, state, current_time)
