"""Pilot policy variants for Stage 2 baseline.

policy-v0.1.0-react              think -> act -> observe -> finish loop
policy-v0.1.1-plan-execute       plan once upfront, execute each step, finish
policy-v0.1.2-reflect-loop       react + reflect step every N iterations
policy-v0.1.3-handoff            single-shot; on signaled failure, hand off

Each variant implements next_step(history, context). The runner asks
for one step at a time; the variant's policy decides whether to think,
act, observe, or finish based on history and an internal step budget.

Stage 2 hard-codes step budgets and trigger heuristics; Stage 3 would
calibrate against real agent traces.
"""
from __future__ import annotations

from .base import AgentStep, PolicyVariant


class ReActPolicyVariant(PolicyVariant):
    """Think -> act -> observe -> ... loop until budget or finish."""

    name = "policy-v0.1.0-react"

    def __init__(self, max_steps: int = 6):
        self.max_steps = max_steps

    def next_step(self, history: list[AgentStep], context: dict) -> AgentStep:
        # Stop conditions
        if len(history) >= self.max_steps:
            return AgentStep(kind="finish", payload={"reason": "max_steps"})
        # Cycle: think, act, observe, think, act, observe, ...
        cycle = ["think", "act", "observe"]
        n = len(history)
        kind = cycle[n % len(cycle)]
        # When budget allows, finish after a few cycles
        if n >= 4 and kind == "observe":
            # Heuristic: after at least one full think/act/observe cycle,
            # consider finishing on subsequent observe steps based on
            # context["task_class"] (single_step finishes early)
            if context.get("task_class") == "single_step":
                return AgentStep(kind="finish", payload={"reason": "task_done"})
        return AgentStep(kind=kind, payload={"step": n})


class PlanExecutePolicyVariant(PolicyVariant):
    """Plan once, execute each step in plan, finish."""

    name = "policy-v0.1.1-plan-execute"

    def __init__(self, plan_size_by_class: dict[str, int] | None = None):
        self.plan_size = plan_size_by_class or {
            "single_step": 1,
            "multi_step": 3,
            "needs_reflection": 3,
            "needs_replan": 4,
        }

    def next_step(self, history: list[AgentStep], context: dict) -> AgentStep:
        if not history:
            return AgentStep(kind="think", payload={"phase": "plan"})
        task_class = context.get("task_class", "multi_step")
        plan_len = self.plan_size.get(task_class, 3)
        # After plan (history[0]=think), execute plan_len act steps
        n_acts = sum(1 for s in history if s.kind == "act")
        if n_acts < plan_len:
            return AgentStep(kind="act",
                            payload={"step_in_plan": n_acts + 1,
                                     "plan_len": plan_len})
        return AgentStep(kind="finish", payload={"reason": "plan_complete"})


class ReflectLoopPolicyVariant(PolicyVariant):
    """ReAct plus a reflect step every N iterations."""

    name = "policy-v0.1.2-reflect-loop"

    def __init__(self, max_steps: int = 8, reflect_every: int = 3):
        self.max_steps = max_steps
        self.reflect_every = reflect_every

    def next_step(self, history: list[AgentStep], context: dict) -> AgentStep:
        if len(history) >= self.max_steps:
            return AgentStep(kind="finish", payload={"reason": "max_steps"})
        n = len(history)
        # Every N steps, reflect
        if n > 0 and n % self.reflect_every == 0:
            return AgentStep(kind="think",
                            payload={"phase": "reflect"})
        # Otherwise: think -> act -> observe cycle
        cycle = ["think", "act", "observe"]
        kind = cycle[n % len(cycle)]
        if n >= 4 and context.get("task_class") == "single_step":
            return AgentStep(kind="finish", payload={"reason": "task_done"})
        return AgentStep(kind=kind, payload={"step": n})


class HandoffPolicyVariant(PolicyVariant):
    """Single-shot; on signaled failure, hand off to a larger model."""

    name = "policy-v0.1.3-handoff"

    def next_step(self, history: list[AgentStep], context: dict) -> AgentStep:
        # First call: try once
        if not history:
            return AgentStep(kind="act", payload={"attempt": "single_shot"})
        # If context signals failure (set by simulator), hand off
        last = history[-1]
        failure_signaled = last.payload.get("failed", False) if last.payload else False
        if failure_signaled and len(history) < 3:
            return AgentStep(kind="act",
                            payload={"attempt": "handoff_to_larger"})
        return AgentStep(kind="finish",
                        payload={"reason": "single_shot_or_handoff_done"})
