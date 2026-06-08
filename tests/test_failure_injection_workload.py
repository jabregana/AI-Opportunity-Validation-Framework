"""Tests for the synthetic failure-injection workload (Day 2 of
Recovery Stage 2)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_failure_injection import (
    DEFAULT_FAILURE_DISTRIBUTION,
    FAILURE_KINDS,
    FailureInjectionWorkload,
    InjectedFailure,
    TaskScenario,
    TaskStep,
    generate_failure_injection_workload,
)


# ---------------- Determinism ----------------


def test_workload_deterministic_with_same_seed():
    w1 = generate_failure_injection_workload(n_scenarios=50, seed=42)
    w2 = generate_failure_injection_workload(n_scenarios=50, seed=42)
    assert w1.n_scenarios == w2.n_scenarios
    for s1, s2 in zip(w1.scenarios, w2.scenarios):
        assert s1.task_id == s2.task_id
        assert len(s1.steps) == len(s2.steps)
        assert len(s1.injected_failures) == len(s2.injected_failures)
        for f1, f2 in zip(s1.injected_failures, s2.injected_failures):
            assert (f1.step_idx, f1.kind) == (f2.step_idx, f2.kind)


def test_different_seeds_produce_different_workloads():
    w1 = generate_failure_injection_workload(n_scenarios=50, seed=1)
    w2 = generate_failure_injection_workload(n_scenarios=50, seed=2)
    # Should differ somewhere; very unlikely two seeds produce identical
    # failure placement
    differs = any(
        len(s1.injected_failures) != len(s2.injected_failures)
        or any((f1.step_idx, f1.kind) != (f2.step_idx, f2.kind)
               for f1, f2 in zip(s1.injected_failures, s2.injected_failures))
        for s1, s2 in zip(w1.scenarios, w2.scenarios)
    )
    assert differs


# ---------------- Scenario structure ----------------


def test_workload_has_requested_scenario_count():
    w = generate_failure_injection_workload(n_scenarios=37, seed=1)
    assert w.n_scenarios == 37
    assert len(w.scenarios) == 37


def test_every_scenario_starts_with_model_call_and_ends_with_model_call():
    w = generate_failure_injection_workload(n_scenarios=50, seed=1)
    for s in w.scenarios:
        assert s.steps[0].kind == "model_call"
        assert s.steps[0].label == "model:plan"
        assert s.steps[-1].kind == "model_call"
        assert s.steps[-1].label == "model:respond"


def test_step_count_in_range():
    w = generate_failure_injection_workload(
        n_scenarios=100, min_steps=4, max_steps=6, seed=1
    )
    for s in w.scenarios:
        assert 4 <= len(s.steps) <= 6


def test_step_indices_are_sequential():
    w = generate_failure_injection_workload(n_scenarios=50, seed=1)
    for s in w.scenarios:
        for i, step in enumerate(s.steps):
            assert step.idx == i


def test_task_ids_unique():
    w = generate_failure_injection_workload(n_scenarios=100, seed=1)
    ids = [s.task_id for s in w.scenarios]
    assert len(ids) == len(set(ids))


# ---------------- Failure injection ----------------


def test_failure_rate_approximate():
    w = generate_failure_injection_workload(
        n_scenarios=1000, failure_rate=0.30, seed=1
    )
    # Sample variance acceptable; check within 5pp of target
    actual = w.n_scenarios_with_failure / w.n_scenarios
    assert 0.25 <= actual <= 0.35


def test_failure_rate_zero_means_no_failures():
    w = generate_failure_injection_workload(
        n_scenarios=100, failure_rate=0.0, seed=1
    )
    assert w.n_scenarios_with_failure == 0
    for s in w.scenarios:
        assert s.injected_failures == []


def test_failure_kinds_only_from_canonical_list():
    w = generate_failure_injection_workload(
        n_scenarios=200, failure_rate=0.5, seed=1
    )
    for s in w.scenarios:
        for f in s.injected_failures:
            assert f.kind in FAILURE_KINDS


def test_failures_not_on_first_or_last_step():
    w = generate_failure_injection_workload(
        n_scenarios=200, failure_rate=0.5, seed=1
    )
    for s in w.scenarios:
        for f in s.injected_failures:
            assert f.step_idx != 0
            assert f.step_idx != len(s.steps) - 1


def test_failure_distribution_matches_weights_approximately():
    # tool_error has 0.55 weight; should dominate
    w = generate_failure_injection_workload(
        n_scenarios=2000, failure_rate=1.0, seed=1
    )
    total = sum(w.failure_distribution.values())
    assert total > 0
    tool_error_share = w.failure_distribution["tool_error"] / total
    # Allow wide tolerance; sample variance + 1 failure per scenario
    assert 0.45 <= tool_error_share <= 0.65


def test_failure_detail_carries_step_label():
    w = generate_failure_injection_workload(
        n_scenarios=100, failure_rate=1.0, seed=1
    )
    for s in w.scenarios:
        for f in s.injected_failures:
            assert "step_label" in f.detail
            assert f.detail["step_label"] == s.steps[f.step_idx].label


# ---------------- Custom failure distribution ----------------


def test_custom_failure_distribution():
    # All-refusals distribution
    only_refusal = {"model_refusal": 1.0}
    w = generate_failure_injection_workload(
        n_scenarios=200, failure_rate=1.0,
        failure_distribution=only_refusal, seed=1,
    )
    for s in w.scenarios:
        for f in s.injected_failures:
            assert f.kind == "model_refusal"


# ---------------- Aggregate accounting ----------------


def test_failure_distribution_sums_to_n_failures():
    w = generate_failure_injection_workload(
        n_scenarios=500, failure_rate=0.4, seed=1
    )
    total_by_kind = sum(w.failure_distribution.values())
    total_by_scenario = sum(
        len(s.injected_failures) for s in w.scenarios
    )
    assert total_by_kind == total_by_scenario
    assert total_by_kind == w.n_scenarios_with_failure


def test_default_failure_distribution_complete():
    # DEFAULT_FAILURE_DISTRIBUTION must cover every kind in FAILURE_KINDS
    assert set(DEFAULT_FAILURE_DISTRIBUTION.keys()) == set(FAILURE_KINDS)
