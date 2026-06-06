"""Tests for v0.5.7 MultiTenantANNSingletonAwareLazyProxy.

Two properties to verify:
  1. Behavior parity with v0.5.3 (singleton-aware) at small K.
  2. Per-source inners are ANN-backed (not the default linear-scan
     StructurallyFilteredHybridSchemaProxy).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.variants import build
from runner.variants.embed_proxy import ANNSchemaProxy


WORKLOAD = [
    # (source, surface, oracle_canonical)
    ("sales", "Apple", "Apple Inc"),
    ("sales", "AAPL", "Apple Inc"),
    ("sales", "Apple Inc", "Apple Inc"),
    ("ops", "Apple", "Apple Inc"),
    ("ops", "Apple Inc", "Apple Inc"),
    ("ops", "Apple Computer", "Apple Inc"),
    ("sales", "Microsoft", "Microsoft Corp"),
    ("sales", "MSFT", "Microsoft Corp"),
    ("ops", "Microsoft", "Microsoft Corp"),
    ("ops", "Microsoft Corp", "Microsoft Corp"),
]


def _run(variant_id: str) -> list[str]:
    v = build(variant_id)
    for src, surface, _ in WORKLOAD:
        v.align_with_context(surface, {"source_id": src})
    if hasattr(v, "consolidate"):
        v.consolidate()
    return [
        v.align_with_context(surface, {"source_id": src})
        for src, surface, _ in WORKLOAD
    ]


def test_v0_5_7_parity_with_v0_5_3_at_small_k():
    """At small K the ANN index is exact via HNSW or numpy scan; v0.5.7
    should produce identical canonical assignments to v0.5.3."""
    ref = _run("embed-proxy-v0.5.3-singleton-aware")
    ann = _run("embed-proxy-v0.5.7-mt-ann")
    assert ref == ann, (
        f"v0.5.7 diverges from v0.5.3 at small K.\n"
        f"v0.5.3: {ref}\nv0.5.7: {ann}"
    )


def test_v0_5_7_inners_are_ann_backed():
    v = build("embed-proxy-v0.5.7-mt-ann")
    for src, surface, _ in WORKLOAD:
        v.align_with_context(surface, {"source_id": src})
    # Each per-source inner must be an ANNSchemaProxy instance.
    for src, inner in v._per_source.items():
        assert isinstance(inner, ANNSchemaProxy), (
            f"source {src!r} inner is {type(inner).__name__}, "
            f"expected ANNSchemaProxy"
        )


def test_v0_5_7_consolidate_returns_summary():
    v = build("embed-proxy-v0.5.7-mt-ann")
    for src, surface, _ in WORKLOAD:
        v.align_with_context(surface, {"source_id": src})
    summary = v.consolidate()
    assert "n_keys" in summary
    assert "n_merge_edges" in summary
    assert "singleton_density" in summary
    assert "singleton_aware_active" in summary
