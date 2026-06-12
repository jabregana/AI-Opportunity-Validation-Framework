"""Unit tests for v0.2.x variants 0.2.1 through 0.2.5 + profile loader.

Tests cover each layer's decision logic in isolation, then the v0.2.5
bundle composition, then the profile loader.

The v0.2.0 component-isolation tests live in test_component_isolation.py.
"""
from __future__ import annotations

from runner.dimensions.memory.lifecycle import (
    build, FACTORIES, GraphState,
    ActivationDecayGC, ComprehensiveGraphTunedGC, EvidenceCountGC,
    SupersessionTombstoneGC, TemporalValidityGC, V02xConfig,
)
from runner.dimensions.memory.lifecycle.profile_loader import (
    build_from_profile, from_yaml, list_profiles,
)


# ---------------- helpers ----------------


def _seed(nodes: dict, edges: list = None, last_access: dict = None,
          query_count: dict = None, pinned: set = None) -> GraphState:
    state = GraphState()
    state.nodes = dict(nodes)
    state.in_degree = {n: 0 for n in nodes}
    state.out_degree = {n: 0 for n in nodes}
    for src, dst in (edges or []):
        state.edges[(src, dst)] = state.edges.get((src, dst), 0) + 1
        state.in_degree[dst] = state.in_degree.get(dst, 0) + 1
        state.out_degree[src] = state.out_degree.get(src, 0) + 1
    state.last_access = dict(last_access or {})
    state.query_count = dict(query_count or {})
    state.pinned = set(pinned or set())
    return state


NOW = 1000 * 86400.0  # day 1000 in seconds


# ---------------- v0.2.1-temporal-validity ----------------


def test_temporal_validity_factory():
    v = build("gc-v0.2.1-temporal-validity")
    assert isinstance(v, TemporalValidityGC)


def test_temporal_validity_collects_expired_invalid_at():
    state = _seed({
        "f1": {"kind": "fact", "added_at": NOW - 100 * 86400, "invalid_at": NOW - 10 * 86400},
        "f2": {"kind": "fact", "added_at": NOW - 100 * 86400, "invalid_at": NOW - 1 * 86400},
        "f3": {"kind": "fact", "added_at": NOW - 100 * 86400, "invalid_at": None},
    })
    v = TemporalValidityGC(ttl_seconds=7 * 86400)
    assert v.should_collect("f1", state, NOW) is True   # invalid 10 days ago > 7
    assert v.should_collect("f2", state, NOW) is False  # invalid only 1 day ago < 7
    assert v.should_collect("f3", state, NOW) is False  # still valid


def test_temporal_validity_respects_pinning():
    state = _seed(
        nodes={"f1": {"kind": "fact", "added_at": NOW - 100 * 86400, "invalid_at": NOW - 10 * 86400}},
        pinned={"f1"},
    )
    v = TemporalValidityGC()
    assert v.should_collect("f1", state, NOW) is False


# ---------------- v0.2.2-activation-decay ----------------


def test_activation_decay_factory():
    v = build("gc-v0.2.2-activation-decay")
    assert isinstance(v, ActivationDecayGC)


def test_activation_decay_collects_cold_and_low_traffic():
    state = _seed(
        nodes={
            "cold_low": {"kind": "entity", "added_at": NOW - 365 * 86400},
            "cold_high": {"kind": "entity", "added_at": NOW - 365 * 86400},
            "warm_low": {"kind": "entity", "added_at": NOW - 365 * 86400},
            "warm_high": {"kind": "entity", "added_at": NOW - 365 * 86400},
        },
        last_access={
            "cold_low": NOW - 100 * 86400,   # cold
            "cold_high": NOW - 100 * 86400,  # cold
            "warm_low": NOW - 1 * 86400,     # warm
            "warm_high": NOW - 1 * 86400,    # warm
        },
        query_count={
            "cold_low": 1,   # low
            "cold_high": 10, # high
            "warm_low": 1,
            "warm_high": 10,
        },
    )
    v = ActivationDecayGC(window_seconds=60 * 86400, min_query_count=3)
    assert v.should_collect("cold_low", state, NOW) is True
    assert v.should_collect("cold_high", state, NOW) is False  # high traffic saves it
    assert v.should_collect("warm_low", state, NOW) is False   # warm saves it
    assert v.should_collect("warm_high", state, NOW) is False


def test_activation_decay_skips_invalid_at_nodes():
    """Nodes with invalid_at set are v0.2.1's domain; v0.2.2 leaves them alone."""
    state = _seed(
        nodes={"f1": {"kind": "fact", "added_at": NOW - 100 * 86400, "invalid_at": NOW - 100 * 86400}},
        last_access={},  # cold
        query_count={},  # low
    )
    v = ActivationDecayGC()
    assert v.should_collect("f1", state, NOW) is False


