"""Integration shims for the memory-lifecycle dimension.

A `GCIntegrationShim` is the contract a downstream memory framework
(Graphiti, Mem0, Cognee, etc) needs to satisfy so a `GCVariant` can
sweep its store. The variant operates on a normalized `GraphState`;
the shim translates between the downstream's native API and that
normalized form.

Sub-modules:
  base.py - the GCIntegrationShim ABC
  mock.py - an in-memory mock shim used for testing the contract and
            for the Stage 4 architectural validation run; mimics the
            shape of Graphiti's per-tenant graph
"""
from __future__ import annotations

from .base import GCIntegrationShim, IntegrationStats
from .mock import MockGraphStoreShim

__all__ = ["GCIntegrationShim", "IntegrationStats", "MockGraphStoreShim"]
