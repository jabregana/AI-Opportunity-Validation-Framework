"""Six-dimension agent-system architecture.

An agent system varies along six measurable dimensions. This package is
the scaffolding for treating each dimension as a first-class evaluation
axis with the same statistical machinery (LORD++ FDR, paired bootstrap,
CUPED, CI gates, finding-doc culture) the rest of the framework already
applies to the schema-alignment proxy (memory dimension) and the graph
GC (memory dimension).

The six dimensions:

  1. model            - which LLM (or local model), which size tier
                        (covered today: experiments/ladder_sweep_real_data.py)
  2. prompt           - system prompts, instructions, output formats
                        (scaffolded here: dimensions/prompt/)
  3. tools            - which tools the agent can invoke, selection rules
                        (scaffolded here: dimensions/tools/)
  4. memory           - what is stored, canonicalization, lifecycle
                        (covered today: runner/variants/ + runner/gc_variants/;
                         migration target: dimensions/memory/)
  5. execution policy - how the agent decides the next step
                        (scaffolded here: dimensions/policy/)
  6. recovery         - retry, fallback, refusal handling, partial result
                        (scaffolded here: dimensions/recovery/)

Each sub-package follows the same shape as runner/variants/:
  base.py        - the dimension-specific Variant ABC plus its dataclasses
  b_noop.py      - the no-op baseline (the identity/null variant for
                   that dimension; used as the reference for UC gates)
  __init__.py    - FACTORIES dict + build(variant_id) helper

This package is the architecture; the existing runner/variants/ and
runner/gc_variants/ are case studies that pre-date the architecture
and will migrate under dimensions/memory/ in a future commit. The
migration is mechanical, not architectural; see
docs/six-dimensions-architecture.md for the plan.
"""
from __future__ import annotations

from .base import DimensionVariant

DIMENSIONS = ["model", "prompt", "tools", "memory", "policy", "recovery"]

__all__ = ["DimensionVariant", "DIMENSIONS"]
