"""Tests for the tool dimension's pilot variants + runner."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from fixtures.workloads.w_tool_selection import (
    TOOL_CATEGORIES,
    TOOL_UNIVERSE,
    generate_tool_selection_workload,
)
from runner.dimensions.tools import (
    FACTORIES,
    ToolCall,
    build,
)
from runner.dimensions.tools.budget_bucketed import (
    BudgetBucketedToolVariant,
    _stable_tool_score,
)
from runner.dimensions.tools.intent_classified import (
    CATEGORY_KEYWORDS,
    IntentClassifiedToolVariant,
)
from runner.tool_runner import (
    compute_uc_tool_gates,
    run_tools,
)


# ---------------- Factory registration ----------------


def test_factories_include_pilot_variants():
    assert "b-allow-all-tools" in FACTORIES
    assert "tool-v0.1.0-budget-bucketed" in FACTORIES
    assert "tool-v0.1.1-intent-classified" in FACTORIES


def test_build_returns_correct_classes():
    assert isinstance(build("tool-v0.1.0-budget-bucketed"),
                      BudgetBucketedToolVariant)
    assert isinstance(build("tool-v0.1.1-intent-classified"),
                      IntentClassifiedToolVariant)


# ---------------- BudgetBucketedToolVariant ----------------


def test_budget_caps_exposure_at_max():
    v = BudgetBucketedToolVariant(max_exposed=5)
    ctx = {"all_tools": list(TOOL_UNIVERSE)}
    exposed = v.available_tools(ctx)
    assert len(exposed) == 5


def test_budget_exposes_all_if_universe_smaller_than_budget():
    v = BudgetBucketedToolVariant(max_exposed=100)
    small_universe = ["a", "b", "c"]
    ctx = {"all_tools": small_universe}
    exposed = v.available_tools(ctx)
    assert set(exposed) == set(small_universe)


def test_budget_deterministic_with_same_seed():
    v1 = BudgetBucketedToolVariant(max_exposed=8, seed=42)
    v2 = BudgetBucketedToolVariant(max_exposed=8, seed=42)
    ctx = {"all_tools": list(TOOL_UNIVERSE)}
    assert v1.available_tools(ctx) == v2.available_tools(ctx)


def test_budget_different_seeds_pick_different_tools():
    v1 = BudgetBucketedToolVariant(max_exposed=8, seed=1)
    v2 = BudgetBucketedToolVariant(max_exposed=8, seed=2)
    ctx = {"all_tools": list(TOOL_UNIVERSE)}
    assert v1.available_tools(ctx) != v2.available_tools(ctx)


def test_stable_tool_score_consistent():
    s1 = _stable_tool_score("web_search", seed=0)
    s2 = _stable_tool_score("web_search", seed=0)
    assert s1 == s2


# ---------------- IntentClassifiedToolVariant ----------------


def test_intent_classifies_search_keyword():
    v = IntentClassifiedToolVariant()
    ctx = {
        "all_tools": list(TOOL_UNIVERSE),
        "categories": TOOL_CATEGORIES,
        "goal": "Find information about Python",
    }
    exposed = v.available_tools(ctx)
    # Should include search-category tools
    search_tools = set(TOOL_CATEGORIES["search"])
    assert search_tools.issubset(set(exposed))


def test_intent_classifies_communication_keyword():
    v = IntentClassifiedToolVariant()
    ctx = {
        "all_tools": list(TOOL_UNIVERSE),
        "categories": TOOL_CATEGORIES,
        "goal": "Notify the team about a release",
    }
    exposed = v.available_tools(ctx)
    comm_tools = set(TOOL_CATEGORIES["communication"])
    assert comm_tools.issubset(set(exposed))


def test_intent_falls_back_when_no_category_match():
    v = IntentClassifiedToolVariant(fallback_max_exposed=5)
    ctx = {
        "all_tools": list(TOOL_UNIVERSE),
        "categories": TOOL_CATEGORIES,
        "goal": "xyzzy completely unrelated nonsense phrase",
    }
    exposed = v.available_tools(ctx)
    # Should fall back to first-N alphabetically
    assert len(exposed) <= 5


def test_intent_classifier_keywords_cover_all_categories():
    # CATEGORY_KEYWORDS must have an entry for every TOOL_CATEGORIES key
    assert set(CATEGORY_KEYWORDS) == set(TOOL_CATEGORIES)


# ---------------- Runner ----------------


def test_runner_baseline_exposes_all_tools():
    w = generate_tool_selection_workload(n_tasks=30, seed=1)
    r = run_tools(build("b-allow-all-tools"), w)
    assert r.avg_exposed_per_task == len(w.tool_universe)
    # Recall must be 100% (everything exposed)
    assert r.selection_recall_pct == 100.0


def test_runner_budget_loses_many_required_tools():
    w = generate_tool_selection_workload(n_tasks=100, seed=1)
    baseline = run_tools(build("b-allow-all-tools"), w)
    budget = run_tools(build("tool-v0.1.0-budget-bucketed"), w)
    # Budget-bucketed without intent should miss required tools often
    assert budget.n_missing_required > 0
    assert budget.completion_rate_pct < baseline.completion_rate_pct


def test_runner_intent_beats_budget_on_completion():
    w = generate_tool_selection_workload(n_tasks=100, seed=1)
    budget = run_tools(build("tool-v0.1.0-budget-bucketed"), w)
    intent = run_tools(build("tool-v0.1.1-intent-classified"), w)
    assert intent.completion_rate_pct > budget.completion_rate_pct


def test_runner_intent_more_precise_than_baseline():
    w = generate_tool_selection_workload(n_tasks=100, seed=1)
    baseline = run_tools(build("b-allow-all-tools"), w)
    intent = run_tools(build("tool-v0.1.1-intent-classified"), w)
    assert intent.selection_precision_pct > baseline.selection_precision_pct


def test_runner_deterministic_with_same_seed():
    w = generate_tool_selection_workload(n_tasks=50, seed=7)
    r1 = run_tools(build("tool-v0.1.1-intent-classified"), w, seed=5)
    r2 = run_tools(build("tool-v0.1.1-intent-classified"), w, seed=5)
    assert r1.n_completed == r2.n_completed
    assert r1.total_cost == r2.total_cost


def test_runner_tracks_failure_reasons():
    w = generate_tool_selection_workload(n_tasks=50, seed=1)
    r = run_tools(build("tool-v0.1.0-budget-bucketed"), w)
    # Total should match
    assert (r.n_completed + r.n_missing_required + r.n_selection_failed
            == r.n_tasks)


# ---------------- UC-TOOL gates ----------------


def test_uc_gates_have_all_four():
    w = generate_tool_selection_workload(n_tasks=50, seed=1)
    baseline = run_tools(build("b-allow-all-tools"), w)
    variant = run_tools(build("tool-v0.1.1-intent-classified"), w)
    gates = compute_uc_tool_gates(variant, baseline)
    assert set(gates) == {"UC-TOOL-1", "UC-TOOL-2", "UC-TOOL-3", "UC-TOOL-4"}


def test_uc_baseline_always_passes_recall_against_itself():
    # b-allow-all has 100% recall by construction; against any variant
    # the recall gate threshold (90%) is meaningful only for narrowed
    # variants
    w = generate_tool_selection_workload(n_tasks=50, seed=1)
    baseline = run_tools(build("b-allow-all-tools"), w)
    # The baseline has 100% recall by construction
    assert baseline.selection_recall_pct == 100.0
