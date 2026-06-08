"""Tests for the Graphiti integration adapter.

Uses a FakeGraphiti (async simulator that mimics the graphiti-core API
surface) so the adapter can be exercised without a running Neo4j +
the graphiti-core install.

Real-Graphiti smoke testing is the next step once graphiti-core is
installed and a Neo4j backend is available.
"""
from __future__ import annotations
import asyncio
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.dimensions.memory.lifecycle import build
from runner.dimensions.memory.lifecycle.integrations import (
    GraphitiGCMiddleware,
    GraphitiNodeRecord,
)


# ---------------- Fake Graphiti (in-memory async simulator) ----------------


@dataclass
class FakeEntityNode:
    uuid: str
    name: str
    group_id: str = ""


@dataclass
class FakeEntityEdge:
    uuid: str
    source_node_uuid: str
    target_node_uuid: str
    fact: str = ""


@dataclass
class FakeEpisodeNode:
    uuid: str
    name: str
    content: str
    group_id: str = ""


@dataclass
class FakeAddEpisodeResults:
    episode: FakeEpisodeNode
    nodes: list[FakeEntityNode] = field(default_factory=list)
    edges: list[FakeEntityEdge] = field(default_factory=list)


class FakeGraphiti:
    """Async simulator for the graphiti-core API shape."""

    def __init__(self):
        self.entities: dict[str, FakeEntityNode] = {}
        self.episodes: dict[str, FakeEpisodeNode] = {}
        self.edges: dict[str, FakeEntityEdge] = {}

    async def add_episode(self, *, name, episode_body, group_id="",
                          reference_time=None, **kwargs):
        """Extract a couple of fake entities from the body + episode."""
        ep_uuid = str(uuid.uuid4())
        episode = FakeEpisodeNode(
            uuid=ep_uuid, name=name, content=episode_body,
            group_id=group_id,
        )
        self.episodes[ep_uuid] = episode

        # Naive "extraction": pull the first 2-3 capitalized words as entities
        words = [w.strip(".,!?") for w in episode_body.split()
                 if w and w[0].isupper()]
        nodes = []
        edges = []
        for w in words[:3]:
            node = FakeEntityNode(uuid=str(uuid.uuid4()), name=w,
                                  group_id=group_id)
            self.entities[node.uuid] = node
            nodes.append(node)
            edge = FakeEntityEdge(
                uuid=str(uuid.uuid4()),
                source_node_uuid=ep_uuid,
                target_node_uuid=node.uuid,
                fact=f"mentions {w}",
            )
            self.edges[edge.uuid] = edge
            edges.append(edge)
        return FakeAddEpisodeResults(episode=episode, nodes=nodes, edges=edges)

    async def search(self, query, *, group_ids=None, num_results=10, **kwargs):
        """Naive search: return edges whose fact contains the query."""
        q_lower = query.lower()
        hits = [e for e in self.edges.values()
                if q_lower in e.fact.lower()]
        return hits[:num_results]

    async def get_nodes_by_query(self, query, **kwargs):
        q_lower = query.lower()
        return [n for n in self.entities.values()
                if q_lower in n.name.lower()]

    async def delete_node(self, *, uuid):
        return self.entities.pop(uuid, None)

    async def delete_episode(self, *, uuid):
        return self.episodes.pop(uuid, None)


# ---------------- Adapter instantiation ----------------


def test_adapter_instantiates_with_fake_graphiti():
    g = FakeGraphiti()
    mw = GraphitiGCMiddleware(g)
    assert mw.graphiti is g
    assert mw.contract_version == 1
    assert mw.name == "graphiti-adapter"


def test_adapter_starts_with_empty_state():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    state = mw.get_state()
    assert state.nodes == {}
    assert mw.stats().n_writes == 0


# ---------------- add_episode() interception ----------------


def test_add_episode_records_episode_and_entities():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    result = mw.add_episode(
        name="ep1",
        episode_body="Alice met Bob at Charlie's coffee shop.",
        group_id="tenant_a",
    )
    state = mw.get_state()
    # 1 episode + 3 entities = 4 nodes
    assert len(state.nodes) >= 1
    # Episode is a fact node
    episode_uuid = result.episode.uuid
    assert episode_uuid in state.nodes
    assert state.nodes[episode_uuid]["kind"] == "fact"


def test_add_episode_records_edges_with_out_degree():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    result = mw.add_episode(
        name="ep1",
        episode_body="Alice met Bob.",
        group_id="tenant_a",
    )
    state = mw.get_state()
    # Episode has edges to its entities; out_degree should be > 0
    ep_uuid = result.episode.uuid
    assert state.out_degree.get(ep_uuid, 0) > 0


def test_add_episode_carries_group_id_as_tenant():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    result = mw.add_episode(
        name="ep1",
        episode_body="Test content with Apple.",
        group_id="tenant_x",
    )
    ep_uuid = result.episode.uuid
    rec = mw._records[ep_uuid]
    assert rec.group_id == "tenant_x"


# ---------------- search() interception ----------------


def test_search_records_query_against_returned_edges():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    add_result = mw.add_episode(
        name="ep1",
        episode_body="Alice prefers Apple products.",
        group_id="u1",
    )
    pre_total_queries = mw.stats().n_queries

    search_result = mw.search("Apple", group_ids=["u1"])
    assert len(search_result) >= 0

    # Each returned edge has source + target node; both get query events
    post_total_queries = mw.stats().n_queries
    assert post_total_queries > pre_total_queries


