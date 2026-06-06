"""AdvisoryConsolidator — exposes the consolidation lifecycle for
lazy variants so integrators can schedule it independently of writes.

Stable public contract:

  AdvisoryConsolidator(normalizer: EntityNormalizer)

  .schedule_required() -> bool      (True if writes have accumulated since
                                     last consolidate)
  .last_consolidation: dict | None  (most recent consolidation summary)
  .write_count_since: int           (writes since last consolidate)
  .run() -> dict                    (run consolidate immediately; returns summary)

Two production deployment patterns:

  1. Cron / scheduled: call run() periodically (hourly, nightly).
     Use schedule_required() to skip empty consolidations.

  2. Event-driven / cadence: track write_count_since; call run() when
     it crosses a threshold. Combine with the cadence-invariance
     finding (docs/finding-cadence-invariance.md): final F1 is
     unaffected by cadence, only read freshness is.

Out of scope here: distributed locking, leader election, async I/O.
Those are deployment concerns for the integrator.
"""
from __future__ import annotations
from typing import Any

from .normalizer import EntityNormalizer


class AdvisoryConsolidator:
    def __init__(self, normalizer: EntityNormalizer):
        if not normalizer.supports_consolidate:
            raise ValueError(
                f"Variant {normalizer.variant_name} does not support "
                "consolidation. Use AdvisoryConsolidator only with lazy "
                "variants (v0.4.2+)."
            )
        self._normalizer = normalizer
        self._writes_since_last = 0
        self._last_summary: dict | None = None
        # Patch the variant's align_with_context to bump our counter.
        # Idempotent monkey-patch keyed by attribute presence.
        variant = normalizer._variant
        if not getattr(variant, "_advisory_consolidator_patched", False):
            original_align = variant.align_with_context

            def patched_align(input_relation: str, context: dict | None = None) -> str:
                self._writes_since_last += 1
                return original_align(input_relation, context)

            variant.align_with_context = patched_align  # type: ignore[method-assign]
            variant._advisory_consolidator_patched = True  # type: ignore[attr-defined]

    @property
    def write_count_since(self) -> int:
        return self._writes_since_last

    @property
    def last_consolidation(self) -> dict | None:
        return self._last_summary

    def schedule_required(self, min_writes: int = 1) -> bool:
        """True if at least min_writes new writes have accumulated since
        the last consolidate() call."""
        return self._writes_since_last >= min_writes

    def run(self) -> dict:
        summary = self._normalizer.consolidate()
        if summary is not None:
            self._last_summary = summary
        self._writes_since_last = 0
        return summary or {}
