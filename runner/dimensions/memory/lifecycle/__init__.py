"""Graph GC variant registry.

GC variants are the second opportunity class evaluated through this
framework. The first was schema-alignment proxies (runner/variants/).
Same pattern: an ABC, a factory dict, and a build() helper.
"""
from __future__ import annotations
from typing import Callable

from .activation_decay import ActivationDecayGC
from .base import GCVariant, GraphState
from .b_raw import BRawNoGC
from .component_isolation import ComponentIsolationGC
from .comprehensive import ComprehensiveGC
from .comprehensive_graph_tuned import ComprehensiveGraphTunedGC, V02xConfig
from .comprehensive_tuned import ComprehensiveTunedGC
from .conservative_entity import ConservativeEntityPlusFactGC
from .conservative_entity_tuned import ConservativeEntityTunedGC
from .evidence_count import EvidenceCountGC
from .ref_count import FactOnlyGC, RefCountGC, RefCountUtilityGC
from .supersession_tombstone import SupersessionTombstoneGC, Tombstone
from .temporal_validity import TemporalValidityGC
from .tenant_pin import FactOnlyTenantPinningGC
from .tombstone import FactOnlyTombstoneGC


FACTORIES: dict[str, Callable[[], GCVariant]] = {
    "b-raw-no-gc": BRawNoGC,
    "gc-v0.1.0-ref-count": RefCountGC,
    "gc-v0.1.1-ref-count-utility": RefCountUtilityGC,
    "gc-v0.1.2-fact-only": FactOnlyGC,
    "gc-v0.1.3-fact-only-tombstone": FactOnlyTombstoneGC,
    "gc-v0.1.4-conservative-entity-plus-fact": ConservativeEntityPlusFactGC,
    "gc-v0.1.5-fact-only-tenant-pinning": FactOnlyTenantPinningGC,
    "gc-v0.1.6-comprehensive": ComprehensiveGC,
    "gc-v0.1.7-conservative-entity-tuned": ConservativeEntityTunedGC,
    "gc-v0.1.8-comprehensive-tuned": ComprehensiveTunedGC,
    # v0.2.x family: graph-topology-aware variants for edge-rich frameworks
    # (Graphiti, Cognee). See docs/opportunity-v0.2.x-graph-topology-gc.md.
    "gc-v0.2.0-component-isolation": ComponentIsolationGC,
    "gc-v0.2.1-temporal-validity": TemporalValidityGC,
    "gc-v0.2.2-activation-decay": ActivationDecayGC,
    "gc-v0.2.3-evidence-count": EvidenceCountGC,
    "gc-v0.2.4-supersession-tombstone": SupersessionTombstoneGC,
    "gc-v0.2.5-comprehensive-graph-tuned": ComprehensiveGraphTunedGC,
}


def build(variant_id: str) -> GCVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown GC variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["GCVariant", "GraphState", "build", "FACTORIES"]
