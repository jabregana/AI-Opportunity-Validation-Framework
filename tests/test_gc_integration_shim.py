"""Tests for the GCIntegrationShim contract + MockGraphStoreShim
reference implementation."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.dimensions.memory.lifecycle import GraphState, build as build_variant
from runner.dimensions.memory.lifecycle.integrations import (
    GCIntegrationShim,
    IntegrationStats,
    MockGraphStoreShim,
)


# ---------------- Contract types ----------------


def test_mock_shim_is_a_gc_integration_shim():
    s = MockGraphStoreShim()
    assert isinstance(s, GCIntegrationShim)


def test_mock_shim_has_contract_version():
    s = MockGraphStoreShim()
    assert s.contract_version == 1


def test_mock_shim_has_name():
    s = MockGraphStoreShim()
    assert s.name == "mock-graph-store"


# ---------------- Basic write recording ----------------


def test_record_write_adds_node_to_state():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", {"label": "Apple"}, t=1.0)
    state = s.get_state()
    assert "e1" in state.nodes
    assert state.nodes["e1"]["kind"] == "entity"
    assert state.nodes["e1"]["added_at"] == 1.0


def test_record_write_increments_stats():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.record_write("f1", "fact", None, t=1.0)
    assert s.stats().n_writes == 2


# ---------------- Edge recording ----------------


def test_record_edge_updates_both_degrees():
    s = MockGraphStoreShim()
    s.record_write("f1", "fact", None, t=0.0)
    s.record_write("e1", "entity", None, t=0.0)
    s.record_edge("f1", "e1", t=1.0)
    state = s.get_state()
    assert state.in_degree["e1"] == 1
    assert state.out_degree["f1"] == 1
    assert state.edges[("f1", "e1")] == 1


def test_record_remove_edge_decrements_both_degrees():
    s = MockGraphStoreShim()
    s.record_write("f1", "fact", None, t=0.0)
    s.record_write("e1", "entity", None, t=0.0)
    s.record_edge("f1", "e1", t=1.0)
    s.record_remove_edge("f1", "e1", t=2.0)
    state = s.get_state()
    assert state.in_degree["e1"] == 0
    assert state.out_degree["f1"] == 0
    assert ("f1", "e1") not in state.edges


def test_record_remove_edge_idempotent_on_missing_edge():
    s = MockGraphStoreShim()
    # Removing an edge that does not exist should be a no-op
    s.record_remove_edge("f1", "e1", t=2.0)
    state = s.get_state()
    assert state.edges == {}


# ---------------- Query recording ----------------


def test_record_query_updates_last_access_and_count():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.record_query("e1", t=10.0)
    s.record_query("e1", t=20.0)
    state = s.get_state()
    assert state.last_access["e1"] == 20.0
    assert state.query_count["e1"] == 2


def test_record_query_on_missing_node_is_safe():
    s = MockGraphStoreShim()
    s.record_query("missing", t=5.0)
    # Should not crash and should still count toward stats
    assert s.stats().n_queries == 1


# ---------------- Pinning ----------------


def test_pin_adds_to_pinned_set():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.pin("e1")
    state = s.get_state()
    assert "e1" in state.pinned


def test_apply_sweep_refuses_pinned():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.pin("e1")
    removed = s.apply_sweep(["e1"])
    assert removed == 0
    state = s.get_state()
    assert "e1" in state.nodes


# ---------------- Sweep ----------------


def test_apply_sweep_removes_node_and_incident_edges():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.record_write("f1", "fact", None, t=0.0)
    s.record_write("f2", "fact", None, t=0.0)
    s.record_edge("f1", "e1", t=1.0)
    s.record_edge("f2", "e1", t=1.0)
    removed = s.apply_sweep(["e1"])
    assert removed == 1
    state = s.get_state()
    assert "e1" not in state.nodes
    assert ("f1", "e1") not in state.edges
    assert ("f2", "e1") not in state.edges
    # Out-degree of f1 / f2 should drop
    assert state.out_degree["f1"] == 0
    assert state.out_degree["f2"] == 0


def test_apply_sweep_idempotent_on_missing_node():
    s = MockGraphStoreShim()
    removed = s.apply_sweep(["missing"])
    assert removed == 0


def test_apply_sweep_increments_stats():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.apply_sweep(["e1"])
    stats = s.stats()
    assert stats.n_sweeps_invoked == 1
    assert stats.n_nodes_actually_removed == 1


# ---------------- End-to-end variant through shim ----------------


def test_v0_1_2_through_shim_collects_orphan_facts():
    """Plays a tiny workload through the shim and lets v0.1.2 sweep."""
    s = MockGraphStoreShim()
    # Two facts pointing at one entity
    s.record_write("e1", "entity", None, t=0.0)
    s.record_write("f1", "fact", None, t=0.0)
    s.record_write("f2", "fact", None, t=0.0)
    s.record_edge("f1", "e1", t=0.1)
    s.record_edge("f2", "e1", t=0.1)
    # Both facts age out
    s.record_remove_edge("f1", "e1", t=10 * 86400)
    s.record_remove_edge("f2", "e1", t=10 * 86400)

    # v0.1.2 should now identify f1 and f2 as collectible
    variant = build_variant("gc-v0.1.2-fact-only")
    state = s.get_state()
    candidates = variant.collect_candidates(state, current_time=11 * 86400)
    assert set(candidates) == {"f1", "f2"}

    # Apply sweep and verify the state
    removed = s.apply_sweep(candidates)
    assert removed == 2
    state = s.get_state()
    assert "f1" not in state.nodes
    assert "f2" not in state.nodes
    assert "e1" in state.nodes  # entity preserved
    assert state.in_degree["e1"] == 0


def test_v0_1_2_through_shim_preserves_pinned_facts():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.record_write("f1", "fact", None, t=0.0)
    s.record_edge("f1", "e1", t=0.1)
    s.record_remove_edge("f1", "e1", t=10 * 86400)
    s.pin("f1")

    variant = build_variant("gc-v0.1.2-fact-only")
    state = s.get_state()
    # candidate_collect should NOT include f1 because the variant
    # checks state.pinned in should_collect
    candidates = variant.collect_candidates(state, current_time=11 * 86400)
    assert "f1" not in candidates


# ---------------- Stats accounting ----------------


def test_stats_track_full_workload_activity():
    s = MockGraphStoreShim()
    s.record_write("e1", "entity", None, t=0.0)
    s.record_write("f1", "fact", None, t=1.0)
    s.record_edge("f1", "e1", t=1.1)
    s.record_query("e1", t=2.0)
    s.record_remove_edge("f1", "e1", t=10.0)
    s.pin("e1")
    s.apply_sweep(["f1"])

    stats = s.stats()
    assert stats.n_writes == 2
    assert stats.n_edges_added == 1
    assert stats.n_edges_removed == 1
    assert stats.n_queries == 1
    assert stats.n_pins == 1
    assert stats.n_sweeps_invoked == 1
    assert stats.n_nodes_actually_removed == 1
