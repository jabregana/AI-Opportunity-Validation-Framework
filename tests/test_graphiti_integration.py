"""Tests for the GraphitiPreNormalized integration.

Uses a fake async Graphiti stub (no actual graphiti-core dependency,
no Neo4j) so the test suite stays fast and offline. The wrapper's
contract is the same shape as Mem0PreNormalized but the entry points
are async.
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
from runner.service.integrations import GraphitiPreNormalized


class _FakeGraphiti:
    """Stand-in for graphiti.Graphiti: records what gets passed to
    add_episode / add_episode_bulk."""

    def __init__(self):
        self.add_episode_calls: list[dict] = []
        self.add_episode_bulk_calls: list[dict] = []

    async def add_episode(self, name, episode_body, **kwargs):
        self.add_episode_calls.append({
            "name": name,
            "episode_body": episode_body,
            "kwargs": kwargs,
        })
        return {"uuid": f"ep_{len(self.add_episode_calls)}"}

    async def add_episode_bulk(self, episodes, **kwargs):
        self.add_episode_bulk_calls.append({
            "episodes": episodes,
            "kwargs": kwargs,
        })
        return {"count": len(episodes)}

    async def search(self, *args, **kwargs):
        return {"results": [{"call": "search"}]}


def test_requires_mention_map_or_extractor():
    fake = _FakeGraphiti()
    norm = EntityNormalizer("b-raw-identity")
    with pytest.raises(ValueError):
        GraphitiPreNormalized(fake, norm)


def test_mention_map_replaces_aliases_in_episode_body():
    async def _run():
        fake = _FakeGraphiti()
        norm = EntityNormalizer("b-raw-identity")
        wrapped = GraphitiPreNormalized(
            fake, norm,
            mention_map={"AAPL": "Apple_Inc", "MSFT": "Microsoft_Corp"},
        )
        await wrapped.add_episode(
            name="trade-log-2026-06-06",
            episode_body="Bought AAPL today and looking at MSFT next week.",
            group_id="trader1",
        )
        assert len(fake.add_episode_calls) == 1
        sent = fake.add_episode_calls[0]["episode_body"]
        assert "AAPL" not in sent
        assert "MSFT" not in sent
        assert "Apple_Inc" in sent
        assert "Microsoft_Corp" in sent

    asyncio.run(_run())


def test_mention_map_longest_first_avoids_prefix_collisions():
    async def _run():
        fake = _FakeGraphiti()
        norm = EntityNormalizer("b-raw-identity")
        wrapped = GraphitiPreNormalized(
            fake, norm,
            mention_map={
                "Apple Inc": "Apple_Inc_Canonical",
                "Apple": "Apple_Generic",
            },
        )
        await wrapped.add_episode(
            name="apple-news",
            episode_body="Apple Inc and just Apple.",
            group_id="g1",
        )
        sent = fake.add_episode_calls[0]["episode_body"]
        assert "Apple_Inc_Canonical" in sent
        assert "Apple_Generic" in sent
        assert "Apple_Generic Inc" not in sent

    asyncio.run(_run())


def test_callable_extractor_invoked():
    async def _run():
        fake = _FakeGraphiti()
        norm = EntityNormalizer("b-raw-identity")

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

        wrapped = GraphitiPreNormalized(
            fake, norm,
            mention_extractor=extractor,
        )
        await wrapped.add_episode(
            name="acme-update",
            episode_body="Acme is great. Working with Acme.",
            group_id="g1",
        )
        sent = fake.add_episode_calls[0]["episode_body"]
        assert sent.count("Acme") == 2

    asyncio.run(_run())


def test_passes_through_other_methods():
    async def _run():
        fake = _FakeGraphiti()
        norm = EntityNormalizer("b-raw-identity")
        wrapped = GraphitiPreNormalized(fake, norm, mention_map={"x": "y"})
        result = await wrapped.search("query")
        assert result == {"results": [{"call": "search"}]}

    asyncio.run(_run())


def test_bulk_episodes_get_their_bodies_normalized():
    class _RawEpisode:
        """Minimal episode-like object that the wrapper should mutate."""
        def __init__(self, name, body):
            self.name = name
            self.episode_body = body

    async def _run():
        fake = _FakeGraphiti()
        norm = EntityNormalizer("b-raw-identity")
        wrapped = GraphitiPreNormalized(
            fake, norm,
            mention_map={"AAPL": "Apple_Inc"},
        )
        episodes = [
            _RawEpisode("e1", "AAPL up today"),
            _RawEpisode("e2", "Watching AAPL"),
        ]
        await wrapped.add_episode_bulk(episodes=episodes, group_id="g")
        assert len(fake.add_episode_bulk_calls) == 1
        sent_eps = fake.add_episode_bulk_calls[0]["episodes"]
        assert all("AAPL" not in ep.episode_body for ep in sent_eps)
        assert all("Apple_Inc" in ep.episode_body for ep in sent_eps)

    asyncio.run(_run())
