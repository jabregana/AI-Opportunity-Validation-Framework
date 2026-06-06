"""Tests for the structural merge filter (v0.3.1)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.variants.embed_proxy import (
    EmbeddingSchemaProxy,
    HashedTokenEmbedder,
)
from runner.variants.structural_filter import (
    _digit_tokens,
    _words,
    block_on_digit_mismatch,
    block_on_trailing_function_word,
    structural_merge_guard,
)


# -- _digit_tokens, _words --------------------------------------------------


def test_digit_tokens():
    assert _digit_tokens("ISO 639-1 code") == ["639", "1"]
    assert _digit_tokens("ISO 3166-1 alpha-2 code") == ["3166", "1", "2"]
    assert _digit_tokens("review score") == []
    assert _digit_tokens("v1.2.3 release") == ["1", "2", "3"]


def test_words_normalization():
    assert _words("WORKS_AT") == ["works", "at"]
    assert _words("ISO-3166-1") == ["iso", "3166", "1"]
    assert _words("review  score") == ["review", "score"]


# -- block_on_digit_mismatch -----------------------------------------------


def test_digit_mismatch_blocks_iso_versions():
    assert block_on_digit_mismatch("ISO 639-1 code", "ISO 639-2 code")
    assert block_on_digit_mismatch("ISO 3166-1 alpha-2 code", "ISO 3166-1 alpha-3 code")
    assert block_on_digit_mismatch("alpha-2", "alpha-3")


def test_digit_mismatch_allows_same_digits():
    assert not block_on_digit_mismatch("ISO 639-1 code", "iso 639 1 language code")
    assert not block_on_digit_mismatch("review score", "review score by")
    assert not block_on_digit_mismatch("works_at", "WORKS_AT")


# -- block_on_trailing_function_word ---------------------------------------


def test_trailing_preposition_blocks_review_score_by():
    assert block_on_trailing_function_word("review score", "review score by")
    assert block_on_trailing_function_word("review score by", "review score")  # symmetric


def test_trailing_preposition_blocks_assorted():
    for prep in ["by", "of", "for", "to", "in", "with", "from"]:
        assert block_on_trailing_function_word("place", f"place {prep}")


def test_trailing_preposition_allows_when_not_prefix():
    # "score by team" is not "review score" + extra preposition
    assert not block_on_trailing_function_word("review score", "score by team")


def test_trailing_preposition_allows_when_more_than_one_extra():
    assert not block_on_trailing_function_word("review score", "review score by team")


def test_trailing_preposition_allows_when_extra_word_is_content():
    assert not block_on_trailing_function_word("review score", "review score total")


def test_trailing_preposition_allows_identical():
    assert not block_on_trailing_function_word("WORKS_AT", "works_at")


# -- structural_merge_guard end-to-end --------------------------------------


def test_guard_blocks_known_v030_failures():
    """The three pairs v0.3.0 false-merged on WikiData Tier B."""
    pairs = [
        ("review score", "review score by"),
        ("ISO 3166-1 alpha-2 code", "ISO 3166-1 alpha-3 code"),
        ("ISO 3166-1 alpha-2 code", "ISO 3166-2 code"),
    ]
    for a, b in pairs:
        assert structural_merge_guard(a, b) is False, (
            f"guard should block {a!r} <-> {b!r} but did not"
        )


def test_guard_allows_case_underscore_variants():
    """Case and underscore variants must still merge under any sane
    structural filter."""
    pairs = [
        ("WORKS_AT", "works_at"),
        ("IsA", "is_a"),
        ("part_of", "PART_OF"),
        ("HasA", "has_a"),
    ]
    for a, b in pairs:
        assert structural_merge_guard(a, b) is True, (
            f"guard should allow {a!r} <-> {b!r} but blocked"
        )


def test_guard_allows_true_paraphrases():
    """The filter is structural, not semantic. True paraphrases that
    share no digits and no prepositional suffix must pass through."""
    pairs = [
        ("IsA", "INSTANCE_OF"),
        ("Causes", "leads_to"),
        ("UsedFor", "purpose_of"),  # both end in "_of"; not the asymmetric case
    ]
    for a, b in pairs:
        assert structural_merge_guard(a, b) is True, (
            f"guard should allow {a!r} <-> {b!r} but blocked"
        )


# -- integration with EmbeddingSchemaProxy --------------------------------


def test_proxy_with_blocking_guard_mints_new_canonical():
    """When the merge_guard says no, the proxy mints a new canonical
    instead of returning the matched one."""
    # A guard that always blocks
    always_block = lambda _a, _b: False
    p = EmbeddingSchemaProxy(
        embedder=HashedTokenEmbedder(),
        similarity_threshold=0.7,
        merge_guard=always_block,
    )
    p.align("WORKS_AT")
    p.align("works_at")  # would alias, but blocked
    assert p.canonical_count == 2


def test_proxy_with_allowing_guard_behaves_like_default():
    always_allow = lambda _a, _b: True
    p = EmbeddingSchemaProxy(
        embedder=HashedTokenEmbedder(),
        similarity_threshold=0.7,
        merge_guard=always_allow,
    )
    p.align("WORKS_AT")
    p.align("works_at")
    assert p.canonical_count == 1


def test_proxy_with_structural_guard_blocks_iso_digits():
    p = EmbeddingSchemaProxy(
        embedder=HashedTokenEmbedder(),
        similarity_threshold=0.5,
        merge_guard=structural_merge_guard,
    )
    p.align("ISO 639-1 code")
    p.align("ISO 639-2 code")  # high token overlap, but digits differ
    assert p.canonical_count == 2
