"""Tests for the ANN index abstraction and the v0.5.5 ANN-backed proxy."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math
import random

import pytest

from runner.variants.ann_index import (
    HNSWANNIndex,
    LinearANNIndex,
    _HAVE_HNSW,
    build_index,
)


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        return v
    return [x / n for x in v]


def _rand_unit(rng: random.Random, dim: int) -> list[float]:
    return _norm([rng.gauss(0, 1) for _ in range(dim)])


def test_linear_index_basic_recall():
    idx = LinearANNIndex(dim=8)
    a = _norm([1, 0, 0, 0, 0, 0, 0, 0])
    b = _norm([0, 1, 0, 0, 0, 0, 0, 0])
    idx.add(7, a)
    idx.add(42, b)
    got_id, got_sim = idx.nearest(a)
    assert got_id == 7
    assert got_sim == pytest.approx(1.0, abs=1e-6)
    got_id, got_sim = idx.nearest(b)
    assert got_id == 42
    assert got_sim == pytest.approx(1.0, abs=1e-6)


def test_linear_index_empty_raises():
    idx = LinearANNIndex(dim=8)
    with pytest.raises(IndexError):
        idx.nearest([0.0] * 8)


def test_linear_index_dim_mismatch_raises():
    idx = LinearANNIndex(dim=8)
    with pytest.raises(ValueError):
        idx.add(0, [1.0] * 4)


@pytest.mark.skipif(not _HAVE_HNSW, reason="hnswlib not installed")
def test_hnsw_index_top1_matches_linear_at_modest_scale():
    rng = random.Random(7)
    dim = 64
    n = 500
    vectors = [_rand_unit(rng, dim) for _ in range(n)]

    linear = LinearANNIndex(dim=dim)
    hnsw = HNSWANNIndex(dim=dim)
    for i, v in enumerate(vectors):
        linear.add(i, v)
        hnsw.add(i, v)

    queries = [_rand_unit(rng, dim) for _ in range(50)]
    hits = 0
    for q in queries:
        lin_id, _ = linear.nearest(q)
        hnsw_id, _ = hnsw.nearest(q)
        if lin_id == hnsw_id:
            hits += 1
    assert hits / len(queries) >= 0.9, "HNSW top-1 recall < 90% at n=500"


@pytest.mark.skipif(not _HAVE_HNSW, reason="hnswlib not installed")
def test_hnsw_index_grows_past_initial_capacity():
    idx = HNSWANNIndex(dim=8, initial_capacity=16)
    for i in range(40):
        idx.add(i, _norm([(i + 1) % 7] + [0.0] * 7))
    assert idx.size == 40
    nearest_id, _ = idx.nearest(_norm([1.0] + [0.0] * 7))
    assert isinstance(nearest_id, int)


def test_build_index_auto_picks_hnsw_if_available():
    idx = build_index(dim=8, backend="auto")
    if _HAVE_HNSW:
        assert isinstance(idx, HNSWANNIndex)
    else:
        assert isinstance(idx, LinearANNIndex)


def test_build_index_linear_forced():
    idx = build_index(dim=8, backend="linear")
    assert isinstance(idx, LinearANNIndex)


def test_build_index_unknown_raises():
    with pytest.raises(ValueError):
        build_index(dim=8, backend="bogus")


def test_v0_5_5_ann_matches_v0_3_1_at_small_k():
    """Behavior parity check: v0.5.5 with the same inputs as v0.3.1 should
    produce the same canonical assignments at small K, where any HNSW
    approximation error is well below the safety margin."""
    from runner.variants import build

    inputs = [
        "WORKS_AT",
        "works_at",
        "WorksAt",
        "IS_A",
        "INSTANCE_OF",
        "ISO 639-1 code",
        "ISO 639-2 code",
        "review score",
        "review score by",
    ]

    v_ref = build("embed-proxy-v0.3.1")
    v_ann = build("embed-proxy-v0.5.5-ann")
    ref_out = [v_ref.align(s) for s in inputs]
    ann_out = [v_ann.align(s) for s in inputs]
    assert ref_out == ann_out, (
        f"v0.5.5 diverges from v0.3.1 on small-K aliasing.\n"
        f"v0.3.1:    {ref_out}\nv0.5.5-ann:{ann_out}"
    )


def test_v0_5_5_ann_canonical_count_matches_v0_3_1():
    from runner.variants import build

    inputs = ["alpha", "Alpha", "ALPHA", "beta", "gamma", "delta", "Delta"]
    v_ref = build("embed-proxy-v0.3.1")
    v_ann = build("embed-proxy-v0.5.5-ann")
    for s in inputs:
        v_ref.align(s)
        v_ann.align(s)
    assert v_ref.canonical_count == v_ann.canonical_count
