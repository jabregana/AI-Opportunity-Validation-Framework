"""Tests for the synthetic prompt-task workload."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_prompt_tasks import (
    GOAL_TEMPLATES,
    TASK_CATEGORIES,
    generate_prompt_task_workload,
)


def test_workload_deterministic_with_same_seed():
    w1 = generate_prompt_task_workload(n_tasks=50, seed=42)
    w2 = generate_prompt_task_workload(n_tasks=50, seed=42)
    for t1, t2 in zip(w1.tasks, w2.tasks):
        assert (t1.task_id, t1.category, t1.difficulty, t1.goal) == (
            t2.task_id, t2.category, t2.difficulty, t2.goal,
        )


def test_workload_has_requested_task_count():
    w = generate_prompt_task_workload(n_tasks=37, seed=1)
    assert w.n_tasks == 37
    assert len(w.tasks) == 37


def test_task_ids_unique():
    w = generate_prompt_task_workload(n_tasks=100, seed=1)
    ids = [t.task_id for t in w.tasks]
    assert len(ids) == len(set(ids))


def test_difficulty_in_range():
    w = generate_prompt_task_workload(n_tasks=200, seed=1)
    for t in w.tasks:
        assert 1 <= t.difficulty <= 5


def test_category_in_range():
    w = generate_prompt_task_workload(n_tasks=200, seed=1)
    for t in w.tasks:
        assert t.category in TASK_CATEGORIES


def test_goal_non_empty():
    w = generate_prompt_task_workload(n_tasks=50, seed=1)
    for t in w.tasks:
        assert isinstance(t.goal, str)
        assert len(t.goal) > 0


def test_ground_truth_non_empty():
    w = generate_prompt_task_workload(n_tasks=50, seed=1)
    for t in w.tasks:
        assert len(t.ground_truth) > 0


def test_by_category_count_sums_to_total():
    w = generate_prompt_task_workload(n_tasks=100, seed=1)
    assert sum(w.by_category.values()) == w.n_tasks


def test_by_difficulty_count_sums_to_total():
    w = generate_prompt_task_workload(n_tasks=100, seed=1)
    assert sum(w.by_difficulty.values()) == w.n_tasks


def test_categories_filter_works():
    w = generate_prompt_task_workload(
        n_tasks=50, categories=("reasoning", "code"), seed=1,
    )
    for t in w.tasks:
        assert t.category in {"reasoning", "code"}


def test_all_categories_have_goal_templates():
    for cat in TASK_CATEGORIES:
        assert cat in GOAL_TEMPLATES
        assert len(GOAL_TEMPLATES[cat]) > 0
