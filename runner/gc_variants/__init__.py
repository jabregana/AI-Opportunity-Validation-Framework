"""Graph GC variant registry.

GC variants are the second opportunity class evaluated through this
framework. The first was schema-alignment proxies (runner/variants/).
Same pattern: an ABC, a factory dict, and a build() helper.
"""
from __future__ import annotations
from typing import Callable

from .base import GCVariant, GraphState
from .b_raw import BRawNoGC
from .ref_count import RefCountGC, RefCountUtilityGC


FACTORIES: dict[str, Callable[[], GCVariant]] = {
    "b-raw-no-gc": BRawNoGC,
    "gc-v0.1.0-ref-count": RefCountGC,
    "gc-v0.1.1-ref-count-utility": RefCountUtilityGC,
}


def build(variant_id: str) -> GCVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown GC variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["GCVariant", "GraphState", "build", "FACTORIES"]
