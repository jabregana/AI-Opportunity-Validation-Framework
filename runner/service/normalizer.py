"""EntityNormalizer — drop-in middleware for canonicalizing entity
surface forms before they reach a downstream memory or graph store.

Stable public contract:

  EntityNormalizer(variant_id: str | None = None,
                    *,
                    variant: Variant | None = None)

  .normalize(surface: str, context: dict | None = None) -> str
  .batch_normalize(items: Iterable[str], context: dict | None = None) -> list[str]
  .consolidate() -> dict | None   (no-op if the underlying variant is not Consolidatable)

  .variant_name: str   (informational; underlying variant id)
  .known_sources: list[str]   (for multi-tenant variants)

Usage examples:

    # Single-tenant
    from runner.service import EntityNormalizer
    norm = EntityNormalizer("embed-proxy-v0.3.1")
    canonical = norm.normalize("WORKS_AT")
    # -> "WORKS_AT" or whatever the variant decides

    # Multi-tenant (source attribution)
    norm = EntityNormalizer("embed-proxy-v0.4.4-adaptive")
    canonical = norm.normalize("Apple", context={"source_id": "sales"})
    # -> source-prefixed or merged canonical based on workload

    # As middleware in front of an arbitrary store
    def my_write_path(text, source_id):
        canonical = norm.normalize(text, context={"source_id": source_id})
        downstream_store.put(canonical, text)
"""
from __future__ import annotations
from typing import Iterable

from runner.variants import build, FACTORIES
from runner.variants.base import Variant


class EntityNormalizer:
    """Single-instance middleware over a Variant. Thread-safety follows
    the underlying variant (none of the v0.x variants are
    explicitly thread-safe; serialize calls or shard per-thread)."""

    def __init__(
        self,
        variant_id: str | None = None,
        *,
        variant: Variant | None = None,
    ):
        if variant is None and variant_id is None:
            raise ValueError("must provide variant_id or variant instance")
        if variant is None:
            if variant_id not in FACTORIES:
                raise KeyError(
                    f"unknown variant_id {variant_id!r}. Known: {sorted(FACTORIES)}"
                )
            variant = build(variant_id)
        self._variant = variant
        self.variant_name = variant.name

    def normalize(self, surface: str, context: dict | None = None) -> str:
        """Canonicalize one surface form. Returns the canonical string
        chosen by the underlying variant."""
        return self._variant.align_with_context(surface, context)

    def batch_normalize(
        self,
        items: Iterable[str],
        context: dict | None = None,
    ) -> list[str]:
        """Canonicalize many surface forms with the same context.
        For per-item contexts use a list comprehension over normalize().
        """
        return [self.normalize(s, context) for s in items]

    def consolidate(self) -> dict | None:
        """If the underlying variant supports consolidate (lazy variants),
        run it. Otherwise return None. Integrators can call this on
        their own cadence (cron, event-driven)."""
        consolidate_fn = getattr(self._variant, "consolidate", None)
        if consolidate_fn is None:
            return None
        return consolidate_fn()

    @property
    def known_sources(self) -> list[str]:
        """For multi-tenant variants, the set of source_ids that have
        been seen. Empty for single-tenant variants."""
        return getattr(self._variant, "known_sources", [])

    @property
    def supports_consolidate(self) -> bool:
        return hasattr(self._variant, "consolidate")
