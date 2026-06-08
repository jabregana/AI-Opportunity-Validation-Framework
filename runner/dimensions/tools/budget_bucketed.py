"""Budget-bucketed tool variant.

tool-v0.1.0-budget-bucketed: expose at most max_exposed tools out of
the full universe, chosen deterministically by a stable hash of the
tool name (no intent awareness). Models the naive "limit to N tools
to fit a token budget" strategy that production deployments often
default to.

The deterministic-hash selection (instead of random or popularity-
ranked) keeps results reproducible across runs without smuggling in
extra information. A real production deployment would order tools
by recent usage, predicted-relevance, or similar; that would be the
v0.2.0 successor.
"""
from __future__ import annotations
import hashlib

from .base import ToolCall, ToolVariant


def _stable_tool_score(tool_name: str, seed: int = 0) -> int:
    """Deterministic integer ordering for a tool name, used to pick
    which tools fall under a budget cap."""
    h = hashlib.sha256(f"{seed}:{tool_name}".encode()).digest()
    return int.from_bytes(h[:8], "big")


class BudgetBucketedToolVariant(ToolVariant):
    """Expose at most max_exposed tools, chosen by stable hash."""

    name = "tool-v0.1.0-budget-bucketed"

    def __init__(self, max_exposed: int = 10, seed: int = 0):
        self.max_exposed = max_exposed
        self.seed = seed

    def available_tools(self, context: dict) -> list[str]:
        all_tools = list(context.get("all_tools", []))
        if len(all_tools) <= self.max_exposed:
            return all_tools
        # Pick max_exposed by stable hash; ties broken alphabetically
        ranked = sorted(
            all_tools,
            key=lambda t: (_stable_tool_score(t, self.seed), t),
        )
        return ranked[: self.max_exposed]
