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
from .strategies import (
    CoTPromptVariant,
    CoTStructuredPromptVariant,
    DirectStructuredPromptVariant,
    FewShot1PromptVariant,
    FewShot3PromptVariant,
)


FACTORIES: dict[str, Callable[[], PromptVariant]] = {
    "b-default-prompt": DefaultPromptVariant,
    "prompt-v0.1.0-cot": CoTPromptVariant,
    "prompt-v0.1.1-direct-structured": DirectStructuredPromptVariant,
    "prompt-v0.1.2-few-shot-1": FewShot1PromptVariant,
    "prompt-v0.1.3-few-shot-3": FewShot3PromptVariant,
    "prompt-v0.1.4-cot-plus-structured": CoTStructuredPromptVariant,
}


def build(variant_id: str) -> PromptVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown prompt variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["PromptVariant", "build", "FACTORIES"]
