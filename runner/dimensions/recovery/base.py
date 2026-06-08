"""RecoveryVariant ABC plus the Failure and RecoveryAction dataclasses.

A recovery variant decides what to do when the agent loop encounters
a failure: tool error, model refusal, validation failure, timeout, etc.
"""
from __future__ import annotations
from abc import abstractmethod
from dataclasses import dataclass, field

from ..base import DimensionVariant


@dataclass
class Failure:
    """A failure the agent loop has surfaced."""

    kind: str  # "tool_error" | "model_refusal" | "timeout" | "validation_failure"
    detail: dict = field(default_factory=dict)


@dataclass
class RecoveryAction:
    """What the recovery variant decided to do about the failure."""

    kind: str  # "retry" | "fallback" | "abort" | "ask_user"
    payload: dict = field(default_factory=dict)


class RecoveryVariant(DimensionVariant):
    """A variant that decides how to react to a failure."""

    dimension: str = "recovery"

    @abstractmethod
    def recover(self, failure: Failure, context: dict) -> RecoveryAction:
        """Decide what to do about the failure.

        context carries the in-flight task state (history, retry count
        so far, budget remaining).
        """
        raise NotImplementedError
