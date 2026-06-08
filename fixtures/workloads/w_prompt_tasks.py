"""Synthetic prompt-task workload for testing PromptVariants.

Generates tasks where each task has:
  - A goal string
  - A category (reasoning, extraction, classification, retrieval, code)
  - A difficulty level (1-5)
  - A ground-truth answer (used by the simulator to score completion)

Different prompt strategies have different (category, difficulty) ->
P(complete) profiles in the simulator. The variants land in
runner/dimensions/prompt/; the simulator + runner land in
runner/prompt_runner.py.

Day 2 of the Prompt Stage 2 plan in docs/opportunity-prompt.md. Real
Stage 3 swaps the simulator for actual LLM calls (the multi-model
ladder at experiments/ladder_sweep_real_data.py).
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field


# Task categories with goal templates per category.
TASK_CATEGORIES = (
    "reasoning",
    "extraction",
    "classification",
    "retrieval",
    "code",
)

GOAL_TEMPLATES: dict[str, list[str]] = {
    "reasoning": [
        "If {a} costs {x} and {b} costs {y}, what is the total?",
        "Why does {phenomenon} happen?",
        "Given {context}, what should you conclude?",
        "What is the next step in {process}?",
        "Compare {x} and {y}, then decide which is better for {goal}.",
    ],
    "extraction": [
        "Extract the entities from: {text}",
        "Pull the key facts out of this passage: {text}",
        "Identify all the dates, names, and locations in: {text}",
        "Return a structured summary of: {text}",
        "List every product mentioned in: {text}",
    ],
    "classification": [
        "Is the sentiment of '{text}' positive or negative?",
        "Classify this text by topic: {text}",
        "Which category does '{text}' belong to?",
        "Is '{text}' spam or legitimate?",
        "Tag the intent of: {text}",
    ],
    "retrieval": [
        "Find the answer to '{question}' in the document.",
        "Look up information about {topic}.",
        "Search for {term} in the knowledge base.",
        "Retrieve all records matching {filter}.",
        "Find the most relevant passage for: {query}",
    ],
    "code": [
        "Write a function that {does_thing}.",
        "Fix the bug in this code: {snippet}",
        "Refactor this for readability: {snippet}",
        "Add error handling to: {snippet}",
        "Translate this {lang} code to Python: {snippet}",
    ],
}


@dataclass
class PromptTask:
    """One prompt-completion task."""

    task_id: str
    category: str  # one of TASK_CATEGORIES
    difficulty: int  # 1-5
    goal: str
    ground_truth: str = ""  # used by simulator to score completion


@dataclass
class PromptTaskWorkload:
    """A batch of prompt tasks."""

    tasks: list[PromptTask]
    n_tasks: int
    by_category: dict[str, int] = field(default_factory=dict)
    by_difficulty: dict[int, int] = field(default_factory=dict)


def _fill_template(template: str, rng: random.Random) -> str:
    """Substitute placeholder tokens with simple synthetic content."""
    fillers = {
        "{a}": rng.choice(["apples", "books", "tickets", "shares"]),
        "{b}": rng.choice(["oranges", "pencils", "passes", "options"]),
        "{x}": str(rng.randint(2, 50)),
        "{y}": str(rng.randint(2, 50)),
        "{phenomenon}": rng.choice(
            ["this", "the result", "the outcome", "the change"]),
        "{context}": "the given context",
        "{process}": rng.choice(
            ["the workflow", "the algorithm", "the sequence"]),
        "{goal}": rng.choice(["accuracy", "speed", "cost", "robustness"]),
        "{text}": rng.choice([
            "the quarterly report", "this customer email",
            "the news article", "the chat log",
        ]),
        "{question}": rng.choice([
            "when did it happen", "what caused it", "who is responsible"]),
        "{topic}": rng.choice([
            "the new product", "the market trend", "the policy change"]),
        "{term}": rng.choice(
            ["the keyword", "this identifier", "the reference"]),
        "{filter}": "the criteria",
        "{query}": "the user query",
        "{does_thing}": rng.choice([
            "validates input", "parses dates", "computes a checksum"]),
        "{snippet}": "the snippet",
        "{lang}": rng.choice(["JavaScript", "Java", "Go"]),
    }
    out = template
    for k, v in fillers.items():
        out = out.replace(k, v)
    return out


def generate_prompt_task_workload(
    n_tasks: int = 250,
    categories: tuple[str, ...] | None = None,
    difficulty_distribution: tuple[float, ...] = (0.10, 0.25, 0.30, 0.25, 0.10),
    seed: int = 0,
) -> PromptTaskWorkload:
    """Generate a deterministic prompt-task workload.

    Args:
      n_tasks: how many tasks to generate.
      categories: which categories to draw from (default: all).
      difficulty_distribution: weights for difficulties 1..5 in order.
        Default is bell-curve centered on 3.
      seed: rng seed for determinism.

    Returns:
      PromptTaskWorkload. Same seed always produces identical output.
    """
    rng = random.Random(seed)
    cats = list(categories) if categories else list(TASK_CATEGORIES)

    tasks: list[PromptTask] = []
    by_cat: dict[str, int] = {c: 0 for c in cats}
    by_diff: dict[int, int] = {d: 0 for d in range(1, 6)}

    for i in range(n_tasks):
        cat = rng.choice(cats)
        diff = rng.choices(
            list(range(1, 6)),
            weights=list(difficulty_distribution),
            k=1,
        )[0]
        template = rng.choice(GOAL_TEMPLATES[cat])
        goal = _fill_template(template, rng)
        # Ground truth is opaque for the simulator; the simulator
        # uses (category, difficulty, variant) to decide P(complete).
        # Real Stage 3 generates actual ground-truth answers and scores
        # actual LLM outputs.
        ground_truth = f"GT_{cat}_{diff}_{i:05d}"

        tasks.append(PromptTask(
            task_id=f"task_{i:05d}",
            category=cat,
            difficulty=diff,
            goal=goal,
            ground_truth=ground_truth,
        ))
        by_cat[cat] += 1
        by_diff[diff] += 1

    return PromptTaskWorkload(
        tasks=tasks, n_tasks=n_tasks,
        by_category=by_cat,
        by_difficulty=by_diff,
    )
