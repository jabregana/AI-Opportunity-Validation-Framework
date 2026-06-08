"""Backward-compat shim. The real package lives at
runner.dimensions.memory.canonicalization.

This shim re-exports the public API from the new location and registers
submodules under their old paths so imports like
`from runner.variants.embed_proxy import HybridSchemaProxy` keep
working.

New code should import from runner.dimensions.memory.canonicalization
directly. See docs/six-dimensions-architecture.md for the architecture.
"""
from __future__ import annotations
import sys as _sys

# Public API
from runner.dimensions.memory.canonicalization import (  # noqa: F401
    FACTORIES,
    Variant,
    build,
)

# Submodule registration for backward-compat with `from
# runner.variants.<submodule> import X` paths.
from runner.dimensions.memory.canonicalization import (  # noqa: F401
    ann_index as _ann_index,
    b_raw as _b_raw,
    base as _base,
    embed_proxy as _embed_proxy,
    neural_embedder as _neural_embedder,
    per_source as _per_source,
    structural_filter as _structural_filter,
    stub_proxy as _stub_proxy,
)

_sys.modules["runner.variants.ann_index"] = _ann_index
_sys.modules["runner.variants.b_raw"] = _b_raw
_sys.modules["runner.variants.base"] = _base
_sys.modules["runner.variants.embed_proxy"] = _embed_proxy
_sys.modules["runner.variants.neural_embedder"] = _neural_embedder
_sys.modules["runner.variants.per_source"] = _per_source
_sys.modules["runner.variants.structural_filter"] = _structural_filter
_sys.modules["runner.variants.stub_proxy"] = _stub_proxy


__all__ = ["FACTORIES", "Variant", "build"]
