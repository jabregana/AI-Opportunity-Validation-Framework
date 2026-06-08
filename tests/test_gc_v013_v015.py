"""Tests for the v0.1.3-v0.1.5 GC variant evolution.

Covers:
  - v0.1.3-fact-only-tombstone: tombstone recording, TTL, prune
  - v0.1.4-conservative-entity-plus-fact: entity collection rule
  - v0.1.5-fact-only-tenant-pinning: tenant-scoped pinning
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.dimensions.memory.lifecycle import (
    FACTORIES,
    GraphState,
    build,
)
from runner.dimensions.memory.lifecycle.conservative_entity import (
    ConservativeEntityPlusFactGC,
)
from runner.dimensions.memory.lifecycle.tenant_pin import (
    FactOnlyTenantPinningGC,
)
from runner.dimensions.memory.lifecycle.tombstone import FactOnlyTombstoneGC


# ---------------- Factory registration ----------------


def test_new_variants_registered():
    assert "gc-v0.1.3-fact-only-tombstone" in FACTORIES
    assert "gc-v0.1.4-conservative-entity-plus-fact" in FACTORIES
    assert "gc-v0.1.5-fact-only-tenant-pinning" in FACTORIES


def test_build_returns_correct_classes():
    assert isinstance(build("gc-v0.1.3-fact-only-tombstone"),
                      FactOnlyTombstoneGC)
    assert isinstance(build("gc-v0.1.4-conservative-entity-plus-fact"),
                      ConservativeEntityPlusFactGC)
    assert isinstance(build("gc-v0.1.5-fact-only-tenant-pinning"),
                      FactOnlyTenantPinningGC)


# ---------------- v0.1.3 tombstone ----------------


def test_tombstone_records_collected_fact():
    v = build("gc-v0.1.3-fact-only-tombstone")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 100.0
    v.collect("f1", state)
    assert "f1" in v.tombstones
    assert v.tombstones["f1"]["kind"] == "fact"


def test_tombstone_was_recently_collected_true_within_ttl():
    v = FactOnlyTombstoneGC(tombstone_ttl_seconds=7 * 86400)
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 100.0
    v.collect("f1", state)
    # 1 day later: still within TTL
    assert v.was_recently_collected("f1", current_time=100.0 + 86400)


def test_tombstone_was_recently_collected_false_after_ttl():
    v = FactOnlyTombstoneGC(tombstone_ttl_seconds=7 * 86400)
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 100.0
    v.collect("f1", state)
    # 10 days later: past TTL
    assert not v.was_recently_collected("f1", current_time=100.0 + 10 * 86400)


def test_tombstone_was_recently_collected_false_for_unknown_id():
    v = build("gc-v0.1.3-fact-only-tombstone")
    assert not v.was_recently_collected("nonexistent", current_time=1.0)


def test_tombstone_prune_expired():
    v = FactOnlyTombstoneGC(tombstone_ttl_seconds=86400)
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 0.0
    v.collect("f1", state)
    # 2 days later: prune should remove the tombstone
    pruned = v.prune_expired_tombstones(current_time=2 * 86400)
    assert pruned == 1
    assert "f1" not in v.tombstones
    assert v.tombstone_eviction_count == 1


def test_tombstone_inherits_fact_only_collection_rule():
    """v0.1.3 must still respect the FactOnlyGC collection rule."""
    v = build("gc-v0.1.3-fact-only-tombstone")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    # Entities never collected by v0.1.3 (inherits from FactOnlyGC)
    assert v.should_collect("e1", state, current_time=1e10) is False


# ---------------- v0.1.4 conservative entity ----------------


def test_conservative_entity_collects_orphan_unaccessed_old_entity():
    v = build("gc-v0.1.4-conservative-entity-plus-fact")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    # 100 days later: > 30d age + > 60d unaccessed
    assert v.should_collect("e1", state, current_time=100 * 86400) is True


def test_conservative_entity_keeps_recently_queried_entity():
    v = build("gc-v0.1.4-conservative-entity-plus-fact")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    # Query at day 30, current at day 50: only 20 days unaccessed
    state.last_access["e1"] = 30 * 86400
    assert v.should_collect("e1", state, current_time=50 * 86400) is False


def test_conservative_entity_keeps_too_new_entity():
    v = build("gc-v0.1.4-conservative-entity-plus-fact")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    # Only 20 days old: under 30d observation threshold
    assert v.should_collect("e1", state, current_time=20 * 86400) is False


def test_conservative_entity_keeps_entity_with_edges():
    v = build("gc-v0.1.4-conservative-entity-plus-fact")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 1
    state.last_access["e1"] = 0.0
    # 100 days but has edges
    assert v.should_collect("e1", state, current_time=100 * 86400) is False


def test_conservative_entity_never_collects_pinned():
    v = build("gc-v0.1.4-conservative-entity-plus-fact")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    state.pinned.add("e1")
    assert v.should_collect("e1", state, current_time=1e10) is False


def test_conservative_entity_still_collects_facts():
    """v0.1.4 must still collect facts per inherited FactOnlyGC rule."""
    v = build("gc-v0.1.4-conservative-entity-plus-fact")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    assert v.should_collect("f1", state, current_time=2 * 86400) is True


# ---------------- v0.1.5 tenant pinning ----------------


def test_tenant_pin_protects_node_from_collection():
    v = build("gc-v0.1.5-fact-only-tenant-pinning")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    v.pin_for_tenant("tenant_a", "f1")
    # Tenant A pinned this fact; should NOT collect
    assert v.should_collect("f1", state, current_time=10 * 86400) is False


def test_tenant_pin_global_pin_also_protected():
    v = build("gc-v0.1.5-fact-only-tenant-pinning")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.pinned.add("f1")
    assert v.should_collect("f1", state, current_time=10 * 86400) is False


def test_tenant_pin_unpin_removes_protection():
    v = build("gc-v0.1.5-fact-only-tenant-pinning")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    v.pin_for_tenant("tenant_a", "f1")
    v.unpin_for_tenant("tenant_a", "f1")
    # No longer pinned by anyone
    assert v.should_collect("f1", state, current_time=10 * 86400) is True


def test_tenant_pin_other_tenant_pin_also_protects():
    """If any tenant pins a node, it survives the global sweep."""
    v = build("gc-v0.1.5-fact-only-tenant-pinning")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    v.pin_for_tenant("tenant_b", "f1")
    # Tenant A is "active" but tenant B pinned the node
    v.set_active_tenant("tenant_a")
    assert v.should_collect("f1", state, current_time=10 * 86400) is False


def test_tenant_pin_is_pinned_for_any_tenant():
    v = build("gc-v0.1.5-fact-only-tenant-pinning")
    v.pin_for_tenant("tenant_a", "f1")
    v.pin_for_tenant("tenant_b", "f2")
    assert v.is_pinned_for_any_tenant("f1") is True
    assert v.is_pinned_for_any_tenant("f2") is True
    assert v.is_pinned_for_any_tenant("f3") is False
