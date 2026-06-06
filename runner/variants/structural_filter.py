"""Deterministic structural filter for schema-alignment merge decisions.

Used as a merge_guard callback to EmbeddingSchemaProxy. The filter runs
AFTER the embedding-based similarity match clears its threshold. It
blocks merges that violate one of two structural rules even when the
embedding says they are close.

The two rules came from observed failures on the WikiData Tier B
gauntlet (commit 52fb9f2):

  Rule 1: digit content differs.
    "ISO 639-1 code" vs "ISO 639-2 code"     -> blocked
    "ISO 3166-1 alpha-2 code" vs "alpha-3"   -> blocked
    Numeric tokens encode versions, codes, IDs. Different numbers
    almost always denote distinct concepts.

  Rule 2: trailing closed-class preposition asymmetry.
    "review score" vs "review score by"      -> blocked
    "score" vs "score for"                   -> blocked
    A preposition added to a relation typically flips the semantic
    role of the relation (subject vs object, agent vs patient). The
    underlying entity is the same word but the role is different.

The filter does NOT touch:
  - Case / underscore / camelCase variants (WORKS_AT vs WorksAt)
  - True paraphrases that share no digits and no prepositional suffix
    (IsA vs INSTANCE_OF)

Lives at the variant boundary because it is variant-specific logic.
For multi-variant deployment, each variant chooses whether to wire it.
"""
from __future__ import annotations
import re

_DIGITS_RE = re.compile(r"\d+")

# Closed-class English prepositions and a few connective adverbs commonly
# observed flipping semantic roles in WikiData property names. Kept short
# and curated rather than open-ended.
_TRAILING_FUNCTION_WORDS = frozenset(
    {
        "by", "of", "for", "to", "in", "on", "at", "with", "from",
        "as", "into", "over", "under", "about", "through", "via",
    }
)


def _normalize(text: str) -> str:
    """Lowercase, collapse separators and whitespace."""
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.lower().split())


def _digit_tokens(text: str) -> list[str]:
    """All numeric substrings in input order."""
    return _DIGITS_RE.findall(text)


def _words(text: str) -> list[str]:
    return _normalize(text).split()


def block_on_digit_mismatch(a: str, b: str) -> bool:
    """Returns True if digit content differs between a and b."""
    return _digit_tokens(a) != _digit_tokens(b)


def block_on_trailing_function_word(a: str, b: str) -> bool:
    """Returns True if one input is the other plus a single trailing
    function word.

    Catches "score" vs "score by", "review score" vs "review score for",
    etc. Symmetric: argument order does not matter.
    """
    wa = _words(a)
    wb = _words(b)
    if wa == wb:
        return False
    shorter, longer = (wa, wb) if len(wa) < len(wb) else (wb, wa)
    if len(longer) - len(shorter) != 1:
        return False
    if longer[: len(shorter)] != shorter:
        return False
    return longer[-1] in _TRAILING_FUNCTION_WORDS


def structural_merge_guard(input_relation: str, candidate_canonical: str) -> bool:
    """merge_guard callable: True = allow the embedding-based merge,
    False = block it and force a new canonical to be minted."""
    if block_on_digit_mismatch(input_relation, candidate_canonical):
        return False
    if block_on_trailing_function_word(input_relation, candidate_canonical):
        return False
    return True
