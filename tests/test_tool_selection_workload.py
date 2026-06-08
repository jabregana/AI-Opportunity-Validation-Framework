"""Tests for the synthetic tool-selection workload (Day 2 of Tools
Stage 2)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_tool_selection import (
    TOOL_CATEGORIES,
    TOOL_TO_CATEGORY,
    TOOL_UNIVERSE,
    ToolSelectionWorkload,
    ToolTask,
    generate_tool_selection_workload,
)


# ---------------- Universe sanity ----------------


def test_tool_universe_is_non_empty():
    assert len(TOOL_UNIVERSE) >= 30


def test_tool_universe_no_duplicates():
    assert len(TOOL_UNIVERSE) == len(set(TOOL_UNIVERSE))


def test_every_tool_in_a_category():
    for t in TOOL_UNIVERSE:
        assert t in TOOL_TO_CATEGORY


def test_categories_partition_universe():
    flattened = [t for cat in TOOL_CATEGORIES.values() for t in cat]
    assert set(flattened) == set(TOOL_UNIVERSE)


# ---------------- Determinism ----------------


def test_workload_deterministic_with_same_seed():
    w1 = generate_tool_selection_workload(n_tasks=50, seed=42)
    w2 = generate_tool_selection_workload(n_tasks=50, seed=42)
    assert w1.n_tasks == w2.n_tasks
    for t1, t2 in zip(w1.tasks, w2.tasks):
        assert t1.task_id == t2.task_id
        assert t1.required_tools == t2.required_tools
        assert t1.helper_tools == t2.helper_tools


def test_different_seeds_produce_different_workloads():
    w1 = generate_tool_selection_workload(n_tasks=50, seed=1)
    w2 = generate_tool_selection_workload(n_tasks=50, seed=2)
    differs = any(
        t1.required_tools != t2.required_tools
        for t1, t2 in zip(w1.tasks, w2.tasks)
    )
    assert differs


# ---------------- Task structure ----------------


def test_workload_has_requested_task_count():
    w = generate_tool_selection_workload(n_tasks=37, seed=1)
    assert w.n_tasks == 37
    assert len(w.tasks) == 37


def test_task_ids_unique():
    w = generate_tool_selection_workload(n_tasks=100, seed=1)
    ids = [t.task_id for t in w.tasks]
    assert len(ids) == len(set(ids))


def test_required_tool_count_in_range():
    w = generate_tool_selection_workload(
        n_tasks=100, required_per_task=(2, 4), seed=1,
    )
    for t in w.tasks:
        assert 2 <= len(t.required_tools) <= 4


def test_helper_tool_count_in_range():
    w = generate_tool_selection_workload(
        n_tasks=100, helper_per_task=(0, 2), seed=1,
    )
    for t in w.tasks:
        assert 0 <= len(t.helper_tools) <= 2


def test_required_and_helper_tools_disjoint():
    w = generate_tool_selection_workload(n_tasks=100, seed=1)
    for t in w.tasks:
        assert set(t.required_tools).isdisjoint(set(t.helper_tools))


def test_required_tools_drawn_from_universe():
    w = generate_tool_selection_workload(n_tasks=100, seed=1)
    universe = set(w.tool_universe)
    for t in w.tasks:
        for tool in t.required_tools:
            assert tool in universe


# ---------------- Category cohesion ----------------


def test_single_category_task_has_required_from_one_category():
    # With cross_category_chance=0, every task should draw required
    # tools from exactly one category
    w = generate_tool_selection_workload(
        n_tasks=100, cross_category_chance=0.0, seed=1,
    )
    for t in w.tasks:
        cats = {TOOL_TO_CATEGORY[tool] for tool in t.required_tools}
        assert len(cats) == 1


def test_cross_category_tasks_appear_at_expected_rate():
    # With cross_category_chance=1.0, many tasks should span two cats
    w = generate_tool_selection_workload(
        n_tasks=200, cross_category_chance=1.0, seed=1,
    )
    multi_cat = sum(
        1 for t in w.tasks
        if len({TOOL_TO_CATEGORY[tool] for tool in t.required_tools}) >= 2
    )
    # Not all tasks span two because required_per_task may produce only
    # 2 tools both from one category; but most should
    assert multi_cat >= w.n_tasks * 0.4


# ---------------- Aggregate stats ----------------


def test_avg_required_per_task_is_computed():
    w = generate_tool_selection_workload(
        n_tasks=100, required_per_task=(2, 4), seed=1,
    )
    assert 2.0 <= w.avg_required_per_task <= 4.0


def test_categories_are_carried_in_workload():
    w = generate_tool_selection_workload(n_tasks=10, seed=1)
    assert set(w.categories) == set(TOOL_CATEGORIES)
    for cat in w.categories:
        assert w.categories[cat] == TOOL_CATEGORIES[cat]


# ---------------- Task content ----------------


def test_every_task_has_a_goal_string():
    w = generate_tool_selection_workload(n_tasks=20, seed=1)
    for t in w.tasks:
        assert isinstance(t.goal, str)
        assert len(t.goal) > 0
