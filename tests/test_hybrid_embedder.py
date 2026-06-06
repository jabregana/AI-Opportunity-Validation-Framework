"""Tests for HybridConcatEmbedder using deterministic sub-embedders."""
from __future__ import annotations
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.variants.embed_proxy import (
    HybridConcatEmbedder,
    _cosine,
)


class _UnitVecEmbedder:
    """Returns a fixed unit vector for any input. Useful for verifying
    concat / weighting math without depending on text-to-vec semantics."""

    def __init__(self, vec: list[float]):
        norm = math.sqrt(sum(x * x for x in vec))
        self._vec = [x / norm for x in vec] if norm > 0 else list(vec)
        self._dim = len(vec)

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return list(self._vec)


def _l2(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def test_hybrid_concat_dim_is_sum_of_parts():
    h = HybridConcatEmbedder(
        [(_UnitVecEmbedder([1.0, 0.0]), 1.0), (_UnitVecEmbedder([0.0, 1.0, 0.0]), 1.0)]
    )
    assert h.dim == 5


def test_hybrid_output_is_l2_normalized():
    h = HybridConcatEmbedder(
        [(_UnitVecEmbedder([1.0, 0.0]), 1.0), (_UnitVecEmbedder([0.0, 1.0]), 1.0)]
    )
    out = h.embed("anything")
    assert math.isclose(_l2(out), 1.0, abs_tol=1e-12)


def test_equal_weights_average_component_cosines():
    """For two sub-embedders both returning a fixed vector per text,
    set up so cos_A = 1.0 on a pair, cos_B = 0.5 on the same pair.
    Hybrid (equal weights) cosine should be (1.0 + 0.5) / 2 = 0.75."""

    class _A:
        # Returns same vec for "x" and "y" -> cos = 1
        dim = 2

        def embed(self, text):
            return [1.0, 0.0]

    class _B:
        # Returns different vecs with cos = 0.5
        dim = 2

        def embed(self, text):
            return [1.0, 0.0] if text == "x" else [0.5, math.sqrt(3) / 2]

    h = HybridConcatEmbedder([(_A(), 1.0), (_B(), 1.0)])
    cos = _cosine(h.embed("x"), h.embed("y"))
    assert math.isclose(cos, 0.75, abs_tol=1e-9)


def test_quadratic_weight_effect():
    """With weights w_A and w_B, cos_hybrid = (w_A^2 cos_A + w_B^2 cos_B)
    / (w_A^2 + w_B^2). Verify with w_A=2, w_B=1, cos_A=1, cos_B=0."""

    class _A:
        dim = 2

        def embed(self, text):
            return [1.0, 0.0]

    class _B:
        dim = 2

        def embed(self, text):
            return [1.0, 0.0] if text == "x" else [0.0, 1.0]

    h = HybridConcatEmbedder([(_A(), 2.0), (_B(), 1.0)])
    cos = _cosine(h.embed("x"), h.embed("y"))
    # cos_A = 1, cos_B = 0; w_A^2=4, w_B^2=1; (4*1 + 1*0)/(4+1) = 0.8
    assert math.isclose(cos, 0.8, abs_tol=1e-9)


def test_zero_weight_drops_embedder():
    """Setting one weight to 0 should make the hybrid behave like only
    the other sub-embedder (modulo zero-pad space)."""
    a = _UnitVecEmbedder([1.0, 0.0])
    b = _UnitVecEmbedder([0.0, 1.0])
    h = HybridConcatEmbedder([(a, 1.0), (b, 0.0)])
    out = h.embed("anything")
    # First two coords carry A; last two are zero.
    assert math.isclose(out[0], 1.0, abs_tol=1e-12)
    assert math.isclose(out[1], 0.0, abs_tol=1e-12)
    assert out[2] == 0.0 and out[3] == 0.0


def test_empty_list_raises():
    with pytest.raises(ValueError):
        HybridConcatEmbedder([])


def test_negative_weight_raises():
    a = _UnitVecEmbedder([1.0])
    with pytest.raises(ValueError):
        HybridConcatEmbedder([(a, -1.0)])


def test_all_zero_weights_raises():
    a = _UnitVecEmbedder([1.0])
    b = _UnitVecEmbedder([1.0])
    with pytest.raises(ValueError):
        HybridConcatEmbedder([(a, 0.0), (b, 0.0)])
