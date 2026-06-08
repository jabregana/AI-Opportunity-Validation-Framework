"""Tests for the GC Stage 2 baseline.

Covers:
  - Workload generator (determinism, ordering, structure, pinning)
  - GCVariant ABC (collect mechanics, pinned protection)
  - The three pilot variants (b-raw-no-gc, ref-count, ref-count+utility)
  - The runner (latency recording, false-collection accounting)
  - The four UC gates
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_graph_churn import (
    ChurnWorkload,
    GraphEvent,
    generate_churn_workload,
)
from runner.gc_runner import _apply_event, compute_uc_gates, run_gc
from runner.gc_variants import GCVariant, GraphState, build, FACTORIES


# ---------------- Workload generator ----------------


def test_workload_deterministic_with_same_seed():
    w1 = generate_churn_workload(n_entities=10, n_facts=50, seed=42)
    w2 = generate_churn_workload(n_entities=10, n_facts=50, seed=42)
    assert len(w1.events) == len(w2.events)
    for e1, e2 in zip(w1.events, w2.events):
        assert (e1.op, e1.timestamp, e1.node_id) == (e2.op, e2.timestamp, e2.node_id)


def test_workload_events_chronologically_sorted():
    w = generate_churn_workload(n_entities=20, n_facts=100, seed=1)
    timestamps = [e.timestamp for e in w.events]
    assert timestamps == sorted(timestamps)


def test_workload_has_all_entity_adds():
    w = generate_churn_workload(n_entities=20, n_facts=100, seed=1)
    entity_adds = [
        e for e in w.events if e.op == "add_node" and e.node_kind == "entity"
    ]
    assert len(entity_adds) == 20


def test_workload_has_facts_and_edges():
    w = generate_churn_workload(n_entities=5, n_facts=10, seed=1)
    fact_adds = [e for e in w.events if e.op == "add_node" and e.node_kind == "fact"]
    edge_adds = [e for e in w.events if e.op == "add_edge"]
    assert len(fact_adds) == 10
    assert len(edge_adds) >= len(fact_adds)


def test_workload_pinned_subset_of_expected_survivors():
    w = generate_churn_workload(
        n_entities=20, n_facts=100, pin_fraction=0.10, seed=1
    )
    assert w.pinned_nodes <= w.expected_survivors


def test_workload_pin_events_present():
    w = generate_churn_workload(
        n_entities=20, n_facts=100, pin_fraction=0.10, seed=1
    )
    pin_events = [e for e in w.events if e.op == "pin"]
    assert len(pin_events) == len(w.pinned_nodes)


# ---------------- Variant registry ----------------


def test_factories_registered():
    assert "b-raw-no-gc" in FACTORIES
    assert "gc-v0.1.0-ref-count" in FACTORIES
    assert "gc-v0.1.1-ref-count-utility" in FACTORIES
    assert "gc-v0.1.2-fact-only" in FACTORIES


# ---------------- Workload expected-survivors (conservative philosophy) ----------------


def test_workload_expected_survivors_includes_all_entities():
    w = generate_churn_workload(n_entities=20, n_facts=100, seed=1)
    entity_ids = {f"e{i:04d}" for i in range(20)}
    assert w.expected_survivors == entity_ids


def test_workload_pinned_subset_of_entities():
    w = generate_churn_workload(
        n_entities=20, n_facts=100, pin_fraction=0.15, seed=1
    )
    entity_ids = {f"e{i:04d}" for i in range(20)}
    assert w.pinned_nodes <= entity_ids
    assert w.pinned_nodes <= w.expected_survivors


# ---------------- v0.1.2 fact-only ----------------


def test_fact_only_collects_fact_with_no_outgoing_edges():
    v = build("gc-v0.1.2-fact-only")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    assert v.should_collect("f1", state, current_time=2 * 86400) is True


def test_fact_only_keeps_fact_with_outgoing_edges():
    v = build("gc-v0.1.2-fact-only")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 2
    assert v.should_collect("f1", state, current_time=10 * 86400) is False


def test_fact_only_respects_min_age():
    v = build("gc-v0.1.2-fact-only")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    # Default min_age is 1 day; at 1 hour we should NOT collect
    assert v.should_collect("f1", state, current_time=3600) is False


def test_fact_only_never_collects_entity_nodes():
    v = build("gc-v0.1.2-fact-only")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.out_degree["e1"] = 0
    # Even an entity with no edges at all is preserved by v0.1.2
    assert v.should_collect("e1", state, current_time=1e10) is False


def test_fact_only_never_collects_pinned_fact():
    v = build("gc-v0.1.2-fact-only")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.pinned.add("f1")
    assert v.should_collect("f1", state, current_time=10 * 86400) is False


# ---------------- out_degree maintained by runner ----------------


def test_apply_event_maintains_out_degree_on_add_edge():
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.out_degree["e1"] = 0
    _apply_event(
        GraphEvent(op="add_edge", timestamp=1.0,
                   edge_src="f1", edge_dst="e1"),
        state,
    )
    assert state.out_degree["f1"] == 1
    assert state.in_degree["e1"] == 1


def test_apply_event_maintains_out_degree_on_remove_edge():
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.edges[("f1", "e1")] = 1
    state.in_degree["e1"] = 1
    state.out_degree["f1"] = 1
    _apply_event(
        GraphEvent(op="remove_edge", timestamp=2.0,
                   edge_src="f1", edge_dst="e1"),
        state,
    )
    assert state.out_degree["f1"] == 0
    assert state.in_degree["e1"] == 0


def test_collect_decrements_out_degree_of_other_endpoint():
    v = build("b-raw-no-gc")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.nodes["f2"] = {"kind": "fact", "added_at": 0.0}
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.edges[("f1", "e1")] = 1
    state.edges[("f2", "e1")] = 1
    state.in_degree["e1"] = 2
    state.out_degree["f1"] = 1
    state.out_degree["f2"] = 1
    # Collecting e1 should decrement out_degree of both f1 and f2
    v.collect("e1", state)
    assert state.out_degree["f1"] == 0
    assert state.out_degree["f2"] == 0


# ---------------- v0.1.2 end-to-end via runner ----------------


def test_runner_v0_1_2_reduces_store_significantly():
    w = generate_churn_workload(
        n_entities=10, n_facts=100, fact_lifetime_seconds=86400, seed=0
    )
    b_raw = run_gc(build("b-raw-no-gc"), w)
    fact_only = run_gc(build("gc-v0.1.2-fact-only"), w)
    # v0.1.2 should collect most facts whose edges have aged out
    assert fact_only.n_nodes_collected > 0
    assert fact_only.n_nodes_at_end < b_raw.n_nodes_at_end


def test_runner_v0_1_2_preserves_all_entities():
    w = generate_churn_workload(
        n_entities=10, n_facts=100, fact_lifetime_seconds=86400, seed=0
    )
    fact_only = run_gc(build("gc-v0.1.2-fact-only"), w)
    assert len(fact_only.surviving_entity_ids) == 10


def test_build_unknown_raises():
    with pytest.raises(KeyError):
        build("nonexistent")


# ---------------- b-raw-no-gc ----------------


def test_b_raw_never_collects():
    v = build("b-raw-no-gc")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    assert v.should_collect("e1", state, current_time=1e10) is False


# ---------------- Default collect behavior ----------------


def test_default_collect_removes_node_and_edges():
    v = build("b-raw-no-gc")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.nodes["f1"] = {"kind": "fact", "added_at": 1.0}
    state.edges[("f1", "e1")] = 1
    state.in_degree["e1"] = 1
    state.last_access["e1"] = 0.0
    state.last_access["f1"] = 1.0
    n = v.collect("f1", state)
    assert n == 1
    assert "f1" not in state.nodes
    assert ("f1", "e1") not in state.edges
    assert state.in_degree["e1"] == 0


def test_default_collect_refuses_pinned():
    v = build("gc-v0.1.0-ref-count")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.pinned.add("e1")
    assert v.collect("e1", state) == 0
    assert "e1" in state.nodes


# ---------------- v0.1.0 ref-count ----------------


def test_ref_count_collects_orphan_entity_past_age_threshold():
    v = build("gc-v0.1.0-ref-count")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    assert v.should_collect("e1", state, current_time=8 * 86400) is True


def test_ref_count_keeps_entity_with_incoming_edges():
    v = build("gc-v0.1.0-ref-count")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 2
    state.last_access["e1"] = 0.0
    assert v.should_collect("e1", state, current_time=30 * 86400) is False


def test_ref_count_keeps_young_orphan_entity():
    v = build("gc-v0.1.0-ref-count")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    assert v.should_collect("e1", state, current_time=86400) is False


def test_ref_count_never_collects_fact_nodes():
    v = build("gc-v0.1.0-ref-count")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.in_degree["f1"] = 0
    state.last_access["f1"] = 0.0
    assert v.should_collect("f1", state, current_time=1e10) is False


def test_ref_count_never_collects_pinned():
    v = build("gc-v0.1.0-ref-count")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    state.pinned.add("e1")
    assert v.should_collect("e1", state, current_time=1e10) is False


# ---------------- v0.1.1 ref-count + utility ----------------


def test_utility_inherits_ref_count_rule():
    v = build("gc-v0.1.1-ref-count-utility")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    assert v.should_collect("e1", state, current_time=8 * 86400) is True


def test_utility_collects_low_utility_entity_with_edges():
    v = build("gc-v0.1.1-ref-count-utility")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 1
    state.last_access["e1"] = 0.0
    state.query_count["e1"] = 0
    assert v.should_collect("e1", state, current_time=60 * 86400) is True


def test_utility_keeps_high_utility_entity():
    v = build("gc-v0.1.1-ref-count-utility")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 2
    state.last_access["e1"] = 25 * 86400
    state.query_count["e1"] = 5
    assert v.should_collect("e1", state, current_time=26 * 86400) is False


def test_utility_respects_observation_window():
    v = build("gc-v0.1.1-ref-count-utility")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 1
    state.last_access["e1"] = 0.0
    state.query_count["e1"] = 0
    assert v.should_collect("e1", state, current_time=5 * 86400) is False


# ---------------- Runner ----------------


def test_runner_b_raw_collects_nothing():
    w = generate_churn_workload(n_entities=5, n_facts=20, seed=0)
    result = run_gc(build("b-raw-no-gc"), w)
    assert result.n_nodes_collected == 0
    assert result.store_size_reduction_pct == 0.0
    assert result.false_collection_rate_pct == 0.0


def test_runner_ref_count_does_not_grow_store_beyond_baseline():
    w = generate_churn_workload(
        n_entities=10, n_facts=100, fact_lifetime_seconds=86400, seed=0
    )
    b_raw = run_gc(build("b-raw-no-gc"), w)
    gc = run_gc(build("gc-v0.1.0-ref-count"), w)
    assert gc.n_nodes_at_end <= b_raw.n_nodes_at_end


def test_runner_records_latencies():
    w = generate_churn_workload(n_entities=5, n_facts=20, seed=0)
    result = run_gc(build("gc-v0.1.0-ref-count"), w)
    assert len(result.write_latencies_ms) == len(w.events)
    assert result.write_p50_ms >= 0.0
    assert result.write_p99_ms >= result.write_p50_ms


def test_runner_pinned_nodes_survive_aggressive_gc():
    w = generate_churn_workload(
        n_entities=20,
        n_facts=300,
        fact_lifetime_seconds=86400,
        pin_fraction=0.20,
        seed=0,
    )
    v = build("gc-v0.1.1-ref-count-utility")
    state = GraphState()
    for ev in w.events:
        _apply_event(ev, state)
    last_t = w.events[-1].timestamp
    for cand in v.collect_candidates(state, last_t):
        v.collect(cand, state)
    for pid in w.pinned_nodes:
        assert pid in state.nodes, f"pinned node {pid} was collected"


# ---------------- UC gates ----------------


def test_uc_gates_pass_on_baseline():
    w = generate_churn_workload(n_entities=10, n_facts=50, seed=0)
    baseline = run_gc(build("b-raw-no-gc"), w)
    gates = compute_uc_gates(baseline, baseline)
    # Against itself, everything passes
    for uc, info in gates.items():
        assert info["status"] == "PASS", f"{uc} failed unexpectedly: {info}"


def test_uc_gates_structure():
    w = generate_churn_workload(n_entities=10, n_facts=50, seed=0)
    baseline = run_gc(build("b-raw-no-gc"), w)
    gc = run_gc(build("gc-v0.1.0-ref-count"), w)
    gates = compute_uc_gates(gc, baseline)
    assert set(gates) == {"UC-GC-1", "UC-GC-2", "UC-GC-3", "UC-GC-4"}
    for uc, info in gates.items():
        assert "status" in info
        assert info["status"] in ("PASS", "FAIL")
        assert "value" in info
        assert "threshold" in info
        assert "reason" in info
