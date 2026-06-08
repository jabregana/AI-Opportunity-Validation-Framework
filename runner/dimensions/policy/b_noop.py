"""b-single-shot-policy: the minimal-loop baseline for the policy dimension.

Always returns finish on the first call, ignoring history. Used as the
reference point for policy-dimension UC gates: any multi-step policy
(ReAct, plan-and-execute, reflection) must show its added loop iterations
buy a measurable gain on task-completion accuracy, robustness, or some
other UC gate justifying the extra latency/cost.
"""
from __future__ import annotations

from .base import AgentStep, PolicyVariant


class SingleShotPolicyVariant(PolicyVariant):
    name = "b-single-shot-policy"

    def next_step(self, history: list[AgentStep], context: dict) -> AgentStep:
        return AgentStep(kind="finish", payload={"reason": "single-shot baseline"})
