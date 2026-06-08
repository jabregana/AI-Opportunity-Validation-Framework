"""Runner for prompt variants against the synthetic prompt-task workload.

The simulator translates (strategy_name, task.category, task.difficulty)
into completion probability via a hard-coded table. Cost is the
rendered-prompt token length plus a base output budget.

Stage 2 hard-codes the strategy effects; Stage 3 calibrates against
real LLM outputs from the multi-model ladder.

UC gates:
  UC-PROMPT-1: completion lift vs default >= +5pp
  UC-PROMPT-2: cost per correct completion <= 1.5x baseline
  UC-PROMPT-3: p99 task latency (in tokens) <= 2.5x baseline
  UC-PROMPT-4: variance of completion across categories <= baseline + 0.10
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from statistics import variance

from fixtures.workloads.w_prompt_tasks import PromptTask, PromptTaskWorkload
from runner.dimensions.prompt import PromptVariant


# Per-strategy lift on each task category (delta vs default baseline).
# Stage 2 hard-coded; Stage 3 calibrates from real LLM outputs.
STRATEGY_CATEGORY_LIFT: dict[str, dict[str, float]] = {
    "b-default-prompt": {
        "reasoning": 0.0, "extraction": 0.0, "classification": 0.0,
        "retrieval": 0.0, "code": 0.0,
    },
    "prompt-v0.1.0-cot": {
        "reasoning": +0.18, "extraction": +0.03, "classification": +0.04,
        "retrieval": +0.02, "code": +0.10,
    },
    "prompt-v0.1.1-direct-structured": {
        "reasoning": -0.02, "extraction": +0.10, "classification": +0.08,
        "retrieval": +0.05, "code": +0.02,
    },
    "prompt-v0.1.2-few-shot-1": {
        "reasoning": +0.06, "extraction": +0.10, "classification": +0.12,
        "retrieval": +0.04, "code": +0.05,
    },
    "prompt-v0.1.3-few-shot-3": {
        "reasoning": +0.10, "extraction": +0.16, "classification": +0.18,
        "retrieval": +0.06, "code": +0.08,
    },
    "prompt-v0.1.4-cot-plus-structured": {
        "reasoning": +0.16, "extraction": +0.13, "classification": +0.11,
        "retrieval": +0.05, "code": +0.11,
    },
}


# Default base completion probability by difficulty (1=easy, 5=hard).
BASE_COMPLETION_BY_DIFFICULTY: dict[int, float] = {
    1: 0.85,
    2: 0.72,
    3: 0.55,
    4: 0.40,
    5: 0.25,
}


# Cost per token (output tokens are typically more expensive than input
# but for Stage 2 we use one rate; Stage 3 splits input/output).
TOKEN_COST_RATE = 1.0
# Approximate token count = chars / 4 (rough English token estimation)
def _approx_tokens(s: str) -> float:
    return max(1.0, len(s) / 4.0)


# Base output budget per task in tokens
BASE_OUTPUT_TOKENS = 50.0


@dataclass
class PromptRunResult:
    variant: str
    n_tasks: int
    n_completed: int
    completion_rate_pct: float
    by_category_completion_pct: dict[str, float] = field(default_factory=dict)
    by_difficulty_completion_pct: dict[int, float] = field(default_factory=dict)
    total_cost: float = 0.0
    cost_per_completion: float = 0.0
    avg_prompt_tokens: float = 0.0
    task_latencies_tokens: list[float] = field(default_factory=list)
    latency_p50: float = 0.0
    latency_p99: float = 0.0
    category_completion_variance: float = 0.0


def _simulate_completion(
    task: PromptTask,
    variant_name: str,
    rng: random.Random,
) -> bool:
    base = BASE_COMPLETION_BY_DIFFICULTY.get(task.difficulty, 0.5)
    lift = STRATEGY_CATEGORY_LIFT.get(variant_name, {}).get(task.category, 0.0)
    p = max(0.0, min(1.0, base + lift))
    return rng.random() < p


def run_prompt(
    variant: PromptVariant,
    workload: PromptTaskWorkload,
    *,
    seed: int = 0,
) -> PromptRunResult:
    rng = random.Random(seed)
    n_completed = 0
    total_cost = 0.0
    prompt_tokens_total = 0.0
    latencies: list[float] = []
    by_cat_completed: dict[str, int] = {}
    by_cat_count: dict[str, int] = {}
    by_diff_completed: dict[int, int] = {}
    by_diff_count: dict[int, int] = {}

    for task in workload.tasks:
        rendered = variant.render({"raw": task.goal})
        prompt_tokens = _approx_tokens(rendered)
        prompt_tokens_total += prompt_tokens
        cost = (prompt_tokens + BASE_OUTPUT_TOKENS) * TOKEN_COST_RATE
        total_cost += cost
        # Latency: proxy = total tokens (input + output)
        latency = prompt_tokens + BASE_OUTPUT_TOKENS
        latencies.append(latency)

        completed = _simulate_completion(task, variant.name, rng)
        if completed:
            n_completed += 1
        by_cat_count[task.category] = by_cat_count.get(task.category, 0) + 1
        by_diff_count[task.difficulty] = by_diff_count.get(task.difficulty, 0) + 1
        if completed:
            by_cat_completed[task.category] = by_cat_completed.get(task.category, 0) + 1
            by_diff_completed[task.difficulty] = by_diff_completed.get(task.difficulty, 0) + 1

    completion_rate_pct = 100.0 * n_completed / max(1, workload.n_tasks)
    cost_per_completion = total_cost / max(1, n_completed)
    avg_prompt_tokens = prompt_tokens_total / max(1, workload.n_tasks)

    by_cat_pct = {
        cat: 100.0 * by_cat_completed.get(cat, 0) / max(1, by_cat_count.get(cat, 1))
        for cat in by_cat_count
    }
    by_diff_pct = {
        d: 100.0 * by_diff_completed.get(d, 0) / max(1, by_diff_count.get(d, 1))
        for d in by_diff_count
    }

    latencies_sorted = sorted(latencies)
    n = len(latencies_sorted)
    p50 = latencies_sorted[n // 2] if n else 0.0
    p99 = latencies_sorted[min(n - 1, max(0, int(0.99 * n)))] if n else 0.0

    cat_var = variance(list(by_cat_pct.values())) if len(by_cat_pct) > 1 else 0.0

    return PromptRunResult(
        variant=variant.name,
        n_tasks=workload.n_tasks,
        n_completed=n_completed,
        completion_rate_pct=completion_rate_pct,
        by_category_completion_pct=by_cat_pct,
        by_difficulty_completion_pct=by_diff_pct,
        total_cost=total_cost,
        cost_per_completion=cost_per_completion,
        avg_prompt_tokens=avg_prompt_tokens,
        task_latencies_tokens=latencies,
        latency_p50=p50,
        latency_p99=p99,
        category_completion_variance=cat_var,
    )


def compute_uc_prompt_gates(
    variant_result: PromptRunResult,
    baseline_result: PromptRunResult,
    *,
    min_completion_lift_pp: float = 5.0,
    max_cost_per_correct_multiplier: float = 1.5,
    max_latency_multiplier: float = 2.5,
    max_variance_increase: float = 100.0,  # in percentage-point variance units
) -> dict[str, dict]:
    lift = variant_result.completion_rate_pct - baseline_result.completion_rate_pct
    uc1_pass = lift >= min_completion_lift_pp

    if baseline_result.cost_per_completion > 0:
        cost_ratio = variant_result.cost_per_completion / baseline_result.cost_per_completion
    else:
        cost_ratio = 1.0
    uc2_pass = cost_ratio <= max_cost_per_correct_multiplier

    if baseline_result.latency_p99 > 0:
        lat_ratio = variant_result.latency_p99 / baseline_result.latency_p99
    else:
        lat_ratio = 1.0
    uc3_pass = lat_ratio <= max_latency_multiplier

    var_delta = (variant_result.category_completion_variance
                 - baseline_result.category_completion_variance)
    uc4_pass = var_delta <= max_variance_increase

    return {
        "UC-PROMPT-1": {
            "name": "completion lift vs default",
            "value": round(lift, 3),
            "threshold": min_completion_lift_pp,
            "status": "PASS" if uc1_pass else "FAIL",
            "reason": f"variant lifted completion by {lift:+.2f}pp (need >= {min_completion_lift_pp:+.2f}pp)",
        },
        "UC-PROMPT-2": {
            "name": "cost per correct completion vs baseline",
            "value": round(cost_ratio, 3),
            "threshold": max_cost_per_correct_multiplier,
            "status": "PASS" if uc2_pass else "FAIL",
            "reason": f"cost/correct ratio {cost_ratio:.2f}x (need <= {max_cost_per_correct_multiplier:.2f}x)",
        },
        "UC-PROMPT-3": {
            "name": "p99 latency (tokens) vs baseline",
            "value": round(lat_ratio, 3),
            "threshold": max_latency_multiplier,
            "status": "PASS" if uc3_pass else "FAIL",
            "reason": f"p99 latency ratio {lat_ratio:.2f}x (need <= {max_latency_multiplier:.2f}x)",
        },
        "UC-PROMPT-4": {
            "name": "category-completion variance delta",
            "value": round(var_delta, 3),
            "threshold": max_variance_increase,
            "status": "PASS" if uc4_pass else "FAIL",
            "reason": f"variance delta {var_delta:+.2f} (need <= +{max_variance_increase:.2f})",
        },
    }
