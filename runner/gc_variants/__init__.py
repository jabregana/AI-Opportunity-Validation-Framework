"""Backward-compat shim. The real package lives at
runner.dimensions.memory.lifecycle.

This shim re-exports the public API from the new location and registers
submodules under their old paths so imports like
`from runner.gc_variants.ref_count import FactOnlyGC` keep working.

New code should import from runner.dimensions.memory.lifecycle directly.
See docs/six-dimensions-architecture.md for the architecture.
"""
from __future__ import annotations
import sys as _sys

from runner.dimensions.memory.lifecycle import (  # noqa: F401
    FACTORIES,
    GCVariant,
    GraphState,
    build,
)

from runner.dimensions.memory.lifecycle import (  # noqa: F401
    b_raw as _b_raw,
    base as _base,
    ref_count as _ref_count,
)

_sys.modules["runner.gc_variants.b_raw"] = _b_raw
_sys.modules["runner.gc_variants.base"] = _base
_sys.modules["runner.gc_variants.ref_count"] = _ref_count


__all__ = ["FACTORIES", "GCVariant", "GraphState", "build"]
