"""Tests for the six-dimension agent-system scaffolding.

Covers:
  - The DimensionVariant marker class
  - Each of the four scaffolded dimensions (prompt, tools, policy,
    recovery): factory registry, build(), unknown-id error, the noop
    baseline's behavior, dimension attribute
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from runner.dimensions import DIMENSIONS, DimensionVariant
from runner.dimensions.prompt import (
    FACTORIES as PROMPT_FACTORIES,
    PromptVariant,
    build as build_prompt,
)
from runner.dimensions.tools import (
    FACTORIES as TOOL_FACTORIES,
    ToolCall,
    ToolVariant,
    build as build_tool,
)
from runner.dimensions.policy import (
    FACTORIES as POLICY_FACTORIES,
    AgentStep,
    PolicyVariant,
    build as build_policy,
)
from runner.dimensions.recovery import (
    FACTORIES as RECOVERY_FACTORIES,
    Failure,
    RecoveryAction,
    RecoveryVariant,
    build as build_recovery,
)


# ---------------- DimensionVariant marker ----------------


def test_dimensions_list_has_six_entries():
    assert set(DIMENSIONS) == {
        "model", "prompt", "tools", "memory", "policy", "recovery"
    }


def test_all_dimension_abcs_inherit_from_dimension_variant():
    for abc in [PromptVariant, ToolVariant, PolicyVariant, RecoveryVariant]:
        assert issubclass(abc, DimensionVariant)


# ---------------- prompt dimension ----------------


def test_prompt_factory_has_noop_baseline():
    assert "b-default-prompt" in PROMPT_FACTORIES


def test_prompt_build_unknown_raises():
    with pytest.raises(KeyError):
        build_prompt("nonexistent")


def test_prompt_noop_returns_raw_unchanged():
    v = build_prompt("b-default-prompt")
    assert v.render({"raw": "hello world"}) == "hello world"


def test_prompt_noop_handles_missing_raw():
    v = build_prompt("b-default-prompt")
    assert v.render({}) == ""


def test_prompt_variant_has_dimension_attr():
    v = build_prompt("b-default-prompt")
    assert v.dimension == "prompt"


def test_prompt_variant_default_output_schema_is_none():
    v = build_prompt("b-default-prompt")
    assert v.output_schema() is None


# ---------------- tools dimension ----------------


def test_tools_factory_has_noop_baseline():
    assert "b-allow-all-tools" in TOOL_FACTORIES


def test_tools_build_unknown_raises():
    with pytest.raises(KeyError):
        build_tool("nonexistent")


def test_tools_noop_exposes_context_tools():
    v = build_tool("b-allow-all-tools")
    ctx = {"all_tools": ["search", "calculator", "write_file"]}
    assert v.available_tools(ctx) == ["search", "calculator", "write_file"]


def test_tools_noop_allows_any_call():
    v = build_tool("b-allow-all-tools")
    call = ToolCall(name="rm_rf_root", arguments={"path": "/"})
    assert v.should_allow_call(call, context={}) is True


def test_tools_noop_handles_missing_tools_context():
    v = build_tool("b-allow-all-tools")
    assert v.available_tools({}) == []


def test_tools_variant_has_dimension_attr():
    v = build_tool("b-allow-all-tools")
    assert v.dimension == "tools"


# ---------------- policy dimension ----------------


def test_policy_factory_has_noop_baseline():
    assert "b-single-shot-policy" in POLICY_FACTORIES


def test_policy_build_unknown_raises():
    with pytest.raises(KeyError):
        build_policy("nonexistent")


def test_policy_noop_finishes_immediately():
    v = build_policy("b-single-shot-policy")
    step = v.next_step(history=[], context={})
    assert step.kind == "finish"


def test_policy_noop_ignores_history():
    v = build_policy("b-single-shot-policy")
    history = [AgentStep(kind="think", payload={"thought": "x"})]
    step = v.next_step(history=history, context={})
    assert step.kind == "finish"


def test_policy_variant_has_dimension_attr():
    v = build_policy("b-single-shot-policy")
    assert v.dimension == "policy"


# ---------------- recovery dimension ----------------


def test_recovery_factory_has_noop_baseline():
    assert "b-abort-on-failure" in RECOVERY_FACTORIES


def test_recovery_build_unknown_raises():
    with pytest.raises(KeyError):
        build_recovery("nonexistent")


def test_recovery_noop_aborts_on_tool_error():
    v = build_recovery("b-abort-on-failure")
    fail = Failure(kind="tool_error", detail={"tool": "search"})
    action = v.recover(fail, context={})
    assert action.kind == "abort"


def test_recovery_noop_aborts_on_refusal():
    v = build_recovery("b-abort-on-failure")
    fail = Failure(kind="model_refusal")
    action = v.recover(fail, context={})
    assert action.kind == "abort"


def test_recovery_action_payload_carries_failure_kind():
    v = build_recovery("b-abort-on-failure")
    fail = Failure(kind="timeout")
    action = v.recover(fail, context={})
    assert action.payload.get("failure_kind") == "timeout"


def test_recovery_variant_has_dimension_attr():
    v = build_recovery("b-abort-on-failure")
    assert v.dimension == "recovery"


# ---------------- Cross-dimension integration ----------------


def test_all_noop_variants_are_dimension_variants():
    for build_fn, name in [
        (build_prompt, "b-default-prompt"),
        (build_tool, "b-allow-all-tools"),
        (build_policy, "b-single-shot-policy"),
        (build_recovery, "b-abort-on-failure"),
    ]:
        v = build_fn(name)
        assert isinstance(v, DimensionVariant), f"{name} is not a DimensionVariant"


def test_each_dimension_has_unique_baseline_name():
    names = {
        "b-default-prompt",
        "b-allow-all-tools",
        "b-single-shot-policy",
        "b-abort-on-failure",
    }
    assert len(names) == 4  # sanity: no accidental collision
