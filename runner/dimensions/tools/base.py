"""ToolVariant ABC plus the ToolCall dataclass.

A tool variant decides which tools an agent can see on a given turn
and whether a specific tool call should be allowed through.
"""
from __future__ import annotations
from abc import abstractmethod
from dataclasses import dataclass, field

from ..base import DimensionVariant


@dataclass
class ToolCall:
    """One tool invocation the agent is asking to make."""

    name: str
    arguments: dict = field(default_factory=dict)


class ToolVariant(DimensionVariant):
    """A variant that gates the agent's tool access.

    Subclasses override available_tools() at minimum; should_allow_call()
    has a default permissive implementation.
    """

    dimension: str = "tools"

    @abstractmethod
    def available_tools(self, context: dict) -> list[str]:
        """Tool names the agent may see on this turn.

        context carries turn-scoped metadata (user id, conversation
        state, budget remaining, etc). Variants that always expose
        the same set ignore context.
        """
        raise NotImplementedError

    def should_allow_call(self, call: ToolCall, context: dict) -> bool:
        """Veto-or-allow on a specific tool call.

        Default: allow all. Override for guardrail variants.
        """
        return True
