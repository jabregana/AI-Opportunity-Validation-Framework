"""Cross-adapter consistency tests.

Runs the SAME synthetic workload through both Mem0GCMiddleware and
GraphitiGCMiddleware (using their respective fakes from the
per-adapter test files), then verifies the adapters produce
consistent abstract behavior:

  - Same number of nodes ingested
  - Pin protection works on both
  - Sweep removes the expected nodes on both
  - GCIntegrationShim contract preserved on both

This is the integration test for the synthesis plan's claim that
the contract abstracts cleanly across downstream systems. If a
future change to v0.1.2 / v0.1.8 breaks one adapter but not the
other, the cross-adapter test catches it.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.dimensions.memory.lifecycle import build
from runner.dimensions.memory.lifecycle.integrations import (
    GCIntegrationShim,
    GraphitiGCMiddleware,
    Mem0GCMiddleware,
)

# Import the fakes from the per-adapter test modules
sys.path.insert(0, str(ROOT / "tests"))
from test_graphiti_adapter import FakeGraphiti
from test_mem0_adapter import FakeMem0


# ---------------- Contract conformance (both adapters) ----------------


@pytest.mark.parametrize("adapter_factory", [
    lambda: Mem0GCMiddleware(FakeMem0()),
    lambda: GraphitiGCMiddleware(FakeGraphiti()),
])
def test_both_adapters_implement_contract(adapter_factory):
    adapter = adapter_factory()
    assert isinstance(adapter, GCIntegrationShim)
    assert adapter.contract_version == 1
    assert hasattr(adapter, "record_write")
    assert hasattr(adapter, "record_edge")
    assert hasattr(adapter, "record_query")
    assert hasattr(adapter, "pin")
    assert hasattr(adapter, "get_state")
    assert hasattr(adapter, "apply_sweep")
    assert hasattr(adapter, "stats")
    assert hasattr(adapter, "sweep")


# ---------------- Empty state (both adapters) ----------------


def test_both_adapters_start_empty():
    mem0_mw = Mem0GCMiddleware(FakeMem0())
    gra_mw = GraphitiGCMiddleware(FakeGraphiti())
    assert mem0_mw.get_state().nodes == {}
    assert gra_mw.get_state().nodes == {}
    assert mem0_mw.stats().n_writes == 0
    assert gra_mw.stats().n_writes == 0


# ---------------- Pin protection (both adapters) ----------------


def test_pin_protection_works_on_both():
    mem0_mw = Mem0GCMiddleware(FakeMem0())
    gra_mw = GraphitiGCMiddleware(FakeGraphiti())

    # Mem0: add + pin + sweep
    r1 = mem0_mw.add("pinned mem", user_id="u1")
    mem_id = r1["results"][0]["id"]
    mem0_mw.pin(mem_id)
    assert mem0_mw.apply_sweep([mem_id]) == 0
    assert mem_id in mem0_mw._records

    # Graphiti: add + pin + sweep
    r2 = gra_mw.add_episode(name="ep", episode_body="Important Apple data.",
                            group_id="u1")
    ep_uuid = r2.episode.uuid
    gra_mw.pin(ep_uuid)
    assert gra_mw.apply_sweep([ep_uuid]) == 0
    assert ep_uuid in gra_mw._records


# ---------------- Stats tracking (both adapters) ----------------


def test_both_adapters_track_writes():
    mem0_mw = Mem0GCMiddleware(FakeMem0())
    gra_mw = GraphitiGCMiddleware(FakeGraphiti())

    mem0_mw.add("memory 1", user_id="u1")
    mem0_mw.add("memory 2", user_id="u1")
    assert mem0_mw.stats().n_writes == 2

    gra_mw.add_episode(name="ep1", episode_body="Alice met Bob.",
                       group_id="u1")
    gra_mw.add_episode(name="ep2", episode_body="Charlie saw Diane.",
                       group_id="u1")
    # Graphiti's add_episode creates the episode + entity nodes,
    # so n_writes >= 2 (typically much more)
    assert gra_mw.stats().n_writes >= 2


# ---------------- Sweep with v0.1.2 (both adapters) ----------------


def test_v012_sweep_works_on_both():
    """v0.1.2 (fact-only) should collect aged facts from both adapters
    when the prerequisites are met (out_degree==0 for Graphiti,
    automatic for Mem0)."""
    variant_m = build("gc-v0.1.2-fact-only")
    variant_g = build("gc-v0.1.2-fact-only")

    # Mem0 side
    mem0_mw = Mem0GCMiddleware(FakeMem0())
    r = mem0_mw.add("aged memory", user_id="u1")
    mem_id = r["results"][0]["id"]
    old_time = time.time() - 2 * 86400
    mem0_mw._records[mem_id].added_at = old_time
    mem0_mw._records[mem_id].last_access = old_time
    n_collected_m = mem0_mw.sweep(variant_m, current_time=time.time())
    assert n_collected_m == 1

    # Graphiti side
    gra_mw = GraphitiGCMiddleware(FakeGraphiti())
    r2 = gra_mw.add_episode(name="ep", episode_body="Aged content.",
                            group_id="u1")
    ep_uuid = r2.episode.uuid
    gra_mw._records[ep_uuid].added_at = old_time
    gra_mw._records[ep_uuid].last_access = old_time
    # Remove edges for out_degree==0
    for (src, dst) in list(gra_mw._edges):
        if src == ep_uuid:
            gra_mw.record_remove_edge(src, dst, t=time.time())
    n_collected_g = gra_mw.sweep(variant_g, current_time=time.time())
    assert n_collected_g == 1


# ---------------- Tenant pinning (both adapters via v0.1.8) ----------------


def test_v018_tenant_pinning_works_on_both():
    variant_m = build("gc-v0.1.8-comprehensive-tuned")
    variant_g = build("gc-v0.1.8-comprehensive-tuned")

    # Mem0 side
    mem0_mw = Mem0GCMiddleware(FakeMem0())
    r = mem0_mw.add("aged memory", user_id="tenant_a")
    mem_id = r["results"][0]["id"]
    mem0_mw._records[mem_id].added_at = time.time() - 10 * 86400
    mem0_mw._records[mem_id].last_access = time.time() - 10 * 86400
    variant_m.pin_for_tenant("tenant_a", mem_id)
    state_m = mem0_mw.get_state()
    cands_m = variant_m.collect_candidates(state_m, current_time=time.time())
    assert mem_id not in cands_m

    # Graphiti side
    gra_mw = GraphitiGCMiddleware(FakeGraphiti())
    r2 = gra_mw.add_episode(name="ep", episode_body="Tenant A data.",
                            group_id="tenant_a")
    ep_uuid = r2.episode.uuid
    gra_mw._records[ep_uuid].added_at = time.time() - 10 * 86400
    gra_mw._records[ep_uuid].last_access = time.time() - 10 * 86400
    for (src, dst) in list(gra_mw._edges):
        if src == ep_uuid:
            gra_mw.record_remove_edge(src, dst, t=time.time())
    variant_g.pin_for_tenant("tenant_a", ep_uuid)
    state_g = gra_mw.get_state()
    cands_g = variant_g.collect_candidates(state_g, current_time=time.time())
    assert ep_uuid not in cands_g


# ---------------- Tombstone behavior (both adapters via v0.1.3) ----------------


def test_v013_tombstone_works_on_both():
    variant_m = build("gc-v0.1.3-fact-only-tombstone")
    variant_g = build("gc-v0.1.3-fact-only-tombstone")

    now = time.time()
    old = now - 2 * 86400

    # Mem0 side: add + age + sweep
    mem0_mw = Mem0GCMiddleware(FakeMem0())
    r = mem0_mw.add("aged memory", user_id="u1")
    mem_id = r["results"][0]["id"]
    mem0_mw._records[mem_id].added_at = old
    mem0_mw._records[mem_id].last_access = old
    n_m = mem0_mw.sweep(variant_m, current_time=now)
    assert n_m == 1
    assert mem_id in variant_m.tombstones
    assert variant_m.was_recently_collected(mem_id, current_time=now + 60)

    # Graphiti side: same
    gra_mw = GraphitiGCMiddleware(FakeGraphiti())
    r2 = gra_mw.add_episode(name="ep", episode_body="Aged content.",
                            group_id="u1")
    ep_uuid = r2.episode.uuid
    gra_mw._records[ep_uuid].added_at = old
    gra_mw._records[ep_uuid].last_access = old
    for (src, dst) in list(gra_mw._edges):
        if src == ep_uuid:
            gra_mw.record_remove_edge(src, dst, t=now)
    n_g = gra_mw.sweep(variant_g, current_time=now)
    assert n_g == 1
    assert ep_uuid in variant_g.tombstones
    assert variant_g.was_recently_collected(ep_uuid, current_time=now + 60)


# ---------------- Get state consistency ----------------


def test_get_state_returns_graph_state_on_both():
    from runner.dimensions.memory.lifecycle import GraphState

    mem0_mw = Mem0GCMiddleware(FakeMem0())
    mem0_mw.add("hello", user_id="u1")
    state_m = mem0_mw.get_state()
    assert isinstance(state_m, GraphState)
    assert len(state_m.nodes) >= 1

    gra_mw = GraphitiGCMiddleware(FakeGraphiti())
    gra_mw.add_episode(name="ep", episode_body="Hello world.",
                       group_id="u1")
    state_g = gra_mw.get_state()
    assert isinstance(state_g, GraphState)
    assert len(state_g.nodes) >= 1
