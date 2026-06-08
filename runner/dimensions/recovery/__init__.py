"""Recovery dimension: variants that decide what to do when something
goes wrong.

A RecoveryVariant takes a Failure and returns a RecoveryAction. This
is where retry policy, fallback chains, refusal handling, partial-result
acceptance, and timeout escalation live.

Today this package contains only the abort baseline (no recovery; the
first failure ends the task). Real variants land here after the first
Stage 1 scan on the recovery dimension.
"""
from __future__ import annotations
from typing import Callable

from .base import Failure, RecoveryAction, RecoveryVariant
from .b_noop import AbortOnFailureVariant
from .fallback import FallbackChainVariant
from .retry import RetryWithBackoffVariant


FACTORIES: dict[str, Callable[[], RecoveryVariant]] = {
    "b-abort-on-failure": AbortOnFailureVariant,
    "recovery-v0.1.0-retry-with-backoff": RetryWithBackoffVariant,
    "recovery-v0.1.1-fallback-chain": FallbackChainVariant,
}


def build(variant_id: str) -> RecoveryVariant:
    if variant_id not in FACTORIES:
        raise KeyError(
            f"Unknown recovery variant {variant_id!r}. Known: {sorted(FACTORIES)}"
        )
    return FACTORIES[variant_id]()


__all__ = ["Failure", "RecoveryAction", "RecoveryVariant", "build", "FACTORIES"]
