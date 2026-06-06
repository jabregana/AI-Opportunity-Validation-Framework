from __future__ import annotations
from typing import Callable

from .base import Variant
from .b_raw import BRawIdentity
from .embed_proxy import (
    EmbeddingSchemaProxy,
    HybridSchemaProxy,
    NeuralEmbeddingSchemaProxy,
    StructurallyFilteredHybridSchemaProxy,
)
from .per_source import (
    CrossSourceConsensusProxy,
    LazyConsensusANDRuleProxy,
    LazyCrossSourceConsensusProxy,
    PerSourceNamespaceProxy,
)
from .stub_proxy import StubRandomBucketProxy

# Registry: variant_id -> factory (no-arg or default-arg)
FACTORIES: dict[str, Callable[[], Variant]] = {
    "b-raw-identity": BRawIdentity,
    "stub-random-bucket": StubRandomBucketProxy,
    "embed-proxy-v0.1.0": EmbeddingSchemaProxy,
    "embed-proxy-v0.2.0": NeuralEmbeddingSchemaProxy,
    "embed-proxy-v0.3.0": HybridSchemaProxy,
    "embed-proxy-v0.3.1": StructurallyFilteredHybridSchemaProxy,
    "embed-proxy-v0.4.0-per-source": PerSourceNamespaceProxy,
    "embed-proxy-v0.4.1-consensus": CrossSourceConsensusProxy,
    "embed-proxy-v0.4.2-lazy-consensus": LazyCrossSourceConsensusProxy,
    "embed-proxy-v0.4.3-and-rule": LazyConsensusANDRuleProxy,
}


def build(variant_id: str) -> Variant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["Variant", "build", "FACTORIES"]
