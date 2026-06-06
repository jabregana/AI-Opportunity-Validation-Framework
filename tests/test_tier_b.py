"""Tests for the UC-4.4 Tier B adversarial generator and fixture."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.generators.tier_b_adversarials import (
    mine,
    _cosine,
    _fixture_sha256,
)
from runner.variants.embed_proxy import (
    EmbeddingSchemaProxy,
    HashedTokenEmbedder,
)


# A small deterministic embedder for testing the mining logic without
# needing model2vec or network.


class _PrefixEmbedder:
    """Embedding = one-hot on the first character (lowercased). Pairs
    sharing a first character get cosine=1.0; others get cosine=0.
    Useful for deterministic mining-logic tests."""

    @property
    def dim(self) -> int:
        return 26

    def embed(self, text: str) -> list[float]:
        v = [0.0] * 26
        if text:
            c = text[0].lower()
            if "a" <= c <= "z":
                v[ord(c) - ord("a")] = 1.0
        return v


def test_mine_returns_only_above_threshold_pairs():
    canonicals = ["Apple", "Ant", "Bear", "Banana", "Cat"]
    pairs = mine(canonicals, _PrefixEmbedder(), cosine_threshold=0.9)
    # Apple/Ant share 'a', Bear/Banana share 'b'. Cat is alone.
    assert {(p["a"], p["b"]) for p in pairs} == {
        ("Ant", "Apple"),
        ("Banana", "Bear"),
    }


def test_mine_returns_sorted_descending_by_cosine():
    canonicals = ["Apple", "Ant"]
    pairs = mine(canonicals, _PrefixEmbedder(), cosine_threshold=0.0)
    assert pairs == sorted(pairs, key=lambda p: (-p["cosine"], p["a"], p["b"]))


def test_mine_normalises_pair_order_lexically():
    canonicals = ["Zebra", "Zoo"]
    pairs = mine(canonicals, _PrefixEmbedder(), cosine_threshold=0.5)
    assert pairs[0]["a"] < pairs[0]["b"]


def test_mine_empty_below_threshold():
    canonicals = ["Apple", "Bear"]
    pairs = mine(canonicals, _PrefixEmbedder(), cosine_threshold=0.5)
    assert pairs == []


def test_fixture_sha256_deterministic():
    p1 = [{"a": "A", "b": "B", "cosine": 0.5}]
    p2 = [{"a": "A", "b": "B", "cosine": 0.5}]
    assert _fixture_sha256(p1) == _fixture_sha256(p2)


def test_fixture_sha256_changes_with_cosine():
    p1 = [{"a": "A", "b": "B", "cosine": 0.5}]
    p2 = [{"a": "A", "b": "B", "cosine": 0.6}]
    assert _fixture_sha256(p1) != _fixture_sha256(p2)


# -- demonstration: fixture format + gate concept ------------------------


CONCEPTNET_TIER_B = ROOT / "fixtures" / "adversarials" / "conceptnet_tier_b.json"


@pytest.mark.skipif(
    not CONCEPTNET_TIER_B.exists(),
    reason="run `python -m fixtures.generators.tier_b_adversarials ...` first",
)
def test_v010_does_not_alias_tier_b_pairs():
    """v0.1.0 (HashedTokenEmbedder) should pass the Tier B gate cleanly:
    the hard negatives mined by the neural embedder have no shared
    tokens, so token-overlap cosine is 0 and no aliasing occurs."""
    fixture = json.loads(CONCEPTNET_TIER_B.read_text())
    false_merges = 0
    for pair in fixture["pairs"]:
        p = EmbeddingSchemaProxy(
            embedder=HashedTokenEmbedder(),
            similarity_threshold=0.7,
        )
        p.align(pair["a"])
        p.align(pair["b"])
        if p.canonical_count == 1:
            false_merges += 1
    rate = false_merges / fixture["n_pairs"]
    assert rate == 0.0, (
        f"v0.1.0 should not alias any neural-embedder hard negatives, "
        f"got false-merge rate {rate:.3f} ({false_merges}/{fixture['n_pairs']})"
    )
