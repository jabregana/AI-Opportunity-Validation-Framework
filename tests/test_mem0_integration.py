"""Tests for the Mem0PreNormalized integration.

Uses a fake Memory stub (no actual Mem0 calls) so the test suite stays
fast and offline.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.service import EntityNormalizer
from runner.service.integrations import Mem0PreNormalized


class _FakeMem0:
    """Stand-in for mem0.Memory: records what gets passed to add()."""

    def __init__(self):
        self.calls: list[dict] = []

    def add(self, messages, user_id=None, **kwargs):
        self.calls.append({"messages": messages, "user_id": user_id, "kwargs": kwargs})
        return {"results": [{"memory": str(messages)}]}

    def search(self, *args, **kwargs):
        return {"results": [{"call": "search"}]}


def test_requires_mention_map_or_extractor():
    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")
    with pytest.raises(ValueError):
        Mem0PreNormalized(fake, norm)


def test_mention_map_replaces_aliases_in_string_input():
    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")
    wrapped = Mem0PreNormalized(
        fake, norm,
        mention_map={"AAPL": "Apple_Inc", "MSFT": "Microsoft_Corp"},
    )
    wrapped.add("Bought AAPL today and looking at MSFT next week.", user_id="trader1")
    assert len(fake.calls) == 1
    # AAPL replaced with normalize("Apple_Inc") -> "Apple_Inc" (b-raw is identity)
    sent = fake.calls[0]["messages"]
    assert "AAPL" not in sent
    assert "MSFT" not in sent
    assert "Apple_Inc" in sent
    assert "Microsoft_Corp" in sent


def test_mention_map_handles_message_list_format():
    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")
    wrapped = Mem0PreNormalized(
        fake, norm,
        mention_map={"AAPL": "Apple_Inc"},
    )
    wrapped.add(
        [{"role": "user", "content": "What about AAPL?"},
         {"role": "assistant", "content": "Looking at AAPL now."}],
        user_id="u",
    )
    sent = fake.calls[0]["messages"]
    assert all("AAPL" not in m["content"] for m in sent)
    assert all("Apple_Inc" in m["content"] for m in sent)


def test_passes_through_other_methods():
    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")
    wrapped = Mem0PreNormalized(fake, norm, mention_map={"x": "y"})
    result = wrapped.search("query")
    assert result == {"results": [{"call": "search"}]}


def test_callable_extractor_called_per_input():
    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")

    def extractor(text):
        # Detect "Acme" anywhere; return its spans
        spans = []
        idx = 0
        while True:
            i = text.find("Acme", idx)
            if i < 0:
                break
            spans.append((i, i + 4, "Acme"))
            idx = i + 4
        return spans

    wrapped = Mem0PreNormalized(
        fake, norm,
        mention_extractor=extractor,
    )
    wrapped.add("Acme is great. Working with Acme.", user_id="u")
    sent = fake.calls[0]["messages"]
    # "Acme" was extracted twice; normalize is identity so unchanged
    assert sent.count("Acme") == 2


def test_dict_replacement_handles_longest_first():
    """Avoid prefix collisions: 'Apple Inc' replaced before 'Apple'."""
    fake = _FakeMem0()
    norm = EntityNormalizer("b-raw-identity")
    wrapped = Mem0PreNormalized(
        fake, norm,
        mention_map={
            "Apple Inc": "Apple_Inc_Canonical",
            "Apple": "Apple_Generic",
        },
    )
    wrapped.add("Apple Inc and just Apple.", user_id="u")
    sent = fake.calls[0]["messages"]
    assert "Apple_Inc_Canonical" in sent
    assert "Apple_Generic" in sent
    # "Apple Inc" shouldn't have been partially replaced as "Apple_Generic Inc"
    assert "Apple_Generic Inc" not in sent
