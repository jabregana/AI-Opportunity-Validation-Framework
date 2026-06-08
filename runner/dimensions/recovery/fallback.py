"""Fallback-chain recovery variant.

recovery-v0.1.1-fallback-chain: retry first (same shape as
recovery-v0.1.0), but on retry exhaustion fall back to a different
strategy chosen by failure kind:

  - tool_error          -> alternate_tool (try a different tool)
  - timeout             -> alternate_tool (likely a smaller/faster one)
  - validation_failure  -> structured_output_guard (re-prompt with
                           explicit schema)
  - model_refusal       -> larger_model (more capable model may
                           comply where the smaller one refused)

If the fallback fails too, abort. One fallback per failure (no
fallback-of-a-fallback ladder); that is intentionally simple for
v0.1.1 and a future v0.1.2 can introduce a longer ladder.

The fallback choice mapping is the load-bearing design decision
this variant is benchmarking: does a kind-aware fallback meaningfully
beat plain retry, given the cost of the fallback step? The Stage 2
finding doc answers that.
"""
from __future__ import annotations

from .base import Failure, RecoveryAction, RecoveryVariant
from .retry import DEFAULT_RETRY_ON_KINDS


FALLBACK_STRATEGY_BY_KIND = {
    "tool_error": "alternate_tool",
    "timeout": "alternate_tool",
    "validation_failure": "structured_output_guard",
    "model_refusal": "larger_model",
}


class FallbackChainVariant(RecoveryVariant):
    """Retry first; on exhaustion, fall back to a kind-specific strategy."""

    name = "recovery-v0.1.1-fallback-chain"

    def __init__(
        self,
        max_retries: int = 2,
        retry_on_kinds: tuple[str, ...] = DEFAULT_RETRY_ON_KINDS,
        max_fallbacks: int = 1,
    ):
        self.max_retries = max_retries
        self.retry_on_kinds = set(retry_on_kinds)
        self.max_fallbacks = max_fallbacks

    def recover(self, failure: Failure, context: dict) -> RecoveryAction:
        n_retries = int(context.get("n_retries", 0))
        n_fallbacks = int(context.get("n_fallbacks", 0))

        # First try the retry path for retryable kinds
        if failure.kind in self.retry_on_kinds and n_retries < self.max_retries:
            return RecoveryAction(
                kind="retry",
                payload={
                    "attempt": n_retries + 1,
                    "backoff_seconds": 0.5 * (2 ** n_retries),
                },
            )

        # Retry path exhausted (or kind never retryable). Try fallback.
        if n_fallbacks < self.max_fallbacks:
            strategy = FALLBACK_STRATEGY_BY_KIND.get(failure.kind, "alternate_tool")
            return RecoveryAction(
                kind="fallback",
                payload={
                    "strategy": strategy,
                    "failure_kind": failure.kind,
                    "fallback_number": n_fallbacks + 1,
                },
            )

        return RecoveryAction(
            kind="abort",
            payload={
                "reason": "all_options_exhausted",
                "failure_kind": failure.kind,
                "n_retries": n_retries,
                "n_fallbacks": n_fallbacks,
            },
        )
