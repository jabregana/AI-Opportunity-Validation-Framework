"""Synthetic task-completion workload for testing tool variants.

Generates tasks where each task has:
  - A goal (string description)
  - Required tools (subset of the universe; agent must call all of them)
  - Helper tools (optional; calling them doesn't hurt completion)
  - Distractor tools (irrelevant; calling them costs budget)

The workload is deterministic with a seed. ToolVariants that decide
which subset of the tool universe to expose can be benchmarked
against the workload by measuring:

  - Completion rate (agent saw all required tools and could call them)
  - Selection precision (true required / all exposed)
  - Selection recall (true required exposed / all required available)
  - Per-task latency / cost (proportional to exposed set size, since
    each tool description costs tokens)

Day 2 of the Tools Stage 2 plan in docs/opportunity-tools.md. The
ToolVariant ABC + noop baseline live at runner/dimensions/tools/.

Stage 3 swaps in real tool ecosystems (MCP servers, LangChain tool
registries) and real agent traces.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field


# Realistic tool categories. Each task draws required tools from one
# or two categories; distractors come from any category. This mimics
# the real-world property that an agent typically needs tools from
# one or two domains for a given task, even though many domains are
# represented in its tool registry.
TOOL_CATEGORIES = {
    "search": ["web_search", "doc_search", "code_search", "image_search",
               "video_search"],
    "data": ["sql_query", "csv_read", "json_parse", "yaml_parse",
             "xml_parse"],
    "files": ["file_read", "file_write", "file_list", "file_delete",
              "file_move"],
    "communication": ["send_email", "send_slack", "post_tweet",
                      "send_sms", "schedule_meeting"],
    "computation": ["calculator", "matrix_solve", "regression",
                    "statistics", "unit_convert"],
    "external_api": ["weather", "stock_price", "currency_rate",
                     "geocode", "translate"],
    "system": ["bash_exec", "git_status", "process_list", "memory_info",
               "disk_info"],
}


def _flatten_tool_universe() -> list[str]:
    return [t for cat in TOOL_CATEGORIES.values() for t in cat]


TOOL_UNIVERSE: list[str] = _flatten_tool_universe()
TOOL_TO_CATEGORY: dict[str, str] = {
    t: cat for cat, tools in TOOL_CATEGORIES.items() for t in tools
}


@dataclass
class ToolTask:
    """One task the agent should complete."""

    task_id: str
    goal: str
    required_tools: list[str]
    helper_tools: list[str] = field(default_factory=list)
    # Distractors are not stored per-task; the variant decides which
    # subset of the universe to expose, and any tool in the exposed
    # set that is not in required + helper is effectively a distractor
    # for that task.


@dataclass
class ToolSelectionWorkload:
    """A batch of tasks + the full tool universe they were drawn from."""

    tasks: list[ToolTask]
    tool_universe: list[str]
    categories: dict[str, list[str]]
    n_tasks: int
    avg_required_per_task: float


def _category_for_goal(category: str) -> str:
    """Generate a plausible goal description for a category."""
    examples = {
        "search": "Find information about {topic}",
        "data": "Process the dataset and report {metric}",
        "files": "Reorganize the project's {target} files",
        "communication": "Notify the team about {event}",
        "computation": "Compute {quantity} from the inputs",
        "external_api": "Look up the current {datum} for the user",
        "system": "Inspect the system's {resource} and report",
    }
    return examples.get(category, "Complete a {category} task")


def generate_tool_selection_workload(
    n_tasks: int = 200,
    required_per_task: tuple[int, int] = (2, 4),
    helper_per_task: tuple[int, int] = (0, 2),
    cross_category_chance: float = 0.30,
    seed: int = 0,
) -> ToolSelectionWorkload:
    """Generate a deterministic task workload.

    Args:
      n_tasks: how many tasks to generate.
      required_per_task: (min, max) inclusive range for the count of
        required tools per task.
      helper_per_task: same for helper tools.
      cross_category_chance: probability that a task draws required
        tools from two categories instead of one.
      seed: rng seed for determinism.

    Returns:
      ToolSelectionWorkload. Same seed always produces identical
      tasks, required/helper tool selections, and ordering.
    """
    rng = random.Random(seed)
    category_names = list(TOOL_CATEGORIES.keys())

    tasks: list[ToolTask] = []
    total_required = 0

    for i in range(n_tasks):
        # Pick primary category (and maybe secondary)
        primary = rng.choice(category_names)
        used_categories = [primary]
        if rng.random() < cross_category_chance:
            other_categories = [c for c in category_names if c != primary]
            used_categories.append(rng.choice(other_categories))

        # Required tools: sample from the union of used categories
        pool_required = [t for c in used_categories
                         for t in TOOL_CATEGORIES[c]]
        n_req = rng.randint(required_per_task[0],
                            min(required_per_task[1], len(pool_required)))
        required = rng.sample(pool_required, n_req)

        # Helper tools: sample from used categories minus required
        pool_helper = [t for t in pool_required if t not in required]
        n_help = rng.randint(helper_per_task[0],
                             min(helper_per_task[1], max(0, len(pool_helper))))
        helper = rng.sample(pool_helper, n_help) if pool_helper else []

        goal = f"Task {i}: " + _category_for_goal(used_categories[0]).format(
            topic="a topic", metric="a metric", target="some",
            event="an event", quantity="something", datum="a value",
            resource="a resource",
        )

        tasks.append(ToolTask(
            task_id=f"task_{i:05d}",
            goal=goal,
            required_tools=required,
            helper_tools=helper,
        ))
        total_required += n_req

    return ToolSelectionWorkload(
        tasks=tasks,
        tool_universe=list(TOOL_UNIVERSE),
        categories={k: list(v) for k, v in TOOL_CATEGORIES.items()},
        n_tasks=n_tasks,
        avg_required_per_task=total_required / max(1, n_tasks),
    )
