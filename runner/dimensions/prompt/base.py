"""PromptVariant ABC.

A prompt variant decides what prompt string to send the model for a
given task input. The decision can also include an output-format
contract (a schema the model should follow).
"""
from __future__ import annotations
from abc import abstractmethod

from ..base import DimensionVariant


class PromptVariant(DimensionVariant):
    """A variant that decides how to prompt the model.

    Subclasses override render() to produce the final prompt string.
    """

    dimension: str = "prompt"

    @abstractmethod
    def render(self, task_input: dict) -> str:
        """Return the prompt string the model should receive.

        task_input is dimension-agnostic; the variant decides which
        fields it needs. Convention: task_input["raw"] holds the
        unaltered user input, other fields are derived context.
        """
        raise NotImplementedError

    def output_schema(self) -> dict | None:
        """Optional output-format contract.

        Default: no schema (free-form output). Variants that enforce
        structured output return a JSON Schema dict.
        """
        return None
