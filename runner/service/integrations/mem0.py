"""Mem0PreNormalized — proxy as pre-normalization middleware for Mem0.

Wraps the public Mem0 v3 OSS Memory client so that entity surface
forms in input text are normalized through the EntityNormalizer
before Mem0's LLM sees the message. This:

  - Reduces fragmentation in Mem0's downstream store (fewer duplicate
    entries for the same entity under different aliases)
  - Hypothetically reduces LLM extraction costs (the LLM sees more
    consistent inputs, may produce fewer redundant extractions)
  - Is a drop-in pattern: existing Mem0 users keep their Mem0 setup
    and add this wrapper

Mention extraction is the hard part. This module supports two modes:

  1. dict-based replacement (the simple, exact-match approach):
     pass a `mention_map: dict[str, str]` mapping aliases to canonical
     forms. The wrapper replaces every occurrence in the input text
     before forwarding to Mem0. Best for narrow domains with a known
     alias list.

  2. callable extractor (extensibility hook):
     pass a `mention_extractor: Callable[[str], list[tuple[int, int, str]]]`
     that returns (start, end, surface) spans. Replace each span with
     the normalized canonical form. Users can plug in spaCy NER,
     regex, an LLM call, or any other extractor.

Neither mode is built into Mem0; both are pure middleware on top.

NOTE: This integration depends on `mem0ai` being installed. It is
optional. Import will raise ImportError if mem0ai is missing.
"""
from __future__ import annotations
import re
from typing import Any, Callable

from ..normalizer import EntityNormalizer


class Mem0PreNormalized:
    """Drop-in wrapper around a Mem0 v3 Memory client. Public surface
    matches Mem0's `add()` signature so existing code can swap it in.

    The wrapped Memory's other methods (search, get, delete) pass
    through unchanged via __getattr__.
    """

    def __init__(
        self,
        memory: Any,
        normalizer: EntityNormalizer,
        *,
        mention_map: dict[str, str] | None = None,
        mention_extractor: Callable[[str], list[tuple[int, int, str]]] | None = None,
    ):
        if mention_map is None and mention_extractor is None:
            raise ValueError(
                "must provide mention_map (dict[alias, canonical]) or "
                "mention_extractor (callable returning spans)"
            )
        self._memory = memory
        self._normalizer = normalizer
        self._mention_map = mention_map or {}
        self._extractor = mention_extractor

    def add(self, messages: str | list, user_id: str | None = None, **kwargs):
        """Pre-normalize entity mentions in `messages` before forwarding
        to Mem0. Returns whatever Mem0.add() returns."""
        if isinstance(messages, str):
            normalized = self._normalize_text(messages, user_id)
        elif isinstance(messages, list):
            normalized = [
                {**msg, "content": self._normalize_text(msg.get("content", ""), user_id)}
                if isinstance(msg, dict) else msg
                for msg in messages
            ]
        else:
            normalized = messages
        return self._memory.add(normalized, user_id=user_id, **kwargs)

    def _normalize_text(self, text: str, user_id: str | None) -> str:
        """Apply mention_map first (single-pass regex) then run callable extractor."""
        out = text
        # Single-pass regex with longest-first alternation. This
        # prevents prefix collisions (replacing "Apple Inc" then
        # touching the canonical it produced when "Apple" is replaced)
        # because each character position in the original text is
        # consumed at most once by the regex engine.
        if self._mention_map:
            aliases_longest_first = sorted(self._mention_map, key=len, reverse=True)
            pattern = re.compile(
                "|".join(re.escape(a) for a in aliases_longest_first)
            )

            def _sub(match):
                alias = match.group(0)
                canonical_raw = self._mention_map[alias]
                return self._normalizer.normalize(
                    canonical_raw,
                    context={"source_id": user_id} if user_id else None,
                )

            out = pattern.sub(_sub, out)
        # Callable extractor: per-span replacement (right-to-left so
        # offsets stay valid as the string mutates).
        if self._extractor is not None:
            spans = list(self._extractor(out))
            spans.sort(key=lambda s: -s[0])
            for start, end, surface in spans:
                canonical = self._normalizer.normalize(
                    surface,
                    context={"source_id": user_id} if user_id else None,
                )
                out = out[:start] + canonical + out[end:]
        return out

    def __getattr__(self, name):
        # Pass through other Mem0 methods (search, get, delete, etc.)
        return getattr(self._memory, name)
