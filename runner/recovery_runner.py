"""Runner for recovery variants against the failure-injection workload.

Walks each scenario step-by-step, applies injected failures at the
planned indices, hands them to the variant's recover(), and simulates
whether the chosen RecoveryAction resolves the failure.

The outcome simulation is the load-bearing simplification of Stage 2:
hard-coded probabilities map (action.kind, failure.kind) to resolution
probability. Stage 3 swaps these for measured probabilities derived
from real LLM tool-use traces.

UC gates:
  UC-REC-1: completion rate (binary success per scenario)
            variant must beat baseline by min_completion_lift_pp
  UC-REC-2: cost per successful completion
            variant must stay within max_cost_per_success_multiplier
            of baseline
  UC-REC-3: p99 task latency in steps (accounts for retries)
            variant must stay within max_latency_multiplier of baseline
  UC-REC-4: max attempts seen across all scenarios
            variant must stay within configured cap (variant-level
            guard, not a per-comparison gate)
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

from fixtures.workloads.w_failure_injection import (
    FailureInjectionWorkload,
    InjectedFailure,
    TaskScenario,
)
from runner.dimensions.recovery import (
    Failure,
    RecoveryAction,
    RecoveryVariant,
)


# Simulation probabilities: P(recovery action resolves failure of kind).
# Stage 2 hard-codes these; Stage 3 should replace with measured values
# from real LLM tool-use traces.
P_RESOLVE_BY_ACTION_AND_KIND: dict[tuple[str, str], float] = {
    # retry: cheap, only helps with transient kinds
    ("retry", "tool_error"): 0.70,
    ("retry", "timeout"): 0.50,
    ("retry", "validation_failure"): 0.30,
    ("retry", "model_refusal"): 0.10,
    # fallback: more expensive, more effective on the right kind
    ("fallback", "tool_error"): 0.45,         # alternate tool
    ("fallback", "timeout"): 0.65,            # faster tool
    ("fallback", "validation_failure"): 0.85, # structured-output guard
    ("fallback", "model_refusal"): 0.60,      # larger model
    # ask_user: high probability but not implemented in pilot variants
    ("ask_user", "tool_error"): 0.50,
    ("ask_user", "timeout"): 0.50,
    ("ask_user", "validation_failure"): 0.50,
    ("ask_user", "model_refusal"): 0.50,
    # abort: by definition does not resolve
    ("abort", "tool_error"): 0.0,
    ("abort", "timeout"): 0.0,
    ("abort", "validation_failure"): 0.0,
    ("abort", "model_refusal"): 0.0,
}


# Cost units per action kind (Stage 2 simplification).
COST_PER_ACTION: dict[str, float] = {
    "retry": 1.0,        # one extra step at the same cost as a normal step
    "fallback": 2.5,     # extra step + possibly a larger model
    "ask_user": 5.0,     # human in the loop, expensive
    "abort": 0.0,
}


# Step count added per action kind (latency in steps).
STEPS_PER_ACTION: dict[str, float] = {
    "retry": 1.0,
    "fallback": 1.0,
    "ask_user": 1.0,
    "abort": 0.0,
}


@dataclass
class RecoveryRunResult:
    """Outcome of running one variant on the failure-injection workload."""

    variant: str
    n_scenarios: int
    n_completed: int
    n_aborted: int
    completion_rate_pct: float
    total_cost: float
    cost_per_completion: float
    task_steps: list[float] = field(default_factory=list)  # total steps per scenario including retries
    latency_p50_steps: float = 0.0
    latency_p99_steps: float = 0.0
    max_attempts_seen: int = 0
    # Counts of action kinds chosen across all scenarios
    action_kind_counts: dict[str, int] = field(default_factory=dict)
    # Per-failure-kind: how many scenarios with that kind completed
    completion_by_failure_kind: dict[str, dict] = field(default_factory=dict)


def _find_failure_at_step(
    scenario: TaskScenario,
    step_idx: int,
) -> InjectedFailure | None:
    for f in scenario.injected_failures:
        if f.step_idx == step_idx:
            return f
    return None


def _simulate_resolution(
    action: RecoveryAction,
    failure_kind: str,
    rng: random.Random,
) -> bool:
    """Did this recovery action resolve the failure?"""
    p = P_RESOLVE_BY_ACTION_AND_KIND.get(
        (action.kind, failure_kind), 0.0,
    )
    return rng.random() < p


def _run_scenario(
    scenario: TaskScenario,
    variant: RecoveryVariant,
    rng: random.Random,
    max_attempts_per_step: int,
) -> tuple[bool, float, float, int, dict[str, int]]:
    """Walk one scenario. Return (completed, total_cost, total_steps,
    max_attempts_this_scenario, action_kind_counts)."""
    total_cost = 0.0
    total_steps = 0.0
    max_attempts_this_scenario = 0
    action_counts: dict[str, int] = {}

    step_idx = 0
    n_steps = len(scenario.steps)

    while step_idx < n_steps:
        # Base cost + step for executing this step
        total_cost += 1.0
        total_steps += 1.0

        injected = _find_failure_at_step(scenario, step_idx)
        if injected is None:
            step_idx += 1
            continue

        # A failure was injected at this step. Loop on recovery actions
        # until the step is resolved, aborted, or the per-step cap fires.
        failure = Failure(kind=injected.kind, detail=injected.detail)
        n_retries = 0
        n_fallbacks = 0
        n_ask_user = 0
        resolved = False
        attempt = 0

        while attempt < max_attempts_per_step:
            attempt += 1
            context = {
                "scenario_id": scenario.task_id,
                "step_idx": step_idx,
                "n_retries": n_retries,
                "n_fallbacks": n_fallbacks,
                "n_ask_user": n_ask_user,
                "attempt": attempt,
            }
            action = variant.recover(failure, context)
            action_counts[action.kind] = action_counts.get(action.kind, 0) + 1

            # Apply cost / step accounting for the action itself
            total_cost += COST_PER_ACTION.get(action.kind, 0.0)
            total_steps += STEPS_PER_ACTION.get(action.kind, 0.0)

            if action.kind == "abort":
                return False, total_cost, total_steps, max(max_attempts_this_scenario, attempt), action_counts

            # Bump the variant's view of attempt counts
            if action.kind == "retry":
                n_retries += 1
            elif action.kind == "fallback":
                n_fallbacks += 1
            elif action.kind == "ask_user":
                n_ask_user += 1

            # Simulate whether the action resolved the failure
            if _simulate_resolution(action, failure.kind, rng):
                resolved = True
                break

        max_attempts_this_scenario = max(max_attempts_this_scenario, attempt)

        if not resolved:
            # Exceeded the per-step attempt cap without resolution
            return False, total_cost, total_steps, max_attempts_this_scenario, action_counts

        step_idx += 1

    return True, total_cost, total_steps, max_attempts_this_scenario, action_counts


def run_recovery(
    variant: RecoveryVariant,
    workload: FailureInjectionWorkload,
    *,
    seed: int = 0,
    max_attempts_per_step: int = 5,
) -> RecoveryRunResult:
    """Run the variant over every scenario and aggregate the metrics."""
    rng = random.Random(seed)
    n_completed = 0
    total_cost = 0.0
    latencies: list[float] = []
    max_attempts = 0
    aggregate_actions: dict[str, int] = {}

    # Per-failure-kind accounting: how many scenarios with each kind
    # completed
    by_kind: dict[str, dict] = {}

    for scenario in workload.scenarios:
        ok, cost, steps, attempts, actions = _run_scenario(
            scenario, variant, rng, max_attempts_per_step,
        )
        total_cost += cost
        latencies.append(steps)
        max_attempts = max(max_attempts, attempts)
        for k, v in actions.items():
            aggregate_actions[k] = aggregate_actions.get(k, 0) + v

        # Kind accounting (use the first injected failure's kind as the
        # scenario's kind for grouping; baseline scenarios = "none")
        kind = scenario.injected_failures[0].kind if scenario.injected_failures else "none"
        if kind not in by_kind:
            by_kind[kind] = {"n_scenarios": 0, "n_completed": 0}
        by_kind[kind]["n_scenarios"] += 1
        if ok:
            by_kind[kind]["n_completed"] += 1
            n_completed += 1

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    p50 = latencies_sorted[n // 2] if n else 0.0
    p99 = latencies_sorted[min(n - 1, max(0, int(0.99 * n)))] if n else 0.0

    n_aborted = workload.n_scenarios - n_completed
    completion_rate_pct = 100.0 * n_completed / max(1, workload.n_scenarios)
    cost_per_completion = total_cost / max(1, n_completed)

    return RecoveryRunResult(
        variant=variant.name,
        n_scenarios=workload.n_scenarios,
        n_completed=n_completed,
        n_aborted=n_aborted,
        completion_rate_pct=completion_rate_pct,
        total_cost=total_cost,
        cost_per_completion=cost_per_completion,
        task_steps=latencies,
        latency_p50_steps=p50,
        latency_p99_steps=p99,
        max_attempts_seen=max_attempts,
        action_kind_counts=aggregate_actions,
        completion_by_failure_kind=by_kind,
    )


def compute_uc_rec_gates(
    variant_result: RecoveryRunResult,
    baseline_result: RecoveryRunResult,
    *,
    min_completion_lift_pp: float = 5.0,
    max_cost_per_success_multiplier: float = 2.0,
    max_latency_multiplier: float = 3.0,
    max_attempts_cap: int = 5,
) -> dict[str, dict]:
    """Compute UC-REC-1..4 for a variant vs a baseline."""
    # UC-REC-1: completion-rate lift (in percentage points)
    lift = variant_result.completion_rate_pct - baseline_result.completion_rate_pct
    uc1_pass = lift >= min_completion_lift_pp

    # UC-REC-2: cost per success ratio
    if baseline_result.cost_per_completion > 0:
        ratio = variant_result.cost_per_completion / baseline_result.cost_per_completion
    else:
        # Baseline never completes; any variant that completes anything wins
        ratio = 0.0 if variant_result.n_completed > 0 else float("inf")
    uc2_pass = ratio <= max_cost_per_success_multiplier

    # UC-REC-3: latency ratio at p99
    if baseline_result.latency_p99_steps > 0:
        lat_ratio = variant_result.latency_p99_steps / baseline_result.latency_p99_steps
    else:
        lat_ratio = 1.0
    uc3_pass = lat_ratio <= max_latency_multiplier

    # UC-REC-4: max attempts under cap
    uc4_pass = variant_result.max_attempts_seen <= max_attempts_cap

    return {
        "UC-REC-1": {
            "name": "completion-rate lift",
            "value": round(lift, 3),
            "threshold": min_completion_lift_pp,
            "status": "PASS" if uc1_pass else "FAIL",
            "reason": f"variant lifted completion by {lift:+.2f}pp (need >= {min_completion_lift_pp:+.2f}pp)",
        },
        "UC-REC-2": {
            "name": "cost per success vs baseline",
            "value": round(ratio, 3),
            "threshold": max_cost_per_success_multiplier,
            "status": "PASS" if uc2_pass else "FAIL",
            "reason": f"cost/success ratio {ratio:.2f}x (need <= {max_cost_per_success_multiplier:.2f}x)",
        },
        "UC-REC-3": {
            "name": "p99 task latency vs baseline",
            "value": round(lat_ratio, 3),
            "threshold": max_latency_multiplier,
            "status": "PASS" if uc3_pass else "FAIL",
            "reason": f"p99 latency ratio {lat_ratio:.2f}x (need <= {max_latency_multiplier:.2f}x)",
        },
        "UC-REC-4": {
            "name": "max attempts per step",
            "value": variant_result.max_attempts_seen,
            "threshold": max_attempts_cap,
            "status": "PASS" if uc4_pass else "FAIL",
            "reason": f"max attempts {variant_result.max_attempts_seen} (need <= {max_attempts_cap})",
        },
    }
