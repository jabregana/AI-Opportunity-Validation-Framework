"""Cross-dimension runner: walks each scenario through one prompt
variant + one tool variant + one recovery variant and measures the
joint outcome.

The simulator combines the three dimensions multiplicatively:

  P(complete) = P_prompt * P_tools_required * P_recovery_if_failure

where:
  P_prompt           = BASE_COMPLETION_BY_DIFFICULTY[difficulty]
                       + STRATEGY_CATEGORY_LIFT[prompt_variant][category]
  P_tools_required   = 1.0 if every required_tool is in exposed_tools
                       else (n_required_in_exposed / n_required)
                       (partial credit for partial tool availability)
  P_recovery_if_fail = 1.0 if no failure injected, otherwise the
                       P_RESOLVE_BY_ACTION_AND_KIND probability for
                       the action the recovery variant returns

The point of running cross-dimension is to surface whether dimension
lifts ADD linearly (in which case independent benchmarks suffice) or
INTERACT (in which case joint experiments matter).
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


@dataclass
class CrossDimRunResult:
    config_label: str  # e.g. "(cot, intent, fallback)"
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


def _p_complete(
    scenario: CrossDimScenario,
    prompt_v: PromptVariant,
    tool_v: ToolVariant,
    recovery_v: RecoveryVariant,
    tool_universe: list[str],
    categories_map: dict[str, list[str]],
) -> tuple[float, float, float, float, bool, bool]:
    """Returns (p_complete, p_prompt, p_tools, p_recovery,
                tools_blocked, recovery_blocked)."""
    # Prompt
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
    required = set(scenario.required_tools)
    if not required:
        p_tools = 1.0
    else:
        n_in = len(required & exposed)
        p_tools = n_in / len(required)
    tools_blocked = p_tools < 1.0

    # Recovery
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

    return (
        p_prompt * p_tools * p_recovery,
        p_prompt, p_tools, p_recovery,
        tools_blocked, recovery_blocked,
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

    for sc in workload.scenarios:
        p_c, p_p, p_t, p_r, tb, rb = _p_complete(
            sc, prompt_v, tool_v, recovery_v,
            tool_universe, categories_map,
        )
        sum_p_prompt += p_p
        sum_p_tools += p_t
        sum_p_recovery += p_r
        if tb:
            n_blocked_tools += 1
        if rb:
            n_blocked_recovery += 1
        if rng.random() < p_c:
            n_completed += 1

    n = workload.n_scenarios
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
    )
