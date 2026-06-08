"""Cross-dimension runner: walks each scenario through one prompt
variant + one tool variant + one recovery variant and measures the
joint outcome.

Adds cost tracking + per-scenario outcome list (for bootstrap CIs)
to the v1 runner.

Cost model (per scenario):
  prompt_cost   = len(rendered_prompt_chars) / 4 + BASE_OUTPUT_TOKENS
  tools_cost    = len(exposed_tools) * TOKEN_PER_TOOL
  recovery_cost = retry_overhead * n_retries + fallback_overhead * n_fallbacks
  total_cost    = prompt_cost + tools_cost + recovery_cost

Engineering-cost weights are NOT modeled here (those live in the
investment-prioritization tooling); this is the per-call inference cost.

The simulator combines the three dimensions multiplicatively:

  P(complete) = P_prompt * P_tools_required * P_recovery_if_failure

This module exposes per-scenario binary outcomes so the bootstrap
CI tooling can paired-resample.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

from fixtures.workloads.w_cross_dim_scenarios import (
    CrossDimScenario,
    CrossDimWorkload,
)
from runner.dimensions.prompt import PromptVariant
from runner.dimensions.recovery import (
    Failure,
    RecoveryAction,
    RecoveryVariant,
)
from runner.dimensions.tools import ToolVariant
from runner.prompt_runner import (
    BASE_COMPLETION_BY_DIFFICULTY,
    STRATEGY_CATEGORY_LIFT,
)
from runner.recovery_runner import P_RESOLVE_OPTIMISTIC


# Cost model constants (Stage 2 simplifications matching the
# individual-dimension runners). All in abstract token units.
TOKEN_PER_TOOL = 100.0       # matches Anthropic verified pricing
BASE_OUTPUT_TOKENS = 50.0
RETRY_OVERHEAD_TOKENS = 200.0       # per retry attempt
FALLBACK_OVERHEAD_TOKENS = 500.0    # per fallback attempt (larger model / alt tool)


def _approx_tokens(s: str) -> float:
    return max(1.0, len(s) / 4.0)


@dataclass
class CrossDimRunResult:
    config_label: str
    prompt_variant: str
    tool_variant: str
    recovery_variant: str
    n_scenarios: int
    n_completed: int
    completion_rate_pct: float
    # Per-dimension contributions
    n_scenarios_blocked_by_tools: int = 0
    n_scenarios_blocked_by_recovery: int = 0
    avg_p_prompt: float = 0.0
    avg_p_tools: float = 0.0
    avg_p_recovery: float = 0.0
    # Cost tracking
    total_cost: float = 0.0
    cost_per_completion: float = 0.0
    avg_prompt_tokens: float = 0.0
    avg_tool_tokens: float = 0.0
    avg_recovery_tokens: float = 0.0
    # Per-scenario binary outcomes (1 = completed, 0 = not). For
    # bootstrap CI computation.
    per_scenario_outcomes: list[int] = field(default_factory=list)


def _p_complete(
    scenario: CrossDimScenario,
    prompt_v: PromptVariant,
    tool_v: ToolVariant,
    recovery_v: RecoveryVariant,
    tool_universe: list[str],
    categories_map: dict[str, list[str]],
) -> tuple[float, float, float, float, bool, bool, float, float, float]:
    """Returns (p_complete, p_prompt, p_tools, p_recovery,
                tools_blocked, recovery_blocked,
                prompt_tokens, tool_tokens, recovery_tokens)."""
    # Prompt
    rendered = prompt_v.render({"raw": scenario.goal})
    prompt_tokens = _approx_tokens(rendered) + BASE_OUTPUT_TOKENS
    base = BASE_COMPLETION_BY_DIFFICULTY.get(scenario.difficulty, 0.5)
    lift = STRATEGY_CATEGORY_LIFT.get(prompt_v.name, {}).get(
        scenario.category, 0.0,
    )
    p_prompt = max(0.0, min(1.0, base + lift))

    # Tools
    ctx = {
        "all_tools": tool_universe,
        "goal": scenario.goal,
        "categories": categories_map,
        "task_id": scenario.scenario_id,
        "required_tools": list(scenario.required_tools),
    }
    exposed = set(tool_v.available_tools(ctx))
    tool_tokens = len(exposed) * TOKEN_PER_TOOL
    required = set(scenario.required_tools)
    if not required:
        p_tools = 1.0
    else:
        n_in = len(required & exposed)
        p_tools = n_in / len(required)
    tools_blocked = p_tools < 1.0

    # Recovery
    recovery_tokens = 0.0
    if scenario.injected_failure is None:
        p_recovery = 1.0
        recovery_blocked = False
    else:
        failure = Failure(
            kind=scenario.injected_failure.kind,
            detail=scenario.injected_failure.detail,
        )
        action = recovery_v.recover(
            failure,
            context={"scenario_id": scenario.scenario_id, "n_retries": 0,
                     "n_fallbacks": 0},
        )
        p_recovery = P_RESOLVE_OPTIMISTIC.get(
            (action.kind, scenario.injected_failure.kind), 0.0,
        )
        recovery_blocked = action.kind == "abort"
        # Cost model: one attempt of the chosen action
        if action.kind == "retry":
            recovery_tokens = RETRY_OVERHEAD_TOKENS
        elif action.kind == "fallback":
            recovery_tokens = FALLBACK_OVERHEAD_TOKENS

    return (
        p_prompt * p_tools * p_recovery,
        p_prompt, p_tools, p_recovery,
        tools_blocked, recovery_blocked,
        prompt_tokens, tool_tokens, recovery_tokens,
    )


def run_cross_dim(
    prompt_v: PromptVariant,
    tool_v: ToolVariant,
    recovery_v: RecoveryVariant,
    workload: CrossDimWorkload,
    tool_universe: list[str],
    categories_map: dict[str, list[str]],
    *,
    seed: int = 0,
) -> CrossDimRunResult:
    rng = random.Random(seed)
    n_completed = 0
    n_blocked_tools = 0
    n_blocked_recovery = 0
    sum_p_prompt = 0.0
    sum_p_tools = 0.0
    sum_p_recovery = 0.0
    sum_prompt_tokens = 0.0
    sum_tool_tokens = 0.0
    sum_recovery_tokens = 0.0
    outcomes: list[int] = []

    for sc in workload.scenarios:
        p_c, p_p, p_t, p_r, tb, rb, pt, tt, rt = _p_complete(
            sc, prompt_v, tool_v, recovery_v,
            tool_universe, categories_map,
        )
        sum_p_prompt += p_p
        sum_p_tools += p_t
        sum_p_recovery += p_r
        sum_prompt_tokens += pt
        sum_tool_tokens += tt
        sum_recovery_tokens += rt
        if tb:
            n_blocked_tools += 1
        if rb:
            n_blocked_recovery += 1
        if rng.random() < p_c:
            n_completed += 1
            outcomes.append(1)
        else:
            outcomes.append(0)

    n = workload.n_scenarios
    total_cost = sum_prompt_tokens + sum_tool_tokens + sum_recovery_tokens
    cost_per_completion = total_cost / max(1, n_completed)
    label = f"({prompt_v.name}, {tool_v.name}, {recovery_v.name})"

    return CrossDimRunResult(
        config_label=label,
        prompt_variant=prompt_v.name,
        tool_variant=tool_v.name,
        recovery_variant=recovery_v.name,
        n_scenarios=n,
        n_completed=n_completed,
        completion_rate_pct=100.0 * n_completed / max(1, n),
        n_scenarios_blocked_by_tools=n_blocked_tools,
        n_scenarios_blocked_by_recovery=n_blocked_recovery,
        avg_p_prompt=sum_p_prompt / max(1, n),
        avg_p_tools=sum_p_tools / max(1, n),
        avg_p_recovery=sum_p_recovery / max(1, n),
        total_cost=total_cost,
        cost_per_completion=cost_per_completion,
        avg_prompt_tokens=sum_prompt_tokens / max(1, n),
        avg_tool_tokens=sum_tool_tokens / max(1, n),
        avg_recovery_tokens=sum_recovery_tokens / max(1, n),
        per_scenario_outcomes=outcomes,
    )


def bootstrap_ci_for_completion(
    outcomes: list[int],
    *,
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Bootstrap CI for the completion rate (percent).

    Returns (point_estimate_pct, lower_ci_pct, upper_ci_pct).
    """
    rng = random.Random(seed)
    n = len(outcomes)
    if n == 0:
        return 0.0, 0.0, 0.0
    point = 100.0 * sum(outcomes) / n
    resamples: list[float] = []
    for _ in range(n_resamples):
        # Sample with replacement
        sample_sum = 0
        for _ in range(n):
            sample_sum += outcomes[rng.randint(0, n - 1)]
        resamples.append(100.0 * sample_sum / n)
    resamples.sort()
    alpha = (1.0 - confidence) / 2.0
    lo_idx = int(alpha * n_resamples)
    hi_idx = int((1.0 - alpha) * n_resamples) - 1
    return point, resamples[lo_idx], resamples[max(lo_idx, hi_idx)]
