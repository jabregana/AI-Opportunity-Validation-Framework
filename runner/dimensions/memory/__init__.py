"""Memory dimension: variants that decide how the agent's memory store
is canonicalized (canonicalization sub-package) and pruned over time
(lifecycle sub-package).

Sub-packages:
  canonicalization/  - schema-alignment Variant ABC + 14 variant
                       implementations (embed-proxy family, per-source,
                       ANN, etc). The proxy case study lives here.
  lifecycle/         - GCVariant ABC + the b-raw / ref-count / utility /
                       fact-only variants. The graph-GC case study
                       lives here.

These sub-packages were originally at runner/variants/ and
runner/gc_variants/ respectively and moved here as the architectural
home for the memory dimension's variants. Backward-compat shims at
the old paths re-export from here; see runner/variants/__init__.py
and runner/gc_variants/__init__.py.
"""
from __future__ import annotations

from . import canonicalization, lifecycle

__all__ = ["canonicalization", "lifecycle"]
