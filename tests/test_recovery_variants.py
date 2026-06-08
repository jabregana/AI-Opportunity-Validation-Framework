"""Tests for the recovery dimension's pilot variants + runner.

Covers:
  - Factory registration for retry-with-backoff and fallback-chain
  - RetryWithBackoffVariant behavior across all four failure kinds
  - FallbackChainVariant behavior + fallback-strategy mapping
  - The simulation-based runner + UC-REC-1..4 gates
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_failure_injection import (
    generate_failure_injection_workload,
)
from runner.dimensions.recovery import (
    FACTORIES,
    Failure,
    RecoveryAction,
    build,
)
from runner.dimensions.recovery.fallback import (
    FALLBACK_STRATEGY_BY_KIND,
    FallbackChainVariant,
)
from runner.dimensions.recovery.retry import (
    DEFAULT_RETRY_ON_KINDS,
    RetryWithBackoffVariant,
)
from runner.recovery_runner import (
    P_RESOLVE_BY_ACTION_AND_KIND,
    compute_uc_rec_gates,
    run_recovery,
)


# ---------------- Factory registration ----------------


def test_factories_include_pilot_variants():
    assert "b-abort-on-failure" in FACTORIES
    assert "recovery-v0.1.0-retry-with-backoff" in FACTORIES
    assert "recovery-v0.1.1-fallback-chain" in FACTORIES


def test_build_returns_correct_classes():
    assert isinstance(build("recovery-v0.1.0-retry-with-backoff"),
                      RetryWithBackoffVariant)
    assert isinstance(build("recovery-v0.1.1-fallback-chain"),
                      FallbackChainVariant)


# ---------------- RetryWithBackoffVariant ----------------


def test_retry_returns_retry_on_tool_error():
    v = build("recovery-v0.1.0-retry-with-backoff")
    action = v.recover(Failure(kind="tool_error"), context={"n_retries": 0})
    assert action.kind == "retry"


def test_retry_returns_retry_on_timeout():
    v = build("recovery-v0.1.0-retry-with-backoff")
    action = v.recover(Failure(kind="timeout"), context={"n_retries": 1})
    assert action.kind == "retry"


def test_retry_aborts_on_model_refusal():
    v = build("recovery-v0.1.0-retry-with-backoff")
    action = v.recover(Failure(kind="model_refusal"), context={"n_retries": 0})
    assert action.kind == "abort"
    assert action.payload["reason"] == "non_retryable_kind"


def test_retry_aborts_on_validation_failure():
    v = build("recovery-v0.1.0-retry-with-backoff")
    action = v.recover(Failure(kind="validation_failure"), context={"n_retries": 0})
    assert action.kind == "abort"
    assert action.payload["reason"] == "non_retryable_kind"


def test_retry_aborts_after_max_retries():
    v = RetryWithBackoffVariant(max_retries=3)
    action = v.recover(Failure(kind="tool_error"), context={"n_retries": 3})
    assert action.kind == "abort"
    assert action.payload["reason"] == "max_retries_exhausted"


def test_retry_backoff_grows_exponentially():
    v = RetryWithBackoffVariant(initial_backoff_seconds=1.0, backoff_factor=2.0)
    a0 = v.recover(Failure(kind="tool_error"), {"n_retries": 0})
    a1 = v.recover(Failure(kind="tool_error"), {"n_retries": 1})
    a2 = v.recover(Failure(kind="tool_error"), {"n_retries": 2})
    assert a0.payload["backoff_seconds"] == 1.0
    assert a1.payload["backoff_seconds"] == 2.0
    assert a2.payload["backoff_seconds"] == 4.0


def test_retry_default_retry_on_kinds():
    assert "tool_error" in DEFAULT_RETRY_ON_KINDS
    assert "timeout" in DEFAULT_RETRY_ON_KINDS
    assert "model_refusal" not in DEFAULT_RETRY_ON_KINDS
    assert "validation_failure" not in DEFAULT_RETRY_ON_KINDS


# ---------------- FallbackChainVariant ----------------


def test_fallback_retries_first_for_retryable_kind():
    v = build("recovery-v0.1.1-fallback-chain")
    action = v.recover(Failure(kind="tool_error"),
                       context={"n_retries": 0, "n_fallbacks": 0})
    assert action.kind == "retry"


def test_fallback_falls_back_after_retry_exhaustion_for_retryable_kind():
    v = FallbackChainVariant(max_retries=2)
    action = v.recover(Failure(kind="tool_error"),
                       context={"n_retries": 2, "n_fallbacks": 0})
    assert action.kind == "fallback"
    assert action.payload["strategy"] == "alternate_tool"


def test_fallback_immediately_falls_back_for_non_retryable_kind():
    v = build("recovery-v0.1.1-fallback-chain")
    action = v.recover(Failure(kind="model_refusal"),
                       context={"n_retries": 0, "n_fallbacks": 0})
    assert action.kind == "fallback"
    assert action.payload["strategy"] == "larger_model"


def test_fallback_validation_failure_uses_structured_output_guard():
    v = build("recovery-v0.1.1-fallback-chain")
    action = v.recover(Failure(kind="validation_failure"),
                       context={"n_retries": 0, "n_fallbacks": 0})
    assert action.payload["strategy"] == "structured_output_guard"


def test_fallback_aborts_after_max_fallbacks():
    v = FallbackChainVariant(max_retries=2, max_fallbacks=1)
    action = v.recover(Failure(kind="tool_error"),
                       context={"n_retries": 2, "n_fallbacks": 1})
    assert action.kind == "abort"
    assert action.payload["reason"] == "all_options_exhausted"


def test_fallback_strategy_mapping_complete():
    # Every canonical failure kind needs a fallback strategy
    for kind in ["tool_error", "model_refusal", "validation_failure", "timeout"]:
        assert kind in FALLBACK_STRATEGY_BY_KIND


# ---------------- Runner ----------------


def test_runner_b_abort_completes_only_no_failure_scenarios():
    w = generate_failure_injection_workload(
        n_scenarios=200, failure_rate=0.4, seed=1,
    )
    r = run_recovery(build("b-abort-on-failure"), w)
    expected_completions = w.n_scenarios - w.n_scenarios_with_failure
    assert r.n_completed == expected_completions
    assert r.n_aborted == w.n_scenarios_with_failure


def test_runner_retry_beats_baseline_completion_rate():
    w = generate_failure_injection_workload(
        n_scenarios=500, failure_rate=0.3, seed=42,
    )
    baseline = run_recovery(build("b-abort-on-failure"), w, seed=42)
    retry = run_recovery(build("recovery-v0.1.0-retry-with-backoff"), w,
                         seed=42)
    assert retry.completion_rate_pct > baseline.completion_rate_pct


def test_runner_fallback_beats_retry_completion_rate():
    w = generate_failure_injection_workload(
        n_scenarios=500, failure_rate=0.3, seed=42,
    )
    retry = run_recovery(build("recovery-v0.1.0-retry-with-backoff"), w,
                         seed=42)
    fallback = run_recovery(build("recovery-v0.1.1-fallback-chain"), w,
                            seed=42)
    assert fallback.completion_rate_pct >= retry.completion_rate_pct


def test_runner_tracks_action_kind_counts():
    w = generate_failure_injection_workload(
        n_scenarios=100, failure_rate=0.5, seed=7,
    )
    r = run_recovery(build("recovery-v0.1.1-fallback-chain"), w, seed=7)
    # Should see at least retry + abort (fallback may or may not appear)
    assert "abort" in r.action_kind_counts or "retry" in r.action_kind_counts


def test_runner_tracks_per_failure_kind_completion():
    w = generate_failure_injection_workload(
        n_scenarios=300, failure_rate=0.5, seed=7,
    )
    r = run_recovery(build("recovery-v0.1.0-retry-with-backoff"), w, seed=7)
    # Should have some completion data for each kind that occurred
    for kind, info in r.completion_by_failure_kind.items():
        assert "n_scenarios" in info
        assert "n_completed" in info
        assert info["n_completed"] <= info["n_scenarios"]


def test_runner_deterministic_with_same_seed():
    w = generate_failure_injection_workload(n_scenarios=100, seed=1)
    r1 = run_recovery(build("recovery-v0.1.0-retry-with-backoff"), w, seed=5)
    r2 = run_recovery(build("recovery-v0.1.0-retry-with-backoff"), w, seed=5)
    assert r1.n_completed == r2.n_completed
    assert r1.total_cost == r2.total_cost


# ---------------- UC-REC gates ----------------


def test_uc_gates_pass_when_variant_beats_baseline():
    w = generate_failure_injection_workload(n_scenarios=500, seed=42)
    baseline = run_recovery(build("b-abort-on-failure"), w, seed=42)
    variant = run_recovery(build("recovery-v0.1.0-retry-with-backoff"),
                           w, seed=42)
    gates = compute_uc_rec_gates(variant, baseline)
    # UC-REC-1 should pass on this workload
    assert gates["UC-REC-1"]["status"] == "PASS"


def test_uc_gates_have_all_four():
    w = generate_failure_injection_workload(n_scenarios=100, seed=1)
    baseline = run_recovery(build("b-abort-on-failure"), w, seed=1)
    variant = run_recovery(build("recovery-v0.1.1-fallback-chain"), w, seed=1)
    gates = compute_uc_rec_gates(variant, baseline)
    assert set(gates) == {"UC-REC-1", "UC-REC-2", "UC-REC-3", "UC-REC-4"}


def test_resolution_probability_table_covers_pilot_actions():
    # Each pilot variant must be able to look up resolution probability
    # for every failure kind it might face
    for action_kind in ["retry", "fallback", "abort"]:
        for failure_kind in ["tool_error", "model_refusal",
                             "validation_failure", "timeout"]:
            assert (action_kind, failure_kind) in P_RESOLVE_BY_ACTION_AND_KIND