# ---------------- v0.2.3-evidence-count ----------------


def test_evidence_count_factory():
    v = build("gc-v0.2.3-evidence-count")
    assert isinstance(v, EvidenceCountGC)


def test_evidence_count_never_collects_entities():
    state = _seed({
        "e1": {"kind": "entity", "added_at": NOW - 365 * 86400},
    })
    v = EvidenceCountGC()
    assert v.should_collect("e1", state, NOW) is False


def test_evidence_count_collects_superseded_evidence():
    """Old fact supports e1. Newer fact also supports e1. Old fact gets collected."""
    state = _seed(
        nodes={
            "e1": {"kind": "entity", "added_at": NOW - 365 * 86400},
            "old_fact": {"kind": "fact", "added_at": NOW - 100 * 86400},
            "new_fact": {"kind": "fact", "added_at": NOW - 10 * 86400},
        },
        edges=[("old_fact", "e1"), ("new_fact", "e1")],
    )
    v = EvidenceCountGC(min_age_seconds=30 * 86400)
    assert v.should_collect("old_fact", state, NOW) is True
    assert v.should_collect("new_fact", state, NOW) is False  # too young


def test_evidence_count_preserves_sole_evidence():
    """If a fact is the ONLY evidence for an entity, don't collect it."""
    state = _seed(
        nodes={
            "e1": {"kind": "entity", "added_at": NOW - 365 * 86400},
            "lonely_fact": {"kind": "fact", "added_at": NOW - 100 * 86400},
        },
        edges=[("lonely_fact", "e1")],
    )
    v = EvidenceCountGC()
    assert v.should_collect("lonely_fact", state, NOW) is False


# ---------------- v0.2.4-supersession-tombstone ----------------


def test_supersession_tombstone_factory():
    v = build("gc-v0.2.4-supersession-tombstone")
    assert isinstance(v, SupersessionTombstoneGC)


def test_supersession_tombstone_collects_only_explicit_supersedes():
    state = _seed({
        "f1": {"kind": "fact", "added_at": NOW - 100 * 86400},
        "f2": {"kind": "fact", "added_at": NOW - 100 * 86400, "superseded_by": "f3"},
    })
    v = SupersessionTombstoneGC()
    assert v.should_collect("f1", state, NOW) is False  # no supersede
    assert v.should_collect("f2", state, NOW) is True


def test_supersession_tombstone_records_tombstone_on_collect():
    state = _seed({
        "f2": {"kind": "fact", "added_at": NOW - 100 * 86400, "superseded_by": "f3"},
    })
    v = SupersessionTombstoneGC()
    v.collect("f2", state, current_time=NOW)
    tomb = v.was_recently_collected("f2", NOW)
    assert tomb is not None
    assert tomb.node_id == "f2"
    assert tomb.superseded_by == "f3"


def test_supersession_tombstone_ttl_expires():
    state = _seed({
        "f2": {"kind": "fact", "added_at": NOW - 100 * 86400, "superseded_by": "f3"},
    })
    v = SupersessionTombstoneGC(tombstone_ttl_seconds=7 * 86400)
    v.collect("f2", state, current_time=NOW)
    # Still within TTL
    assert v.was_recently_collected("f2", NOW + 1 * 86400) is not None
    # Past TTL
    assert v.was_recently_collected("f2", NOW + 10 * 86400) is None


def test_supersession_tombstone_prune_expired():
    state = _seed({
        "f1": {"kind": "fact", "added_at": NOW - 100 * 86400, "superseded_by": "f3"},
        "f2": {"kind": "fact", "added_at": NOW - 100 * 86400, "superseded_by": "f4"},
    })
    v = SupersessionTombstoneGC(tombstone_ttl_seconds=7 * 86400)
    v.collect("f1", state, current_time=NOW)
    v.collect("f2", state, current_time=NOW + 5 * 86400)
    # Prune at NOW + 10 days: f1 expired (5+ days past TTL), f2 still in TTL
    pruned = v.prune_expired_tombstones(NOW + 10 * 86400)
    assert pruned == 1


# ---------------- v0.2.5-comprehensive-graph-tuned ----------------


def test_comprehensive_graph_tuned_factory():
    v = build("gc-v0.2.5-comprehensive-graph-tuned")
    assert isinstance(v, ComprehensiveGraphTunedGC)


def test_comprehensive_bundle_uses_default_config():
    v = ComprehensiveGraphTunedGC()
    assert v.config.component_isolation_enabled is True
    assert v.config.temporal_validity_enabled is True
    assert v.config.activation_decay_enabled is True
    assert v.config.evidence_count_enabled is True
    assert v.config.supersession_tombstone_enabled is True


