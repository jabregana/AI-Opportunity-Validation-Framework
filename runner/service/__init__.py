"""Public service API.

The harness underneath this package is the experimentation layer:
workloads, variants, statistical gates, finding docs. This package is
the EXTERNAL API: stable interfaces that integrators can build against
without coupling to the harness internals.

Two public surfaces:

  EntityNormalizer
    Drop-in middleware that turns surface forms into canonical entity
    names. Wraps a Variant. Stable contract: `normalize(surface, context)
    -> canonical`. Source attribution is optional; single-tenant
    callers can omit it.

  AdvisoryConsolidator
    Wraps any Variant that exposes a `consolidate()` method. Exposes
    the consolidation lifecycle as discrete operations so integrators
    can run consolidation on their own cadence (event-driven, cron,
    scheduled job).

Both classes are deliberately small. The goal is for an integrator
to be able to drop the proxy in front of an existing memory system
(Mem0, Graphiti, Cognee, custom) without touching the harness or
caring which variant version they are on. Variant upgrades change
behavior, not the API surface.
"""
from __future__ import annotations
from .normalizer import EntityNormalizer
from .consolidator import AdvisoryConsolidator

__all__ = ["EntityNormalizer", "AdvisoryConsolidator"]
