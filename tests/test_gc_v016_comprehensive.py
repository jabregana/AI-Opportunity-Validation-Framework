"""Tests for v0.1.6 comprehensive GC (tombstone + conservative-entity + tenant-pin).

Verifies that v0.1.6 inherits the combined behavior of v0.1.3, v0.1.4,
and v0.1.5 simultaneously.
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
from runner.dimensions.memory.lifecycle.comprehensive import ComprehensiveGC


def test_v016_registered_in_factory():
    assert "gc-v0.1.6-comprehensive" in FACTORIES
    assert isinstance(build("gc-v0.1.6-comprehensive"), ComprehensiveGC)


# ---------------- Tombstone behavior (from v0.1.3) ----------------


def test_v016_collect_records_tombstone():
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 100.0
    v.collect("f1", state)
    assert "f1" in v.tombstones
    assert v.tombstones["f1"]["kind"] == "fact"


def test_v016_was_recently_collected():
    v = ComprehensiveGC(tombstone_ttl_seconds=7 * 86400)
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 100.0
    v.collect("f1", state)
    assert v.was_recently_collected("f1", current_time=100.0 + 86400)
    assert not v.was_recently_collected("f1", current_time=100.0 + 10 * 86400)


def test_v016_prune_tombstones():
    v = ComprehensiveGC(tombstone_ttl_seconds=86400)
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.last_access["f1"] = 0.0
    v.collect("f1", state)
    n = v.prune_expired_tombstones(current_time=2 * 86400)
    assert n == 1


# ---------------- Conservative entity (from v0.1.4) ----------------


def test_v016_collects_orphan_dormant_entity():
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 0.0
    # 100 days, dormant: should collect
    assert v.should_collect("e1", state, current_time=100 * 86400) is True


def test_v016_keeps_active_entity():
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 0
    state.last_access["e1"] = 50 * 86400  # queried at day 50
    # current at day 70: only 20 days since last access; below 60d threshold
    assert v.should_collect("e1", state, current_time=70 * 86400) is False


def test_v016_keeps_entity_with_edges():
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["e1"] = {"kind": "entity", "added_at": 0.0}
    state.in_degree["e1"] = 1
    state.last_access["e1"] = 0.0
    assert v.should_collect("e1", state, current_time=100 * 86400) is False


# ---------------- Tenant pinning (from v0.1.5) ----------------


def test_v016_tenant_pin_protects_node():
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    v.pin_for_tenant("tenant_a", "f1")
    assert v.should_collect("f1", state, current_time=10 * 86400) is False


def test_v016_tenant_pin_unpin_restores_collectibility():
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    v.pin_for_tenant("tenant_a", "f1")
    v.unpin_for_tenant("tenant_a", "f1")
    assert v.should_collect("f1", state, current_time=10 * 86400) is True


def test_v016_tenant_pin_does_not_record_tombstone():
    """When a tenant-pinned node is asked to be collected, no tombstone
    should be recorded since the collection itself is rejected."""
    v = build("gc-v0.1.6-comprehensive")
    state = GraphState()
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    v.pin_for_tenant("tenant_a", "f1")
    v.collect("f1", state)
    assert "f1" not in v.tombstones
    assert "f1" in state.nodes  # not removed


# ---------------- Combined behavior ----------------


def test_v016_combines_all_features_in_one_workflow():
    """Realistic workflow: pin some, collect others, query tombstones."""
    v = ComprehensiveGC()
    state = GraphState()
    # Two facts: f1 (pinned by tenant), f2 (collected)
    state.nodes["f1"] = {"kind": "fact", "added_at": 0.0}
    state.nodes["f2"] = {"kind": "fact", "added_at": 0.0}
    state.out_degree["f1"] = 0
    state.out_degree["f2"] = 0
    state.last_access["f1"] = 0.0
    state.last_access["f2"] = 1.0
    v.pin_for_tenant("tenant_a", "f1")

    # Try to collect both
    assert v.should_collect("f1", state, current_time=10 * 86400) is False  # pinned
    assert v.should_collect("f2", state, current_time=10 * 86400) is True   # not pinned

    n_removed = v.collect("f2", state)
    assert n_removed == 0  # no edges to remove
    assert "f2" not in state.nodes  # node removed
    # collected_at = state.last_access["f2"] = 1.0; query 1 day later
    # is within the default 7-day tombstone TTL
    assert v.was_recently_collected("f2", current_time=1.0 + 86400)
    # f1 still survives + no tombstone for it
    assert "f1" in state.nodes
    assert "f1" not in v.tombstones
