"""PolicyVariant ABC plus the AgentStep dataclass.

A policy variant decides the next step the agent should take, given
the history so far. The four step kinds cover the standard agentic
loop shapes (ReAct, plan-and-execute, reflection):

  think    - internal reasoning, no external side-effect
  act      - call a tool (payload typically carries the ToolCall)
  observe  - record a tool result or external event
  finish   - return final answer
"""
from __future__ import annotations
from abc import abstractmethod
from dataclasses import dataclass, field

from ..base import DimensionVariant


@dataclass
class AgentStep:
    """One step in the agent's execution trace."""

    kind: str  # "think" | "act" | "observe" | "finish"
    payload: dict = field(default_factory=dict)


class PolicyVariant(DimensionVariant):
    """A variant that decides the agent's next step."""

    dimension: str = "policy"

    @abstractmethod
    def next_step(self, history: list[AgentStep], context: dict) -> AgentStep:
        """Return the next step given the history and context.

        history is the full trace so far (oldest first). context carries
        task-scoped metadata (user goal, available tools, budget).
        """
        raise NotImplementedError