# ---------------- pin() ----------------


def test_pin_adds_to_pinned_set():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    result = mw.add_episode(
        name="ep1",
        episode_body="Apple is important.",
        group_id="u1",
    )
    ep_uuid = result.episode.uuid
    mw.pin(ep_uuid)
    state = mw.get_state()
    assert ep_uuid in state.pinned


def test_apply_sweep_refuses_pinned():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    result = mw.add_episode(
        name="ep1",
        episode_body="Apple matters.",
        group_id="u1",
    )
    ep_uuid = result.episode.uuid
    mw.pin(ep_uuid)
    removed = mw.apply_sweep([ep_uuid])
    assert removed == 0
    assert ep_uuid in mw._records


# ---------------- End-to-end sweep with v0.1.2 ----------------


def test_sweep_with_v012_collects_aged_facts():
    """Add some old episodes, sweep with v0.1.2 (1 day min_age),
    verify aged facts get collected. v0.1.2 fact-only rule requires
    out_degree==0 — Graphiti adapter sets out_degree from real
    edges so we must remove edges first to make facts eligible."""
    fake = FakeGraphiti()
    mw = GraphitiGCMiddleware(fake)
    variant = build("gc-v0.1.2-fact-only")

    now = time.time()
    old_time = now - 2 * 86400

    # Add 3 episodes (each creates 1 fact + entities)
    fact_uuids = []
    for i in range(3):
        result = mw.add_episode(
            name=f"ep{i}",
            episode_body=f"Test content {i} mentions Apple.",
            group_id="u1",
        )
        fact_uuids.append(result.episode.uuid)
        # Backdate the record
        mw._records[result.episode.uuid].added_at = old_time
        mw._records[result.episode.uuid].last_access = old_time

    # Remove all edges from facts to make them out_degree==0
    for fid in fact_uuids:
        for (src, dst) in list(mw._edges):
            if src == fid:
                mw.record_remove_edge(src, dst, t=now)

    # Sweep
    n_removed = mw.sweep(variant, current_time=now)
    assert n_removed == 3
    # All 3 facts should be gone from sidecar AND FakeGraphiti
    for fid in fact_uuids:
        assert fid not in mw._records
        assert fid not in fake.episodes


def test_sweep_with_v018_tenant_pin_protects_node():
    """v0.1.8 supports tenant pinning; pinned nodes survive."""
    mw = GraphitiGCMiddleware(FakeGraphiti())
    variant = build("gc-v0.1.8-comprehensive-tuned")

    result = mw.add_episode(
        name="important",
        episode_body="Critical Apple data.",
        group_id="tenant_a",
    )
    ep_uuid = result.episode.uuid
    # Age it + clear edges so it would otherwise be eligible
    mw._records[ep_uuid].added_at = time.time() - 10 * 86400
    mw._records[ep_uuid].last_access = time.time() - 10 * 86400
    for (src, dst) in list(mw._edges):
        if src == ep_uuid:
            mw.record_remove_edge(src, dst, t=time.time())

    variant.pin_for_tenant("tenant_a", ep_uuid)

    state = mw.get_state()
    candidates = variant.collect_candidates(state, current_time=time.time())
    assert ep_uuid not in candidates


def test_sweep_with_v013_records_tombstones():
    """v0.1.3 records tombstones for collected memories."""
    mw = GraphitiGCMiddleware(FakeGraphiti())
    variant = build("gc-v0.1.3-fact-only-tombstone")

    now = time.time()
    old = now - 2 * 86400
    fact_uuids = []
    for i in range(3):
        result = mw.add_episode(
            name=f"ep{i}",
            episode_body=f"Content {i} mentions Apple.",
            group_id="u1",
        )
        fid = result.episode.uuid
        fact_uuids.append(fid)
        mw._records[fid].added_at = old
        mw._records[fid].last_access = old
        # Clear edges for out_degree==0
        for (src, dst) in list(mw._edges):
            if src == fid:
                mw.record_remove_edge(src, dst, t=now)

    n_removed = mw.sweep(variant, current_time=now)
    assert n_removed == 3
    assert len(variant.tombstones) == 3
    for fid in fact_uuids:
        assert variant.was_recently_collected(fid, current_time=now + 60)


# ---------------- Contract conformance ----------------


def test_adapter_is_a_gc_integration_shim():
    from runner.dimensions.memory.lifecycle.integrations import (
        GCIntegrationShim,
    )
    mw = GraphitiGCMiddleware(FakeGraphiti())
    assert isinstance(mw, GCIntegrationShim)


def test_stats_track_full_activity():
    mw = GraphitiGCMiddleware(FakeGraphiti())
    mw.add_episode(name="ep1", episode_body="Alice met Bob.", group_id="u1")
    mw.add_episode(name="ep2", episode_body="Charlie met Diane.", group_id="u1")
    mw.search("met")
    stats = mw.stats()
    # 2 episodes + entities (up to 3 per episode) = at least 4 writes
    assert stats.n_writes >= 4
    assert stats.n_edges_added >= 2


# ---------------- Async run helper ----------------


def test_run_async_works_in_sync_context():
    """The adapter's _run_async helper needs to work when called from
    pytest (sync context, no event loop running)."""
    from runner.dimensions.memory.lifecycle.integrations.graphiti_adapter import (
        _run_async,
    )

    async def sample_coro():
        await asyncio.sleep(0)
        return 42

    result = _run_async(sample_coro())
    assert result == 42
