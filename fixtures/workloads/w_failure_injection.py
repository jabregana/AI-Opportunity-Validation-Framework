"""Synthetic failure-injection workload for testing recovery variants.

Produces a stream of task scenarios with controlled failures injected
at known step indices. Each scenario is a sequence of operations the
simulated agent walks through; failures are pre-planned so the runner
can deterministically apply them and measure how the variant's recover()
decision affects task completion.

Workload shape:
  - n_scenarios task scenarios, each with a list of steps
    (model_call / tool_call / validate_output)
  - failure_rate fraction of scenarios contain at least one injected
    failure
  - Failures are distributed across the four standard kinds (tool_error,
    model_refusal, validation_failure, timeout) per failure_distribution
  - Each step has an expected_outcome (success unless overridden by
    an injected failure at that index)
  - Ground truth: success_condition is "final step completes" given
    appropriate recovery

The workload is deliberately abstract: no real tools, no real LLMs.
Stage 2's job is to surface whether the recovery-policy decision
shape is right and whether the harness machinery (paired bootstrap,
UC gates, finding-doc) carries over to this dimension. Stage 3 swaps
in real tool/LLM failures from production traces.

Day 2 of the Stage 2 plan in docs/opportunity-recovery.md. The
RecoveryVariant ABC and the no-op baseline live at
runner/dimensions/recovery/.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field


# Standard failure kinds the workload can inject. Matches the dimensions
# Failure dataclass at runner/dimensions/recovery/base.py.
FAILURE_KINDS = (
    "tool_error",
    "model_refusal",
    "validation_failure",
    "timeout",
)


@dataclass
class TaskStep:
    """One step in a simulated agent task."""

    idx: int
    kind: str  # "model_call" | "tool_call" | "validate_output"
    label: str  # e.g. "call:search" or "model:plan" (for traceability)


@dataclass
class InjectedFailure:
    """A failure pre-injected at a specific step index in a scenario."""

    step_idx: int
    kind: str  # one of FAILURE_KINDS
    detail: dict = field(default_factory=dict)


@dataclass
class TaskScenario:
    """One task the simulated agent walks through."""

    task_id: str
    steps: list[TaskStep]
    injected_failures: list[InjectedFailure]
    success_condition: str = "final_step_completes"


@dataclass
class FailureInjectionWorkload:
    """A batch of task scenarios with their planned failures."""

    scenarios: list[TaskScenario]
    n_scenarios: int
    failure_distribution: dict[str, int]  # kind -> count of scenarios injected
    n_scenarios_with_failure: int


# Default failure distribution: rough real-world frequencies (transient
# tool errors are most common; refusals and timeouts are rarer).
DEFAULT_FAILURE_DISTRIBUTION = {
    "tool_error": 0.55,
    "model_refusal": 0.20,
    "validation_failure": 0.15,
    "timeout": 0.10,
}


def _sample_failure_kind(
    rng: random.Random,
    distribution: dict[str, float],
) -> str:
    """Weighted sample of a failure kind."""
    kinds = list(distribution.keys())
    weights = [distribution[k] for k in kinds]
    return rng.choices(kinds, weights=weights, k=1)[0]


def _build_step_sequence(
    rng: random.Random,
    min_steps: int = 3,
    max_steps: int = 7,
    tool_names: tuple[str, ...] = ("search", "calculator", "fetch", "summarize"),
) -> list[TaskStep]:
    """Build a step sequence: model_call + alternating tool/model + final.

    Typical shape: plan, tool, model, tool, model, ..., respond.
    """
    n = rng.randint(min_steps, max_steps)
    steps: list[TaskStep] = [
        TaskStep(idx=0, kind="model_call", label="model:plan")
    ]
    for i in range(1, n - 1):
        if i % 2 == 1:
            tool = rng.choice(tool_names)
            steps.append(TaskStep(idx=i, kind="tool_call", label=f"tool:{tool}"))
        else:
            steps.append(TaskStep(idx=i, kind="model_call",
                                  label="model:observe"))
    steps.append(TaskStep(idx=n - 1, kind="model_call", label="model:respond"))
    return steps


def generate_failure_injection_workload(
    n_scenarios: int = 100,
    failure_rate: float = 0.30,
    failure_distribution: dict[str, float] | None = None,
    min_steps: int = 3,
    max_steps: int = 7,
    seed: int = 0,
) -> FailureInjectionWorkload:
    """Generate a deterministic failure-injection workload.

    Args:
      n_scenarios: how many task scenarios to generate.
      failure_rate: fraction of scenarios that should have at least one
        injected failure. Default 0.30 (30%).
      failure_distribution: kind -> weight; defaults to
        DEFAULT_FAILURE_DISTRIBUTION. Need not sum to 1; weights are
        normalized at sample time.
      min_steps, max_steps: step count range per scenario.
      seed: rng seed for determinism.

    Returns:
      FailureInjectionWorkload. Same seed always produces identical
      output, including step counts, failure placement, and kinds.
    """
    rng = random.Random(seed)
    distribution = failure_distribution or DEFAULT_FAILURE_DISTRIBUTION

    scenarios: list[TaskScenario] = []
    kind_counts: dict[str, int] = {k: 0 for k in FAILURE_KINDS}
    n_with_failure = 0

    for i in range(n_scenarios):
        task_id = f"task_{i:05d}"
        steps = _build_step_sequence(rng, min_steps, max_steps)

        injected: list[InjectedFailure] = []
        if rng.random() < failure_rate:
            # Inject one failure at a random non-first, non-last step
            # (failures on plan/respond are degenerate; not interesting
            # for policy comparison)
            candidate_indices = list(range(1, len(steps) - 1))
            if candidate_indices:
                step_idx = rng.choice(candidate_indices)
                kind = _sample_failure_kind(rng, distribution)
                injected.append(InjectedFailure(
                    step_idx=step_idx, kind=kind,
                    detail={"step_label": steps[step_idx].label},
                ))
                kind_counts[kind] += 1
                n_with_failure += 1

        scenarios.append(TaskScenario(
            task_id=task_id, steps=steps, injected_failures=injected,
        ))

    return FailureInjectionWorkload(
        scenarios=scenarios,
        n_scenarios=n_scenarios,
        failure_distribution=kind_counts,
        n_scenarios_with_failure=n_with_failure,
    )
