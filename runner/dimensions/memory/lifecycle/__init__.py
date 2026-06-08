"""Graph GC variant registry.

GC variants are the second opportunity class evaluated through this
framework. The first was schema-alignment proxies (runner/variants/).
Same pattern: an ABC, a factory dict, and a build() helper.
"""
from __future__ import annotations
from typing import Callable

from .base import GCVariant, GraphState
from .b_raw import BRawNoGC
from .comprehensive import ComprehensiveGC
from .conservative_entity import ConservativeEntityPlusFactGC
from .conservative_entity_tuned import ConservativeEntityTunedGC
from .ref_count import FactOnlyGC, RefCountGC, RefCountUtilityGC
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
}


def build(variant_id: str) -> GCVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown GC variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["GCVariant", "GraphState", "build", "FACTORIES"]
