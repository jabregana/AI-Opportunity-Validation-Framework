from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math

import pytest

from runner.variants.embed_proxy import (
    EmbeddingSchemaProxy,
    HashedTokenEmbedder,
    _cosine,
    _tokens,
)


# -- _tokens ---------------------------------------------------------------


def test_tokens_lowercase():
    assert _tokens("WorksAt") == ["works", "at"]


def test_tokens_underscore_split():
    assert _tokens("works_at") == ["works", "at"]
    assert _tokens("WORKS_AT") == ["works", "at"]


def test_tokens_camel_split():
    assert _tokens("IsAKindOf") == ["is", "a", "kind", "of"]


def test_tokens_mixed_separators():
    assert _tokens("has-PartOf_thing") == ["has", "part", "of", "thing"]


def test_tokens_empty():
    assert _tokens("") == []
    assert _tokens("___") == []


# -- HashedTokenEmbedder ---------------------------------------------------


def test_embedder_deterministic():
    e = HashedTokenEmbedder()
    assert e.embed("WORKS_AT") == e.embed("WORKS_AT")


def test_embedder_case_underscore_variants_identical():
    e = HashedTokenEmbedder()
    for variant in ["WORKS_AT", "works_at", "WorksAt", "Works At", "works  at"]:
        assert e.embed(variant) == e.embed("WORKS_AT")


def test_embedder_l2_normalized():
    e = HashedTokenEmbedder()
    for txt in ["IsA", "PartOf", "has_subevent", "MotivatedByGoal"]:
        v = e.embed(txt)
        norm = math.sqrt(sum(x * x for x in v))
        assert math.isclose(norm, 1.0, abs_tol=1e-9), f"{txt!r} norm = {norm}"


def test_embedder_empty_text_is_zero_vector():
    e = HashedTokenEmbedder()
    assert e.embed("") == [0.0] * e.dim
    assert e.embed("___") == [0.0] * e.dim


def test_embedder_disjoint_tokens_have_low_similarity():
    e = HashedTokenEmbedder()
    sim = _cosine(e.embed("IsA"), e.embed("MadeOf"))
    # Disjoint token sets land in different hash buckets. Similarity
    # may be slightly non-zero from sign-collisions but should be small.
    assert abs(sim) < 0.3


def test_embedder_partial_overlap_intermediate_similarity():
    e = HashedTokenEmbedder()
    # ["part", "of"] vs ["kind", "of"] share "of" — one token of two.
    sim = _cosine(e.embed("part_of"), e.embed("kind_of"))
    # Half of the tokens overlap, so cosine should be around 0.5.
    assert 0.3 < sim < 0.7


def test_embedder_dim_min_enforced():
    with pytest.raises(ValueError):
        HashedTokenEmbedder(dim=4)


# -- EmbeddingSchemaProxy --------------------------------------------------


def test_proxy_first_write_becomes_canonical():
    p = EmbeddingSchemaProxy()
    assert p.align("works_at") == "works_at"
    assert p.canonical_count == 1


def test_proxy_cached_identical_input():
    p = EmbeddingSchemaProxy()
    a = p.align("works_at")
    b = p.align("works_at")
    assert a == b
    assert p.canonical_count == 1


def test_proxy_case_underscore_variants_alias_to_first():
    p = EmbeddingSchemaProxy(similarity_threshold=0.7)
    canonical = p.align("WORKS_AT")
    # All these have identical normalized tokens, cosine = 1.0
    for v in ["works_at", "WorksAt", "Works At"]:
        assert p.align(v) == canonical
    assert p.canonical_count == 1


def test_proxy_disjoint_relations_get_separate_canonicals():
    p = EmbeddingSchemaProxy(similarity_threshold=0.7)
    p.align("IsA")
    p.align("MadeOf")
    p.align("CausesDesire")
    assert p.canonical_count == 3


def test_proxy_threshold_one_never_merges():
    # With threshold = 1.0, only perfect token-identical variants alias.
    p = EmbeddingSchemaProxy(similarity_threshold=1.0)
    p.align("part_of")
    p.align("kind_of")  # shares "of"; cosine ~= 0.5 < 1.0
    assert p.canonical_count == 2


def test_proxy_threshold_below_zero_aliases_everything():
    # With threshold = -1.0, even disjoint embeddings alias (cosine >= -1).
    p = EmbeddingSchemaProxy(similarity_threshold=-1.0)
    p.align("IsA")
    p.align("MadeOf")  # totally disjoint, but threshold = -1 forces aliasing
    assert p.canonical_count == 1


def test_proxy_threshold_invalid_raises():
    with pytest.raises(ValueError):
        EmbeddingSchemaProxy(similarity_threshold=1.5)
    with pytest.raises(ValueError):
        EmbeddingSchemaProxy(similarity_threshold=-1.5)


def test_proxy_first_writer_wins_canonical_name():
    p = EmbeddingSchemaProxy(similarity_threshold=0.5)
    first = p.align("WORKS_AT")
    second = p.align("works_at")  # would alias to first
    assert first == "WORKS_AT"
    assert second == "WORKS_AT"  # not "works_at"


class _ConstantEmbedder:
    """Returns the same vector for every input. All inputs end up
    in one canonical because cosine = 1.0 to the only existing canonical.
    Used to verify the variant works with an arbitrary Embedder
    implementation, not just HashedTokenEmbedder."""

    def __init__(self, dim: int = 8):
        self._dim = dim
        self._vec = [1.0 / math.sqrt(dim)] * dim  # L2-normalized

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return list(self._vec)


def test_proxy_works_with_arbitrary_embedder():
    p = EmbeddingSchemaProxy(embedder=_ConstantEmbedder(), similarity_threshold=0.5)
    p.align("foo")
    p.align("bar")  # cosine to "foo" = 1.0, aliases
    p.align("baz")  # same
    assert p.canonical_count == 1
