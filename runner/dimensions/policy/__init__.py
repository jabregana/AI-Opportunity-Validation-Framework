"""Execution-policy dimension: variants that decide what the agent does
next given the history so far.

A PolicyVariant takes a history of steps and returns the next step.
This is where ReAct vs plan-and-execute vs reflection loops vs
multi-agent handoff live.

Today this package contains only the single-shot baseline (always
finish after one step). Real variants land here after the first
Stage 1 scan on the execution-policy dimension.
"""
from __future__ import annotations
from typing import Callable

from .base import AgentStep, PolicyVariant
from .b_noop import SingleShotPolicyVariant
from .policies import (
    HandoffPolicyVariant,
    PlanExecutePolicyVariant,
    ReActPolicyVariant,
    ReflectLoopPolicyVariant,
)


FACTORIES: dict[str, Callable[[], PolicyVariant]] = {
    "b-single-shot-policy": SingleShotPolicyVariant,
    "policy-v0.1.0-react": ReActPolicyVariant,
    "policy-v0.1.1-plan-execute": PlanExecutePolicyVariant,
    "policy-v0.1.2-reflect-loop": ReflectLoopPolicyVariant,
    "policy-v0.1.3-handoff": HandoffPolicyVariant,
}


def build(variant_id: str) -> PolicyVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown policy variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["AgentStep", "PolicyVariant", "build", "FACTORIES"]
