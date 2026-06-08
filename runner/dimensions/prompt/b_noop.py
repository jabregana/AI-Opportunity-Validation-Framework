"""b-default-prompt: the no-op identity baseline for the prompt dimension.

Returns task_input["raw"] unchanged. Used as the reference point for
prompt-dimension UC gates: any non-trivial PromptVariant must beat or
match the unaltered raw input on the dimension's UC gates.
"""
from __future__ import annotations

from .base import PromptVariant


class DefaultPromptVariant(PromptVariant):
    name = "b-default-prompt"

    def render(self, task_input: dict) -> str:
        return task_input.get("raw", "")
