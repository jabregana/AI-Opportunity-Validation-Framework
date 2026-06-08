"""Runner for policy variants against the policy-task workload.

Simulates an agent walking each task one step at a time, asking the
variant for next_step() until the variant returns 'finish' or the
max-step cap fires. Completion probability is a hard-coded table by
(policy_variant, task_class, difficulty).

Cost = (n_steps) * STEP_COST. Latency = n_steps. Stage 3 calibrates
against real agent traces.

UC gates:
  UC-POLICY-1: completion lift vs single-shot >= +5pp
  UC-POLICY-2: cost per correct completion <= 2.0x baseline
  UC-POLICY-3: max steps per task <= 12 (variant-level guard)
  UC-POLICY-4: p99 task latency in steps <= 3.0x baseline
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

from fixtures.workloads.w_policy_tasks import PolicyTask, PolicyTaskWorkload
from runner.dimensions.policy import AgentStep, PolicyVariant


# Per-policy completion probability by task class. Stage 2 hard-coded.
POLICY_CLASS_COMPLETION: dict[str, dict[str, float]] = {
    "b-single-shot-policy": {
        "single_step": 0.80, "multi_step": 0.30,
        "needs_reflection": 0.20, "needs_replan": 0.10,
    },
    "policy-v0.1.0-react": {
        "single_step": 0.85, "multi_step": 0.70,
        "needs_reflection": 0.40, "needs_replan": 0.30,
    },
    "policy-v0.1.1-plan-execute": {
        "single_step": 0.80, "multi_step": 0.75,
        "needs_reflection": 0.35, "needs_replan": 0.55,
    },
    "policy-v0.1.2-reflect-loop": {
        "single_step": 0.80, "multi_step": 0.70,
        "needs_reflection": 0.75, "needs_replan": 0.50,
    },
    "policy-v0.1.3-handoff": {
        "single_step": 0.85, "multi_step": 0.55,
        "needs_reflection": 0.50, "needs_replan": 0.35,
    },
}

# Difficulty penalty (multiplier on completion probability).
DIFFICULTY_PENALTY: dict[int, float] = {
    1: 1.10, 2: 1.00, 3: 0.95, 4: 0.85, 5: 0.70,
}

# Cost units
STEP_COST = 1.0
MAX_STEPS_HARD_CAP = 12


@dataclass
class PolicyRunResult:
    variant: str
    n_tasks: int
    n_completed: int
    completion_rate_pct: float
    total_steps: int
    avg_steps_per_task: float
    max_steps_seen: int
    total_cost: float
    cost_per_completion: float
    task_latencies_steps: list[int] = field(default_factory=list)
    latency_p50: float = 0.0
    latency_p99: float = 0.0
    by_class_completion_pct: dict[str, float] = field(default_factory=dict)


def _walk_task(
    task: PolicyTask,
    variant: PolicyVariant,
    rng: random.Random,
) -> tuple[int, bool]:
    """Walk one task. Returns (n_steps, completed)."""
    history: list[AgentStep] = []
    context = {
        "task_id": task.task_id,
        "task_class": task.task_class,
        "difficulty": task.difficulty,
    }
    while len(history) < MAX_STEPS_HARD_CAP:
        step = variant.next_step(history, context)
        history.append(step)
        if step.kind == "finish":
            break

    n_steps = len(history)
    # Completion probability
    base = POLICY_CLASS_COMPLETION.get(variant.name, {}).get(
        task.task_class, 0.5,
    )
    penalty = DIFFICULTY_PENALTY.get(task.difficulty, 1.0)
    p = max(0.0, min(1.0, base * penalty))
    completed = rng.random() < p
    return n_steps, completed


def run_policy(
    variant: PolicyVariant,
    workload: PolicyTaskWorkload,
    *,
    seed: int = 0,
) -> PolicyRunResult:
    rng = random.Random(seed)
    n_completed = 0
    total_steps = 0
    max_steps = 0
    latencies: list[int] = []
    by_class_completed: dict[str, int] = {}
    by_class_count: dict[str, int] = {}

    for task in workload.tasks:
        n_steps, completed = _walk_task(task, variant, rng)
        total_steps += n_steps
        max_steps = max(max_steps, n_steps)
        latencies.append(n_steps)
        by_class_count[task.task_class] = by_class_count.get(task.task_class, 0) + 1
        if completed:
            n_completed += 1
            by_class_completed[task.task_class] = by_class_completed.get(
                task.task_class, 0) + 1

    avg_steps = total_steps / max(1, workload.n_tasks)
    completion_rate_pct = 100.0 * n_completed / max(1, workload.n_tasks)
    total_cost = total_steps * STEP_COST
    cost_per_completion = total_cost / max(1, n_completed)

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    p50 = latencies_sorted[n // 2] if n else 0.0
    p99 = latencies_sorted[min(n - 1, max(0, int(0.99 * n)))] if n else 0.0

    by_cls_pct = {
        c: 100.0 * by_class_completed.get(c, 0) / max(1, by_class_count.get(c, 1))
        for c in by_class_count
    }

    return PolicyRunResult(
        variant=variant.name,
        n_tasks=workload.n_tasks,
        n_completed=n_completed,
        completion_rate_pct=completion_rate_pct,
        total_steps=total_steps,
        avg_steps_per_task=avg_steps,
        max_steps_seen=max_steps,
        total_cost=total_cost,
        cost_per_completion=cost_per_completion,
        task_latencies_steps=latencies,
        latency_p50=p50,
        latency_p99=p99,
        by_class_completion_pct=by_cls_pct,
    )


def compute_uc_policy_gates(
    variant_result: PolicyRunResult,
    baseline_result: PolicyRunResult,
    *,
    min_completion_lift_pp: float = 5.0,
    max_cost_per_correct_multiplier: float = 2.0,
    max_steps_cap: int = 12,
    max_latency_multiplier: float = 3.0,
) -> dict[str, dict]:
    lift = variant_result.completion_rate_pct - baseline_result.completion_rate_pct
    uc1_pass = lift >= min_completion_lift_pp

    if baseline_result.cost_per_completion > 0:
        cost_ratio = variant_result.cost_per_completion / baseline_result.cost_per_completion
    else:
        cost_ratio = 1.0
    uc2_pass = cost_ratio <= max_cost_per_correct_multiplier

    uc3_pass = variant_result.max_steps_seen <= max_steps_cap

    if baseline_result.latency_p99 > 0:
        lat_ratio = variant_result.latency_p99 / baseline_result.latency_p99
    else:
        lat_ratio = 1.0
    uc4_pass = lat_ratio <= max_latency_multiplier

    return {
        "UC-POLICY-1": {
            "name": "completion lift vs baseline",
            "value": round(lift, 3),
            "threshold": min_completion_lift_pp,
            "status": "PASS" if uc1_pass else "FAIL",
            "reason": f"variant lifted completion by {lift:+.2f}pp (need >= {min_completion_lift_pp:+.2f}pp)",
        },
        "UC-POLICY-2": {
            "name": "cost per correct completion",
            "value": round(cost_ratio, 3),
            "threshold": max_cost_per_correct_multiplier,
            "status": "PASS" if uc2_pass else "FAIL",
            "reason": f"cost/correct ratio {cost_ratio:.2f}x (need <= {max_cost_per_correct_multiplier:.2f}x)",
        },
        "UC-POLICY-3": {
            "name": "max steps per task",
            "value": variant_result.max_steps_seen,
            "threshold": max_steps_cap,
            "status": "PASS" if uc3_pass else "FAIL",
            "reason": f"max steps {variant_result.max_steps_seen} (need <= {max_steps_cap})",
        },
        "UC-POLICY-4": {
            "name": "p99 task latency vs baseline",
            "value": round(lat_ratio, 3),
            "threshold": max_latency_multiplier,
            "status": "PASS" if uc4_pass else "FAIL",
            "reason": f"p99 latency ratio {lat_ratio:.2f}x (need <= {max_latency_multiplier:.2f}x)",
        },
    }
