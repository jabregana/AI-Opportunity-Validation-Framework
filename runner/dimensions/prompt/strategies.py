"""Prompt-strategy variants for Stage 2 baseline.

Five pilot strategies plus the existing default:

  prompt-v0.1.0-cot               - zero-shot chain-of-thought scaffolding
  prompt-v0.1.1-direct-structured - force JSON output, no CoT
  prompt-v0.1.2-few-shot-1        - prepend 1 example
  prompt-v0.1.3-few-shot-3        - prepend 3 examples
  prompt-v0.1.4-cot-plus-structured - CoT scaffolding + structured output

Each strategy implements PromptVariant.render(task_input) and may also
expose output_schema() for the runner to compute token cost. The
runner's simulator translates (strategy, task.category, task.difficulty)
into P(complete) and token cost.
"""
from __future__ import annotations

from .base import PromptVariant


COT_PREFIX = (
    "Think step-by-step before answering.\n\n"
    "Question: "
)
COT_SUFFIX = "\n\nLet's work through this carefully.\n\n"


STRUCTURED_SUFFIX = (
    "\n\nRespond as JSON with the shape:\n"
    '  {"answer": "..."}'
)


FEW_SHOT_EXAMPLES = [
    ('Extract the entities from: "Apple Inc reported Q3 earnings."',
     'Apple Inc, Q3, earnings'),
    ('What is the next step in the deployment process?',
     'Run the smoke tests after rollout.'),
    ('Is the sentiment of "Great product, terrible support" positive or negative?',
     'Mixed - positive on product, negative on support.'),
    ('Look up information about the latest API release.',
     'See changelog at /docs/changelog#2026-06.'),
    ('Refactor this for readability: x = [i*2 for i in range(10) if i%2]',
     '\n'.join([
         'doubled_odds = []',
         'for i in range(10):',
         '    if i % 2:',
         '        doubled_odds.append(i * 2)',
     ])),
]


def _few_shot_block(n: int) -> str:
    """Build a few-shot prefix block with n examples."""
    selected = FEW_SHOT_EXAMPLES[:n]
    parts = ["Here are some examples:\n"]
    for q, a in selected:
        parts.append(f"Q: {q}\nA: {a}\n")
    parts.append("\nNow answer this:\n")
    return "\n".join(parts)


class CoTPromptVariant(PromptVariant):
    name = "prompt-v0.1.0-cot"

    def render(self, task_input: dict) -> str:
        return COT_PREFIX + task_input.get("raw", "") + COT_SUFFIX


class DirectStructuredPromptVariant(PromptVariant):
    name = "prompt-v0.1.1-direct-structured"

    def render(self, task_input: dict) -> str:
        return task_input.get("raw", "") + STRUCTURED_SUFFIX

    def output_schema(self) -> dict | None:
        return {"type": "object", "properties": {"answer": {"type": "string"}}}


class FewShot1PromptVariant(PromptVariant):
    name = "prompt-v0.1.2-few-shot-1"

    def render(self, task_input: dict) -> str:
        return _few_shot_block(1) + task_input.get("raw", "")


class FewShot3PromptVariant(PromptVariant):
    name = "prompt-v0.1.3-few-shot-3"

    def render(self, task_input: dict) -> str:
        return _few_shot_block(3) + task_input.get("raw", "")


class CoTStructuredPromptVariant(PromptVariant):
    name = "prompt-v0.1.4-cot-plus-structured"

    def render(self, task_input: dict) -> str:
        return (
            COT_PREFIX
            + task_input.get("raw", "")
            + COT_SUFFIX
            + STRUCTURED_SUFFIX
        )

    def output_schema(self) -> dict | None:
        return {"type": "object", "properties": {"answer": {"type": "string"}}}
