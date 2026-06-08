"""Cross-dimension scenarios that exercise prompt + tools + recovery
dimensions in a single workload.

Each scenario carries:
  - A goal + category + difficulty (prompt dimension)
  - A list of required tools (tools dimension)
  - An optional injected failure (recovery dimension)

A cross-dimension runner walks each scenario through (one prompt
variant, one tool variant, one recovery variant) and measures the
joint outcome. The point: do dimension lifts add linearly, or do
they interact?

The framework's expectation is that the WEAKEST dimension constrains
the result: a great prompt variant cannot save a scenario whose
required tools are not exposed; a great recovery variant cannot save
a scenario where the prompt was never going to produce the right
output. The cross-dim experiment surfaces this.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field

from fixtures.workloads.w_failure_injection import (
    FAILURE_KINDS,
    InjectedFailure,
)
from fixtures.workloads.w_prompt_tasks import (
    GOAL_TEMPLATES,
    TASK_CATEGORIES,
    _fill_template,
)
from fixtures.workloads.w_tool_selection import (
    TOOL_CATEGORIES,
)


# Map task categories to plausible required-tool categories. This
# encodes which task categories use which tool categories in the
# simulator's world. A real workload would derive these from real
# task ground truth.
TASK_TO_TOOL_CATEGORY: dict[str, list[str]] = {
    "reasoning": ["computation", "data"],
    "extraction": ["data", "files"],
    "classification": ["data", "search"],
    "retrieval": ["search", "external_api"],
    "code": ["files", "system"],
}


@dataclass
class CrossDimScenario:
    """One scenario that exercises all three dimensions."""

    scenario_id: str
    # Prompt dimension
    goal: str
    category: str
    difficulty: int
    # Tools dimension
    required_tools: list[str]
    # Recovery dimension (None = no failure injected)
    injected_failure: InjectedFailure | None = None


@dataclass
class CrossDimWorkload:
    scenarios: list[CrossDimScenario]
    n_scenarios: int
    n_scenarios_with_failure: int
    failure_distribution: dict[str, int] = field(default_factory=dict)
    by_category: dict[str, int] = field(default_factory=dict)


def generate_cross_dim_workload(
    n_scenarios: int = 300,
    failure_rate: float = 0.30,
    required_per_scenario: tuple[int, int] = (1, 3),
    difficulty_distribution: tuple[float, ...] = (0.10, 0.25, 0.30, 0.25, 0.10),
    seed: int = 0,
) -> CrossDimWorkload:
    """Generate a deterministic cross-dimension workload."""
    rng = random.Random(seed)

    scenarios: list[CrossDimScenario] = []
    kind_counts: dict[str, int] = {k: 0 for k in FAILURE_KINDS}
    cat_counts: dict[str, int] = {c: 0 for c in TASK_CATEGORIES}
    n_with_failure = 0

    for i in range(n_scenarios):
        # Prompt dimension: pick category + difficulty + goal
        cat = rng.choice(list(TASK_CATEGORIES))
        diff = rng.choices(
            list(range(1, 6)),
            weights=list(difficulty_distribution),
            k=1,
        )[0]
        template = rng.choice(GOAL_TEMPLATES[cat])
        goal = _fill_template(template, rng)

        # Tools dimension: pick required tools from category-matched
        # tool categories
        relevant_tool_cats = TASK_TO_TOOL_CATEGORY.get(cat,
                                                      list(TOOL_CATEGORIES.keys()))
        pool = [t for tc in relevant_tool_cats for t in TOOL_CATEGORIES[tc]]
        n_req = rng.randint(required_per_scenario[0],
                            min(required_per_scenario[1], len(pool)))
        required = rng.sample(pool, n_req)

        # Recovery dimension: inject failure with probability
        injected: InjectedFailure | None = None
        if rng.random() < failure_rate:
            kind = rng.choices(
                list(FAILURE_KINDS),
                weights=[0.55, 0.20, 0.15, 0.10],
                k=1,
            )[0]
            injected = InjectedFailure(
                step_idx=0,  # cross-dim simplification: failure at first step
                kind=kind,
                detail={"category": cat},
            )
            kind_counts[kind] += 1
            n_with_failure += 1

        cat_counts[cat] += 1
        scenarios.append(CrossDimScenario(
            scenario_id=f"xdim_{i:05d}",
            goal=goal,
            category=cat,
            difficulty=diff,
            required_tools=required,
            injected_failure=injected,
        ))

    return CrossDimWorkload(
        scenarios=scenarios,
        n_scenarios=n_scenarios,
        n_scenarios_with_failure=n_with_failure,
        failure_distribution=kind_counts,
        by_category=cat_counts,
    )
