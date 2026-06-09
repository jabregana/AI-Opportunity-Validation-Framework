"""Unit tests for ComponentIsolationGC (v0.2.0) variant.

Tests cover:
  - Two disconnected components: stale one collected, recent one preserved
  - Pinned-node anchor: pinning any node in a component preserves all of it
  - Single connected graph: idle period must exceed threshold
  - Brand-new isolated subgraph: not collected (min_component_age guard)
  - Build via factory registry
"""
from __future__ import annotations
import pytest

from runner.dimensions.memory.lifecycle import build, FACTORIES, GraphState
from runner.dimensions.memory.lifecycle.component_isolation import (
    ComponentIsolationGC,
)


def _seed_state(
    nodes: dict[str, dict],
    edges: list[tuple[str, str]],
    last_access: dict[str, float] | None = None,
    pinned: set[str] | None = None,
) -> GraphState:
    """Build a GraphState from terse spec."""
    state = GraphState()
    state.nodes = dict(nodes)
    state.in_degree = {n: 0 for n in nodes}
    state.out_degree = {n: 0 for n in nodes}
    for src, dst in edges:
        state.edges[(src, dst)] = state.edges.get((src, dst), 0) + 1
        state.in_degree[dst] = state.in_degree.get(dst, 0) + 1
        state.out_degree[src] = state.out_degree.get(src, 0) + 1
    state.last_access = dict(last_access or {})
    state.pinned = set(pinned or set())
    return state


def test_factory_registration():
    """v0.2.0 must resolve via build()."""
    variant = build("gc-v0.2.0-component-isolation")
    assert isinstance(variant, ComponentIsolationGC)
    assert variant.name == "gc-v0.2.0-component-isolation"


def test_factory_registry_contains_v020():
    assert "gc-v0.2.0-component-isolation" in FACTORIES


def test_two_components_one_stale_one_active():
    """Component A queried recently; component B not queried in 60 days.
    v0.2.0 should collect all of B and none of A."""
    # Component A: entities e1, e2 connected; queried 1 hour ago
    # Component B: entities e3, e4 connected; queried 60 days ago
    now = 1000 * 86400.0  # current time = day 1000
    state = _seed_state(
        nodes={
            "e1": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e2": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e3": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e4": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("e1", "e2"), ("e3", "e4")],
        last_access={
            "e1": now - 3600,  # 1 hour ago
            "e2": now - 3600,
            "e3": now - 60 * 86400,  # 60 days ago
            "e4": now - 60 * 86400,
        },
    )
    variant = ComponentIsolationGC(
        min_component_idle_seconds=30 * 86400.0,
        min_component_age_seconds=7 * 86400.0,
    )
    candidates = variant.collect_candidates(state, current_time=now)
    assert set(candidates) == {"e3", "e4"}, f"Expected B collected, got {candidates}"


def test_pinned_node_anchors_whole_component():
    """If any node in a stale component is pinned, the entire component
    is preserved."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "e1": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e2": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e3": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("e1", "e2"), ("e2", "e3")],
        last_access={"e1": now - 60 * 86400, "e2": now - 60 * 86400, "e3": now - 60 * 86400},
        pinned={"e2"},  # pin the middle node
    )
    variant = ComponentIsolationGC()
    candidates = variant.collect_candidates(state, current_time=now)
    assert candidates == [], f"Pinned node should anchor; got {candidates}"


def test_recent_query_preserves_component():
    """Even one recent query to one node in the component preserves all."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "e1": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e2": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e3": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("e1", "e2"), ("e2", "e3")],
        last_access={
            "e1": now - 60 * 86400,
            "e2": now - 60 * 86400,
            "e3": now - 3600,  # ONE recent query on e3
        },
    )
    variant = ComponentIsolationGC()
    candidates = variant.collect_candidates(state, current_time=now)
    assert candidates == [], (
        "Single recent query should preserve whole component"
    )


def test_brand_new_component_not_collected():
    """A subgraph younger than min_component_age_seconds must not be
    collected even if it has no queries."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "e1": {"kind": "entity", "added_at": now - 3600},  # 1 hour old
            "e2": {"kind": "entity", "added_at": now - 3600},
        },
        edges=[("e1", "e2")],
        last_access={},  # no queries
    )
    variant = ComponentIsolationGC(
        min_component_idle_seconds=30 * 86400.0,
        min_component_age_seconds=7 * 86400.0,
    )
    candidates = variant.collect_candidates(state, current_time=now)
    assert candidates == [], (
        "Brand-new component should not be collected even with no queries"
    )


def test_singleton_node_with_no_edges_is_its_own_component():
    """An isolated node (no edges) is a component of size 1; gets
    collected if stale per the same rule."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "isolated": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "connected_a": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "connected_b": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("connected_a", "connected_b")],
        last_access={
            "isolated": now - 60 * 86400,
            "connected_a": now - 3600,
            "connected_b": now - 3600,
        },
    )
    variant = ComponentIsolationGC()
    candidates = variant.collect_candidates(state, current_time=now)
    assert candidates == ["isolated"], f"Expected isolated only, got {candidates}"


def test_should_collect_per_node_matches_collect_candidates():
    """The per-node should_collect API should be consistent with the
    component-level collect_candidates."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "e1": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e2": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e3": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "e4": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("e1", "e2"), ("e3", "e4")],
        last_access={
            "e1": now - 3600, "e2": now - 3600,  # A: recent
            "e3": now - 60 * 86400, "e4": now - 60 * 86400,  # B: stale
        },
    )
    variant = ComponentIsolationGC()
    candidates = set(variant.collect_candidates(state, current_time=now))
    for node in state.nodes:
        per_node = variant.should_collect(node, state, current_time=now)
        in_candidates = node in candidates
        assert per_node == in_candidates, (
            f"{node}: should_collect={per_node} but in candidates={in_candidates}"
        )


def test_collect_actually_removes_nodes_and_edges():
    """End-to-end: detect candidates + invoke collect() and verify state
    is mutated correctly."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "a": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "b": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("a", "b")],
        last_access={"a": now - 60 * 86400, "b": now - 60 * 86400},
    )
    variant = ComponentIsolationGC()
    for node_id in variant.collect_candidates(state, current_time=now):
        variant.collect(node_id, state, current_time=now)
    assert state.nodes == {}
    assert state.edges == {}


def test_directed_edge_treated_as_undirected_for_component_detection():
    """Edges are stored with src/dst; component detection should treat
    them as undirected so a path src->dst connects the two."""
    now = 1000 * 86400.0
    state = _seed_state(
        nodes={
            "a": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "b": {"kind": "entity", "added_at": now - 100 * 86400.0},
            "c": {"kind": "entity", "added_at": now - 100 * 86400.0},
        },
        edges=[("a", "b"), ("c", "b")],  # b is the hub; a and c only connect via b
        last_access={
            "a": now - 60 * 86400,
            "b": now - 3600,  # recent query on hub
            "c": now - 60 * 86400,
        },
    )
    variant = ComponentIsolationGC()
    candidates = variant.collect_candidates(state, current_time=now)
    # The hub's recent query should preserve a and c too, even though they
    # only connect via the hub
    assert candidates == [], (
        f"Hub's recent query should preserve all nodes; got {candidates}"
    )


def test_empty_state_returns_no_candidates():
    state = GraphState()
    variant = ComponentIsolationGC()
    assert variant.collect_candidates(state, current_time=0.0) == []
