"""Synthetic policy-task workload for testing PolicyVariants.

Generates tasks where each task has:
  - A goal (string)
  - A task class (single_step | multi_step | needs_reflection | needs_replan)
  - A difficulty (1-5)
  - Ground-truth: expected number of meaningful steps

Different execution policies have different (task_class, difficulty) ->
P(complete) profiles in the simulator. The variants land in
runner/dimensions/policy/; the simulator + runner land in
runner/policy_runner.py.

Day 2 of the Policy Stage 2 plan in docs/opportunity-policy.md.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field


TASK_CLASSES = (
    "single_step",      # 1 model call suffices (greeting, classification)
    "multi_step",       # 2-4 model calls / tool calls in sequence
    "needs_reflection", # benefits from self-critique
    "needs_replan",     # initial plan was wrong; benefits from replanning
)

GOAL_TEMPLATES: dict[str, list[str]] = {
    "single_step": [
        "Greet the user as {name}.",
        "Classify '{text}' as positive or negative.",
        "Translate '{phrase}' to French.",
        "Echo the input: {input}.",
    ],
    "multi_step": [
        "Find {topic}, then summarize the top result.",
        "Look up the price of {item} and compare to {other_item}.",
        "Fetch the user's profile, then send a {message_kind} email.",
        "Compute {operation} on the dataset, then save to a file.",
    ],
    "needs_reflection": [
        "Solve this puzzle step-by-step: {puzzle}.",
        "Critique and revise this argument: {argument}.",
        "Improve the wording of: {text}.",
        "Find the bug in this code and fix it: {code}.",
    ],
    "needs_replan": [
        "Achieve {goal}. (The first apparent path may not work.)",
        "Reach {state} via the simplest route, but expect obstacles.",
        "Compose {composition} given changing constraints: {constraints}.",
        "Negotiate {target} given the other party's stated objection.",
    ],
}


@dataclass
class PolicyTask:
    """One policy-completion task."""

    task_id: str
    task_class: str  # one of TASK_CLASSES
    difficulty: int  # 1-5
    goal: str
    ground_truth_steps: int  # expected meaningful steps for an oracle policy


@dataclass
class PolicyTaskWorkload:
    tasks: list[PolicyTask]
    n_tasks: int
    by_class: dict[str, int] = field(default_factory=dict)
    by_difficulty: dict[int, int] = field(default_factory=dict)


def _fill_template(template: str, rng: random.Random) -> str:
    fillers = {
        "{name}": rng.choice(["Alex", "Pat", "Sam", "Jordan"]),
        "{text}": rng.choice(["the report", "this email", "the message"]),
        "{phrase}": rng.choice(["hello world", "thank you", "see you"]),
        "{input}": "the input string",
        "{topic}": rng.choice(["the latest model release", "the API change",
                              "the policy update"]),
        "{item}": rng.choice(["AAPL", "TSLA", "NVDA"]),
        "{other_item}": rng.choice(["MSFT", "GOOG", "AMZN"]),
        "{message_kind}": rng.choice(["welcome", "follow-up", "reminder"]),
        "{operation}": rng.choice(["regression", "mean", "summary stats"]),
        "{puzzle}": "the logic puzzle",
        "{argument}": "the argument",
        "{code}": "the code",
        "{goal}": rng.choice(["the agreement", "the consensus"]),
        "{state}": rng.choice(["the final state", "the goal state"]),
        "{composition}": rng.choice(["the proposal", "the response"]),
        "{constraints}": rng.choice(["budget and time", "scope and risk"]),
        "{target}": rng.choice(["the contract terms", "the timeline"]),
    }
    out = template
    for k, v in fillers.items():
        out = out.replace(k, v)
    return out


def generate_policy_task_workload(
    n_tasks: int = 300,
    class_distribution: dict[str, float] | None = None,
    difficulty_distribution: tuple[float, ...] = (0.15, 0.25, 0.30, 0.20, 0.10),
    seed: int = 0,
) -> PolicyTaskWorkload:
    """Generate a deterministic policy-task workload."""
    rng = random.Random(seed)
    dist = class_distribution or {
        "single_step": 0.30,
        "multi_step": 0.35,
        "needs_reflection": 0.20,
        "needs_replan": 0.15,
    }

    tasks: list[PolicyTask] = []
    by_class: dict[str, int] = {c: 0 for c in TASK_CLASSES}
    by_diff: dict[int, int] = {d: 0 for d in range(1, 6)}

    for i in range(n_tasks):
        task_class = rng.choices(
            list(dist.keys()), weights=list(dist.values()), k=1,
        )[0]
        diff = rng.choices(
            list(range(1, 6)),
            weights=list(difficulty_distribution),
            k=1,
        )[0]
        template = rng.choice(GOAL_TEMPLATES[task_class])
        goal = _fill_template(template, rng)

        # Oracle step count varies by class
        oracle_steps = {
            "single_step": 1,
            "multi_step": rng.randint(2, 4),
            "needs_reflection": rng.randint(2, 4),
            "needs_replan": rng.randint(3, 5),
        }[task_class]

        tasks.append(PolicyTask(
            task_id=f"task_{i:05d}",
            task_class=task_class,
            difficulty=diff,
            goal=goal,
            ground_truth_steps=oracle_steps,
        ))
        by_class[task_class] += 1
        by_diff[diff] += 1

    return PolicyTaskWorkload(
        tasks=tasks, n_tasks=n_tasks,
        by_class=by_class, by_difficulty=by_diff,
    )
