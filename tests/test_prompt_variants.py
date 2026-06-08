"""Tests for the prompt dimension pilot variants + runner."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_prompt_tasks import (
    TASK_CATEGORIES,
    generate_prompt_task_workload,
)
from runner.dimensions.prompt import FACTORIES, build
from runner.dimensions.prompt.strategies import (
    CoTPromptVariant,
    CoTStructuredPromptVariant,
    DirectStructuredPromptVariant,
    FewShot1PromptVariant,
    FewShot3PromptVariant,
)
from runner.prompt_runner import (
    STRATEGY_CATEGORY_LIFT,
    compute_uc_prompt_gates,
    run_prompt,
)


# ---------------- Factory registration ----------------


def test_all_pilot_variants_registered():
    for vid in [
        "b-default-prompt",
        "prompt-v0.1.0-cot",
        "prompt-v0.1.1-direct-structured",
        "prompt-v0.1.2-few-shot-1",
        "prompt-v0.1.3-few-shot-3",
        "prompt-v0.1.4-cot-plus-structured",
    ]:
        assert vid in FACTORIES
        assert build(vid).name == vid


# ---------------- Variant render behavior ----------------


def test_cot_prefix_present():
    v = build("prompt-v0.1.0-cot")
    out = v.render({"raw": "What is 2+2?"})
    assert "step-by-step" in out.lower()
    assert "What is 2+2?" in out


def test_structured_appends_schema_hint():
    v = build("prompt-v0.1.1-direct-structured")
    out = v.render({"raw": "Classify this."})
    assert "json" in out.lower()
    assert v.output_schema() is not None


def test_few_shot_1_includes_one_example():
    v = build("prompt-v0.1.2-few-shot-1")
    out = v.render({"raw": "TARGET_QUESTION"})
    assert out.count("Q:") == 1
    assert "TARGET_QUESTION" in out


def test_few_shot_3_includes_three_examples():
    v = build("prompt-v0.1.3-few-shot-3")
    out = v.render({"raw": "TARGET_QUESTION"})
    assert out.count("Q:") == 3
    assert "TARGET_QUESTION" in out


def test_cot_structured_combines_both():
    v = build("prompt-v0.1.4-cot-plus-structured")
    out = v.render({"raw": "Hard question."})
    assert "step-by-step" in out.lower()
    assert "json" in out.lower()
    assert v.output_schema() is not None


# ---------------- Lift table coverage ----------------


def test_lift_table_covers_all_variants_and_categories():
    for vid in FACTORIES:
        assert vid in STRATEGY_CATEGORY_LIFT
        for cat in TASK_CATEGORIES:
            assert cat in STRATEGY_CATEGORY_LIFT[vid]


# ---------------- Runner behavior ----------------


def test_runner_baseline_at_baseline_completion():
    # Baseline should hover near the mean of BASE_COMPLETION_BY_DIFFICULTY
    w = generate_prompt_task_workload(n_tasks=200, seed=1)
    r = run_prompt(build("b-default-prompt"), w)
    # Completion rate should be in a reasonable range
    assert 40.0 <= r.completion_rate_pct <= 75.0


def test_runner_cot_beats_baseline():
    w = generate_prompt_task_workload(n_tasks=300, seed=1)
    base = run_prompt(build("b-default-prompt"), w)
    cot = run_prompt(build("prompt-v0.1.0-cot"), w)
    assert cot.completion_rate_pct > base.completion_rate_pct


def test_runner_few_shot_3_costlier_than_few_shot_1():
    w = generate_prompt_task_workload(n_tasks=200, seed=1)
    fs1 = run_prompt(build("prompt-v0.1.2-few-shot-1"), w)
    fs3 = run_prompt(build("prompt-v0.1.3-few-shot-3"), w)
    assert fs3.avg_prompt_tokens > fs1.avg_prompt_tokens
    assert fs3.cost_per_completion > fs1.cost_per_completion


def test_runner_tracks_by_category():
    w = generate_prompt_task_workload(n_tasks=200, seed=1)
    r = run_prompt(build("prompt-v0.1.0-cot"), w)
    # Every category in the workload should have a completion rate
    for cat in w.by_category:
        if w.by_category[cat] > 0:
            assert cat in r.by_category_completion_pct


def test_runner_deterministic_with_seed():
    w = generate_prompt_task_workload(n_tasks=100, seed=1)
    r1 = run_prompt(build("prompt-v0.1.4-cot-plus-structured"), w, seed=7)
    r2 = run_prompt(build("prompt-v0.1.4-cot-plus-structured"), w, seed=7)
    assert r1.n_completed == r2.n_completed


# ---------------- UC-PROMPT gates ----------------


def test_uc_gates_have_all_four():
    w = generate_prompt_task_workload(n_tasks=100, seed=1)
    base = run_prompt(build("b-default-prompt"), w)
    var = run_prompt(build("prompt-v0.1.4-cot-plus-structured"), w)
    gates = compute_uc_prompt_gates(var, base)
    assert set(gates) == {"UC-PROMPT-1", "UC-PROMPT-2",
                          "UC-PROMPT-3", "UC-PROMPT-4"}
