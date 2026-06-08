"""Tests for the w_graph_churn workload extensions.

Covers the new params: total_period_days, n_tenants,
dormant_entity_fraction, collected_fact_query_fraction.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_graph_churn import generate_churn_workload


# ---------------- total_period_days ----------------


def test_default_total_period_is_30_days():
    w = generate_churn_workload(n_entities=5, n_facts=50, seed=0)
    last_event_t = max(e.timestamp for e in w.events)
    # Default total_period_days=30, so events should fit within ~30 days
    assert last_event_t <= 30 * 86400 + 86400  # +1d for safety on remove_t


def test_total_period_days_doubles_event_span():
    w_short = generate_churn_workload(n_entities=5, n_facts=50,
                                      total_period_days=10.0, seed=0)
    w_long = generate_churn_workload(n_entities=5, n_facts=50,
                                     total_period_days=60.0, seed=0)
    short_max = max(e.timestamp for e in w_short.events)
    long_max = max(e.timestamp for e in w_long.events)
    assert long_max > short_max * 2


# ---------------- n_tenants ----------------


def test_default_n_tenants_is_1_no_tenant_ids():
    w = generate_churn_workload(n_entities=10, n_facts=20, seed=0)
    assert w.n_tenants == 1
    assert w.tenant_assignments == {}
    entity_adds = [e for e in w.events if e.op == "add_node" and e.node_kind == "entity"]
    assert all(e.tenant_id is None for e in entity_adds)


def test_n_tenants_assigns_entities_round_robin():
    w = generate_churn_workload(
        n_entities=12, n_facts=20, n_tenants=4, seed=0,
    )
    assert w.n_tenants == 4
    assert len(w.tenant_assignments) == 12
    # Round-robin: 12 entities / 4 tenants = 3 per tenant
    tenants = {}
    for tid in w.tenant_assignments.values():
        tenants[tid] = tenants.get(tid, 0) + 1
    assert len(tenants) == 4
    for count in tenants.values():
        assert count == 3


def test_n_tenants_attaches_tenant_id_to_entity_adds():
    w = generate_churn_workload(
        n_entities=6, n_facts=10, n_tenants=3, seed=0,
    )
    entity_adds = [e for e in w.events
                   if e.op == "add_node" and e.node_kind == "entity"]
    assert all(e.tenant_id is not None for e in entity_adds)
    assert all(e.tenant_id == w.tenant_assignments[e.node_id]
               for e in entity_adds)


# ---------------- dormant_entity_fraction ----------------


def test_default_dormant_fraction_is_zero():
    w = generate_churn_workload(n_entities=20, n_facts=50, seed=0)
    assert w.dormant_entity_ids == set()


def test_dormant_entities_receive_no_queries():
    w = generate_churn_workload(
        n_entities=20, n_facts=200, dormant_entity_fraction=0.3, seed=42,
    )
    assert len(w.dormant_entity_ids) > 0
    # Verify no query event targets a dormant entity
    query_targets = [e.node_id for e in w.events if e.op == "query"]
    for dormant in w.dormant_entity_ids:
        assert dormant not in query_targets, (
            f"Dormant entity {dormant} received a query but shouldn't have"
        )


def test_dormant_entities_excluded_from_pinned():
    """Dormant pool is sampled from non-pinned entities."""
    w = generate_churn_workload(
        n_entities=20, n_facts=100, dormant_entity_fraction=0.3,
        pin_fraction=0.2, seed=42,
    )
    assert w.dormant_entity_ids.isdisjoint(w.pinned_nodes)


# ---------------- collected_fact_query_fraction ----------------


def test_default_collected_fact_query_targets_empty():
    w = generate_churn_workload(n_entities=10, n_facts=50, seed=0)
    assert w.collected_fact_query_targets == []


def test_collected_fact_query_targets_emit_post_collection_queries():
    w = generate_churn_workload(
        n_entities=10, n_facts=50, collected_fact_query_fraction=0.2,
        seed=42,
    )
    assert len(w.collected_fact_query_targets) > 0
    # Verify each target has a query event AFTER the fact's remove_edge time
    remove_times = {}
    for ev in w.events:
        if ev.op == "remove_edge" and ev.edge_src in w.collected_fact_query_targets:
            remove_times[ev.edge_src] = max(
                remove_times.get(ev.edge_src, 0.0), ev.timestamp,
            )
    for fid in w.collected_fact_query_targets:
        query_events = [
            e for e in w.events
            if e.op == "query" and e.node_id == fid
        ]
        assert query_events, f"No query for collected-fact target {fid}"
        # Query should be 1-2 days after the latest remove_edge
        assert query_events[0].timestamp >= remove_times[fid] + 86400


# ---------------- Determinism preserved with extensions ----------------


def test_extensions_deterministic_with_same_seed():
    w1 = generate_churn_workload(
        n_entities=10, n_facts=50, n_tenants=3,
        dormant_entity_fraction=0.2,
        collected_fact_query_fraction=0.1, seed=42,
    )
    w2 = generate_churn_workload(
        n_entities=10, n_facts=50, n_tenants=3,
        dormant_entity_fraction=0.2,
        collected_fact_query_fraction=0.1, seed=42,
    )
    assert w1.tenant_assignments == w2.tenant_assignments
    assert w1.dormant_entity_ids == w2.dormant_entity_ids
    assert w1.collected_fact_query_targets == w2.collected_fact_query_targets