def test_comprehensive_bundle_respects_disabled_layers():
    config = V02xConfig(
        component_isolation_enabled=False,
        temporal_validity_enabled=False,
        activation_decay_enabled=False,
        evidence_count_enabled=False,
        supersession_tombstone_enabled=False,
    )
    v = ComprehensiveGraphTunedGC(config=config)
    state = _seed({
        "any": {"kind": "fact", "added_at": NOW - 1000 * 86400, "invalid_at": NOW - 1000 * 86400},
    })
    # All layers disabled -> should never collect
    assert v.should_collect("any", state, NOW) is False


def test_comprehensive_bundle_tenant_pinning():
    v = ComprehensiveGraphTunedGC()
    v.pin_for_tenant("acme", "f1")
    assert v.is_pinned_for_any_tenant("f1") is True
    assert v.is_pinned_for_any_tenant("f2") is False
    v.unpin_for_tenant("acme", "f1")
    assert v.is_pinned_for_any_tenant("f1") is False


def test_comprehensive_bundle_collects_via_layer_consensus():
    """A node that satisfies temporal-validity should be collected even
    if other layers don't apply."""
    state = _seed(
        nodes={
            "isolated_old": {"kind": "fact", "added_at": NOW - 200 * 86400,
                             "invalid_at": NOW - 30 * 86400},  # invalid 30 days ago
        },
        last_access={"isolated_old": NOW - 200 * 86400},  # cold
        query_count={"isolated_old": 0},  # low
    )
    v = ComprehensiveGraphTunedGC()  # defaults
    assert v.should_collect("isolated_old", state, NOW) is True


def test_comprehensive_bundle_global_pin_prevents_collection():
    state = _seed(
        nodes={"f1": {"kind": "fact", "added_at": NOW - 200 * 86400,
                      "invalid_at": NOW - 30 * 86400}},
        pinned={"f1"},
    )
    v = ComprehensiveGraphTunedGC()
    assert v.should_collect("f1", state, NOW) is False


def test_comprehensive_bundle_tombstone_recovery():
    """v0.2.5 should delegate was_recently_collected to its v0.2.4 layer."""
    state = _seed({
        "f1": {"kind": "fact", "added_at": NOW - 100 * 86400, "superseded_by": "f2"},
    })
    v = ComprehensiveGraphTunedGC()
    v.collect("f1", state, current_time=NOW)
    tomb = v.was_recently_collected("f1", NOW)
    assert tomb is not None
    assert tomb.superseded_by == "f2"


# ---------------- profile loader ----------------


def test_list_profiles_finds_starter_profiles():
    profiles = list_profiles()
    # Five customer-facing starter profiles + one benchmark-only profile
    # (finance-aggressive-no-iso) that disables component_isolation for
    # F1-style benchmark workloads where the BEFORE pass touches every
    # node in the graph.
    assert {
        "general-default",
        "finance-aggressive",
        "clinical-conservative",
        "customer-conversations",
        "local-model-conservative",
    }.issubset(set(profiles))


def test_general_default_profile_loads():
    config = from_yaml(
        "runner/dimensions/memory/lifecycle/profiles/general-default.yaml"
    )
    assert config.component_isolation_enabled is True
    assert config.min_component_idle_seconds == 2592000  # 30 days


def test_finance_aggressive_has_tighter_thresholds():
    general = build_from_profile("general-default").config
    finance = build_from_profile("finance-aggressive").config
    assert finance.min_component_idle_seconds < general.min_component_idle_seconds
    assert finance.temporal_validity_ttl_seconds < general.temporal_validity_ttl_seconds
    assert finance.tombstone_ttl_seconds < general.tombstone_ttl_seconds


def test_clinical_conservative_has_looser_thresholds():
    general = build_from_profile("general-default").config
    clinical = build_from_profile("clinical-conservative").config
    assert clinical.min_component_idle_seconds > general.min_component_idle_seconds
    assert clinical.temporal_validity_ttl_seconds > general.temporal_validity_ttl_seconds
    assert clinical.tombstone_ttl_seconds > general.tombstone_ttl_seconds


def test_build_from_profile_returns_configured_bundle():
    bundle = build_from_profile("local-model-conservative")
    assert isinstance(bundle, ComprehensiveGraphTunedGC)
    # local-model profile has min_query_count=5 (vs general's 3)
    assert bundle.config.min_query_count == 5


def test_all_v02x_variants_in_factory():
    expected = {
        "gc-v0.2.0-component-isolation",
        "gc-v0.2.1-temporal-validity",
        "gc-v0.2.2-activation-decay",
        "gc-v0.2.3-evidence-count",
        "gc-v0.2.4-supersession-tombstone",
        "gc-v0.2.5-comprehensive-graph-tuned",
    }
    assert expected.issubset(FACTORIES.keys())
