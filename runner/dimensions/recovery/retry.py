"""Retry-with-backoff recovery variant.

recovery-v0.1.0-retry-with-backoff: when a failure arrives that
belongs to a retryable kind, return a retry action with exponential
backoff. Abort once max_retries is reached or the failure kind is
not in the retryable set.

Mirrors LangChain RunnableRetry's shape (exponential backoff, max
attempts cap, exception-type filtering) but with the recovery-policy
benchmark's failure-kind taxonomy instead of exception classes. The
verified Day 1 finding (docs/recovery-stage2-day1-verification.md)
documented that LangChain / LangGraph offer this shape too; this
variant lets the harness benchmark whether the shape is enough on
the synthetic failure-injection workload.
"""
from __future__ import annotations

from .base import Failure, RecoveryAction, RecoveryVariant


# Failure kinds where a simple retry has a reasonable chance of
# resolving the underlying issue. Refusals are excluded (the model
# said no; retrying without changing anything is unlikely to help).
# Validation failures are excluded for the same reason (the output
# format mismatch will repeat unless something changes).
DEFAULT_RETRY_ON_KINDS = ("tool_error", "timeout")


class RetryWithBackoffVariant(RecoveryVariant):
    """Retry up to `max_retries` times with exponential backoff."""

    name = "recovery-v0.1.0-retry-with-backoff"

    def __init__(
        self,
        max_retries: int = 3,
        retry_on_kinds: tuple[str, ...] = DEFAULT_RETRY_ON_KINDS,
        initial_backoff_seconds: float = 0.5,
        backoff_factor: float = 2.0,
    ):
        self.max_retries = max_retries
        self.retry_on_kinds = set(retry_on_kinds)
        self.initial_backoff = initial_backoff_seconds
        self.backoff_factor = backoff_factor

    def recover(self, failure: Failure, context: dict) -> RecoveryAction:
        n_retries = int(context.get("n_retries", 0))
        if failure.kind not in self.retry_on_kinds:
            return RecoveryAction(
                kind="abort",
                payload={
                    "reason": "non_retryable_kind",
                    "failure_kind": failure.kind,
                },
            )
        if n_retries >= self.max_retries:
            return RecoveryAction(
                kind="abort",
                payload={
                    "reason": "max_retries_exhausted",
                    "failure_kind": failure.kind,
                    "n_retries": n_retries,
                },
            )
        backoff = self.initial_backoff * (self.backoff_factor ** n_retries)
        return RecoveryAction(
            kind="retry",
            payload={
                "backoff_seconds": backoff,
                "attempt": n_retries + 1,
            },
        )
