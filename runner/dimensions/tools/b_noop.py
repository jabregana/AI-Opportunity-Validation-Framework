"""b-allow-all-tools: the permissive baseline for the tools dimension.

Exposes every tool in context.get("all_tools", []) and allows every
call. Used as the reference point for tools-dimension UC gates: any
guardrail variant must show its restrictiveness buys a measurable
gain on the dimension's UC gates (latency, cost, safety incidents,
etc).
"""
from __future__ import annotations

from .base import ToolCall, ToolVariant


class AllowAllToolVariant(ToolVariant):
    name = "b-allow-all-tools"

    def available_tools(self, context: dict) -> list[str]:
        return list(context.get("all_tools", []))

    def should_allow_call(self, call: ToolCall, context: dict) -> bool:
        return True
