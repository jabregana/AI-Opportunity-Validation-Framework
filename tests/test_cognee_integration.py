"""Tests for the CogneePreNormalized integration.

Cognee exposes its API as module-level async functions (you call
`await cognee.add(...)` directly). The tests pass a fake module-like
stub via the `cognee_module` constructor argument so the suite stays
fast, offline, and independent of the real cognee install.
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.service import EntityNormalizer
from runner.service.integrations import CogneePreNormalized


class _FakeCogneeModule:
    """Stub of the cognee module. Records calls so tests can assert
    on what the wrapper forwarded."""

    def __init__(self):
        self.add_calls: list[dict] = []
        self.cognify_calls: list[dict] = []

    async def add(self, data, dataset_name=None, **kwargs):
        self.add_calls.append({
            "data": data,
            "dataset_name": dataset_name,
            "kwargs": kwargs,
        })
        return {"added": True}

    async def cognify(self, *args, **kwargs):
        self.cognify_calls.append({"args": args, "kwargs": kwargs})
        return {"cognified": True}

    async def search(self, query, **kwargs):
        return {"results": [{"call": "search", "query": query}]}

    async def prune(self, *args, **kwargs):
        return {"pruned": True}


def test_requires_mention_map_or_extractor():
    norm = EntityNormalizer("b-raw-identity")
    fake = _FakeCogneeModule()
    with pytest.raises(ValueError):
        CogneePreNormalized(norm, cognee_module=fake)


def test_missing_cognee_raises_helpful_error(monkeypatch):
    """If cognee is not installed and the caller doesn't pass a stub,
    the constructor raises RuntimeError (not ImportError) with a
    helpful install hint."""
    import builtins
    real_import = builtins.__import__

    def stub_import(name, *args, **kwargs):
        if name == "cognee":
            raise ImportError("simulated missing cognee")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", stub_import)
    norm = EntityNormalizer("b-raw-identity")
    with pytest.raises(RuntimeError, match="cognee not installed"):
        CogneePreNormalized(norm, mention_map={"x": "y"})


def test_mention_map_replaces_aliases_in_string_payload():
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={"AAPL": "Apple_Inc", "MSFT": "Microsoft_Corp"},
        )
        await wrapped.add(
            "Bought AAPL today and looking at MSFT next week.",
            dataset_name="trader1",
        )
        assert len(fake.add_calls) == 1
        sent = fake.add_calls[0]["data"]
        assert "AAPL" not in sent
        assert "MSFT" not in sent
        assert "Apple_Inc" in sent
        assert "Microsoft_Corp" in sent
        assert fake.add_calls[0]["dataset_name"] == "trader1"

    asyncio.run(_run())


def test_mention_map_replaces_in_list_payload():
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={"AAPL": "Apple_Inc"},
        )
        await wrapped.add(
            ["AAPL up today", "Watching AAPL", "Random unrelated text"],
            dataset_name="d1",
        )
        sent = fake.add_calls[0]["data"]
        assert isinstance(sent, list)
        assert sent[0] == "Apple_Inc up today"
        assert sent[1] == "Watching Apple_Inc"
        assert sent[2] == "Random unrelated text"  # untouched

    asyncio.run(_run())


def test_non_string_payload_passes_through_unchanged():
    """Cognee's add() can also take file paths or binary data. The
    proxy doesn't normalize those; it just forwards them."""
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={"AAPL": "Apple_Inc"},
        )
        payload = {"file_path": "/some/file.pdf"}  # exotic, not a string
        await wrapped.add(payload, dataset_name="d1")
        assert fake.add_calls[0]["data"] is payload

    asyncio.run(_run())


def test_mention_map_longest_first_avoids_prefix_collisions():
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={
                "Apple Inc": "Apple_Inc_Canonical",
                "Apple": "Apple_Generic",
            },
        )
        await wrapped.add("Apple Inc and just Apple.", dataset_name="d1")
        sent = fake.add_calls[0]["data"]
        assert "Apple_Inc_Canonical" in sent
        assert "Apple_Generic" in sent
        assert "Apple_Generic Inc" not in sent

    asyncio.run(_run())


def test_callable_extractor_invoked():
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()

        def extractor(text):
            spans = []
            idx = 0
            while True:
                i = text.find("Acme", idx)
                if i < 0:
                    break
                spans.append((i, i + 4, "Acme"))
                idx = i + 4
            return spans

        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_extractor=extractor,
        )
        await wrapped.add("Acme is great. Working with Acme.", dataset_name="d1")
        sent = fake.add_calls[0]["data"]
        assert sent.count("Acme") == 2  # identity normalization preserves both

    asyncio.run(_run())


def test_cognify_forwards_unchanged():
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={"x": "y"},
        )
        result = await wrapped.cognify(some_arg="value")
        assert result == {"cognified": True}
        assert fake.cognify_calls[0]["kwargs"] == {"some_arg": "value"}

    asyncio.run(_run())


def test_passes_through_other_module_functions():
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={"x": "y"},
        )
        # search() is on the fake module; wrapper exposes it via __getattr__
        result = await wrapped.search("query about Apple Inc")
        assert result == {"results": [{"call": "search", "query": "query about Apple Inc"}]}

    asyncio.run(_run())


def test_add_without_dataset_name_omits_kwarg():
    """Calling add() without dataset_name should not inject a
    `dataset_name=None` kwarg into the forwarded call; some cognee
    builds may reject None explicitly."""
    async def _run():
        norm = EntityNormalizer("b-raw-identity")
        fake = _FakeCogneeModule()
        wrapped = CogneePreNormalized(
            norm, cognee_module=fake,
            mention_map={"AAPL": "Apple_Inc"},
        )
        await wrapped.add("AAPL up")
        # dataset_name should not have been passed (the fake records
        # the kwarg from its own default, None, which is fine)
        assert fake.add_calls[0]["dataset_name"] is None
        sent = fake.add_calls[0]["data"]
        assert sent == "Apple_Inc up"

    asyncio.run(_run())
