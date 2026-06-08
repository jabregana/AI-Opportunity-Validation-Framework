"""Runner for tool variants against the task-completion workload.

Simulates an agent walking each task: the variant chooses which tools
to expose (based on the task's goal and the full tool universe), then
the simulator decides whether the agent completes the task given the
exposed set and how much it cost.

Simulation rules (Stage 2 simplification):

  - Completion requires every required_tool to be in exposed_tools.
    If any required tool is missing, the task fails immediately
    (the agent cannot do something for which it has no tool).
  - Given all required tools are exposed, the agent picks each one
    with probability SELECTION_BASE_ACCURACY, reduced by
    SELECTION_PENALTY_PER_EXTRA_TOOL for every exposed tool above
    the required count (cognitive overload model). Failure on any
    required-tool selection fails the task.
  - Cost = TASK_BASE_COST + len(exposed_tools) * TOKEN_PER_TOOL.
    This mirrors Anthropic's verified pricing where each added tool
    in the tools parameter consumes ~100 input tokens.
  - Latency in steps = 1 + len(exposed_tools) * LATENCY_PER_EXPOSED.
    Real latency depends on inference time which grows with input
    token count.

Stage 3 swaps the simulation rules for measured outcomes from a real
agent loop (LangGraph or Anthropic SDK).
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

from fixtures.workloads.w_tool_selection import ToolSelectionWorkload, ToolTask
from runner.dimensions.tools import ToolVariant


# Simulation constants (Stage 2). All abstract units; Stage 3 calibrates
# to real costs and accuracies.
SELECTION_BASE_ACCURACY = 0.95
SELECTION_PENALTY_PER_EXTRA_TOOL = 0.005
TOKEN_PER_TOOL = 100.0
TASK_BASE_COST = 500.0
LATENCY_PER_EXPOSED = 0.05


@dataclass
class ToolRunResult:
    """Outcome of running one variant on the task-completion workload."""

    variant: str
    n_tasks: int
    n_completed: int
    n_missing_required: int   # tasks where variant didn't expose a required tool
    n_selection_failed: int   # tasks where required tools all exposed but agent picked wrong
    completion_rate_pct: float
    total_cost: float
    cost_per_completion: float
    avg_exposed_per_task: float
    avg_required_per_task: float
    selection_precision_pct: float   # required-in-exposed / exposed (avg)
    selection_recall_pct: float      # required-in-exposed / required (avg)
    task_latencies: list[float] = field(default_factory=list)
    latency_p50: float = 0.0
    latency_p99: float = 0.0


def _run_one_task(
    task: ToolTask,
    variant: ToolVariant,
    workload: ToolSelectionWorkload,
    rng: random.Random,
) -> tuple[bool, str, float, float, int, int]:
    """Run one task through the variant. Returns:

      (completed, failure_reason, cost, latency_steps,
       n_required_in_exposed, n_exposed)
    """
    context = {
        "all_tools": list(workload.tool_universe),
        "goal": task.goal,
        "categories": workload.categories,
        "task_id": task.task_id,
        "required_tools": list(task.required_tools),
        "helper_tools": list(task.helper_tools),
    }
    exposed = list(variant.available_tools(context))
    n_exposed = len(exposed)

    cost = TASK_BASE_COST + n_exposed * TOKEN_PER_TOOL
    latency = 1.0 + n_exposed * LATENCY_PER_EXPOSED

    exposed_set = set(exposed)
    required_set = set(task.required_tools)
    n_required_in_exposed = len(required_set & exposed_set)

    # Check completion: every required tool must be in the exposed set
    if not required_set.issubset(exposed_set):
        return (False, "missing_required", cost, latency,
                n_required_in_exposed, n_exposed)

    # All required exposed; now simulate selection accuracy
    extra = max(0, n_exposed - len(required_set))
    per_tool_accuracy = max(
        0.0,
        SELECTION_BASE_ACCURACY
        - SELECTION_PENALTY_PER_EXTRA_TOOL * extra,
    )
    for _ in required_set:
        if rng.random() >= per_tool_accuracy:
            return (False, "selection_failed", cost, latency,
                    n_required_in_exposed, n_exposed)

    return (True, "completed", cost, latency,
            n_required_in_exposed, n_exposed)


def run_tools(
    variant: ToolVariant,
    workload: ToolSelectionWorkload,
    *,
    seed: int = 0,
) -> ToolRunResult:
    """Run the variant over every task and aggregate the metrics."""
    rng = random.Random(seed)
    n_completed = 0
    n_missing_required = 0
    n_selection_failed = 0
    total_cost = 0.0
    latencies: list[float] = []
    sum_exposed = 0
    sum_required = 0
    sum_required_in_exposed = 0
    sum_exposed_for_precision_denom = 0

    for task in workload.tasks:
        ok, reason, cost, latency, n_req_in_exp, n_exp = _run_one_task(
            task, variant, workload, rng,
        )
        total_cost += cost
        latencies.append(latency)
        sum_exposed += n_exp
        sum_required += len(task.required_tools)
        sum_required_in_exposed += n_req_in_exp
        sum_exposed_for_precision_denom += n_exp
        if ok:
            n_completed += 1
        elif reason == "missing_required":
            n_missing_required += 1
        elif reason == "selection_failed":
            n_selection_failed += 1

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    p50 = latencies_sorted[n // 2] if n else 0.0
    p99 = latencies_sorted[min(n - 1, max(0, int(0.99 * n)))] if n else 0.0

    avg_exposed = sum_exposed / max(1, workload.n_tasks)
    avg_required = sum_required / max(1, workload.n_tasks)
    completion_rate_pct = 100.0 * n_completed / max(1, workload.n_tasks)
    cost_per_completion = total_cost / max(1, n_completed)

    # Precision: across all tasks, what fraction of exposed tools were
    # required? Macro-averaged.
    if sum_exposed_for_precision_denom > 0:
        selection_precision = (
            100.0 * sum_required_in_exposed
            / sum_exposed_for_precision_denom
        )
    else:
        selection_precision = 0.0
    # Recall: what fraction of required tools were exposed?
    if sum_required > 0:
        selection_recall = 100.0 * sum_required_in_exposed / sum_required
    else:
        selection_recall = 0.0

    return ToolRunResult(
        variant=variant.name,
        n_tasks=workload.n_tasks,
        n_completed=n_completed,
        n_missing_required=n_missing_required,
        n_selection_failed=n_selection_failed,
        completion_rate_pct=completion_rate_pct,
        total_cost=total_cost,
        cost_per_completion=cost_per_completion,
        avg_exposed_per_task=avg_exposed,
        avg_required_per_task=avg_required,
        selection_precision_pct=selection_precision,
        selection_recall_pct=selection_recall,
        task_latencies=latencies,
        latency_p50=p50,
        latency_p99=p99,
    )


def compute_uc_tool_gates(
    variant_result: ToolRunResult,
    baseline_result: ToolRunResult,
    *,
    min_completion_lift_pp: float = -5.0,
    min_selection_precision_pct: float = 30.0,
    min_selection_recall_pct: float = 90.0,
    max_latency_multiplier: float = 1.5,
) -> dict[str, dict]:
    """Compute UC-TOOL-1..4 for a variant vs the b-allow-all baseline.

    UC-TOOL-1: completion-rate lift relative to baseline (note:
               narrowing the exposed set may LOSE some completions
               by missing required tools; the threshold is -5pp
               (can lose at most 5 percentage points) to encode the
               "narrow set ok if it does not break too many tasks"
               policy. A variant that beats baseline obviously wins.
    UC-TOOL-2: selection precision >= 30 percent (a narrow variant
               should be much more precise than allow-all, which is
               typically ~10 percent precision on a 35-tool universe
               with 2-4 required tools per task).
    UC-TOOL-3: selection recall >= 90 percent (don't miss too many
               required tools).
    UC-TOOL-4: latency p99 <= 1.5x baseline (narrowing should reduce
               or hold latency, not inflate it).
    """
    lift = variant_result.completion_rate_pct - baseline_result.completion_rate_pct
    uc1_pass = lift >= min_completion_lift_pp

    uc2_pass = variant_result.selection_precision_pct >= min_selection_precision_pct
    uc3_pass = variant_result.selection_recall_pct >= min_selection_recall_pct

    if baseline_result.latency_p99 > 0:
        lat_ratio = variant_result.latency_p99 / baseline_result.latency_p99
    else:
        lat_ratio = 1.0
    uc4_pass = lat_ratio <= max_latency_multiplier

    return {
        "UC-TOOL-1": {
            "name": "completion-rate lift",
            "value": round(lift, 3),
            "threshold": min_completion_lift_pp,
            "status": "PASS" if uc1_pass else "FAIL",
            "reason": f"variant lifted completion by {lift:+.2f}pp (need >= {min_completion_lift_pp:+.2f}pp)",
        },
        "UC-TOOL-2": {
            "name": "selection precision",
            "value": round(variant_result.selection_precision_pct, 3),
            "threshold": min_selection_precision_pct,
            "status": "PASS" if uc2_pass else "FAIL",
            "reason": f"precision {variant_result.selection_precision_pct:.2f}% (need >= {min_selection_precision_pct}%)",
        },
        "UC-TOOL-3": {
            "name": "selection recall",
            "value": round(variant_result.selection_recall_pct, 3),
            "threshold": min_selection_recall_pct,
            "status": "PASS" if uc3_pass else "FAIL",
            "reason": f"recall {variant_result.selection_recall_pct:.2f}% (need >= {min_selection_recall_pct}%)",
        },
        "UC-TOOL-4": {
            "name": "p99 latency vs baseline",
            "value": round(lat_ratio, 3),
            "threshold": max_latency_multiplier,
            "status": "PASS" if uc4_pass else "FAIL",
            "reason": f"p99 latency ratio {lat_ratio:.2f}x (need <= {max_latency_multiplier:.2f}x)",
        },
    }
