"""Prompt dimension: variants that decide what prompt to send the model.

A PromptVariant takes a task input and returns the prompt string the
model should receive. Variants differ on system prompt, instruction
phrasing, output-format contract, few-shot examples, chain-of-thought
scaffolding, role framing, etc.

Today this package contains only the no-op baseline. Real variants
land here after the first Stage 1 scan on the prompt dimension.
"""
from __future__ import annotations
from typing import Callable

from .base import PromptVariant
from .b_noop import DefaultPromptVariant


FACTORIES: dict[str, Callable[[], PromptVariant]] = {
    "b-default-prompt": DefaultPromptVariant,
}


def build(variant_id: str) -> PromptVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown prompt variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["PromptVariant", "build", "FACTORIES"]
