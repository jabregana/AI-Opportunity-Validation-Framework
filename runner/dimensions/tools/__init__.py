"""Tools dimension: variants that decide what tools the agent can use
and whether to allow a particular tool call.

A ToolVariant has two responsibilities:
  1. available_tools(context) - which tools are visible this turn
  2. should_allow_call(call, context) - veto-or-allow on a specific call

Variants differ on tool-set composition (full toolbox vs narrow set),
guardrail policy (require args validation, block destructive ops,
budget-cap expensive tools), or selection heuristics (prefer cheap
tools, route by intent class).

Today this package contains only the allow-all baseline. Real variants
land here after the first Stage 1 scan on the tools dimension.
"""
from __future__ import annotations
from typing import Callable

from .base import ToolCall, ToolVariant
from .b_noop import AllowAllToolVariant
from .budget_bucketed import BudgetBucketedToolVariant
from .intent_classified import IntentClassifiedToolVariant


FACTORIES: dict[str, Callable[[], ToolVariant]] = {
    "b-allow-all-tools": AllowAllToolVariant,
    "tool-v0.1.0-budget-bucketed": BudgetBucketedToolVariant,
    "tool-v0.1.1-intent-classified": IntentClassifiedToolVariant,
}


def build(variant_id: str) -> ToolVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown tool variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["ToolCall", "ToolVariant", "build", "FACTORIES"]
