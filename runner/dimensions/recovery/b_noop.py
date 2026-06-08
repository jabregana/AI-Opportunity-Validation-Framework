"""b-abort-on-failure: the no-recovery baseline for the recovery dimension.

Always returns abort. The first failure ends the task. Used as the
reference point for recovery-dimension UC gates: any retry/fallback/
ask-user variant must show its added complexity buys a measurable
gain on task-completion rate or correctness.
"""
from __future__ import annotations

from .base import Failure, RecoveryAction, RecoveryVariant


class AbortOnFailureVariant(RecoveryVariant):
    name = "b-abort-on-failure"

    def recover(self, failure: Failure, context: dict) -> RecoveryAction:
        return RecoveryAction(kind="abort", payload={"failure_kind": failure.kind})
